from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from config import AppConfig
from market import BinanceMarketClient, MarketError, MarketSnapshot
from parser import ForwardStatus, parse_status_file
from portfolio import PortfolioError, PortfolioSnapshot, load_portfolio, load_combined_portfolio
from report import build_latest_report
from runner import DailyModelRunner, RunResult
from storage import MonitorStorage, StorageError
from execution_summary import appended_rows, latest_ledger_summary, read_ledgers, render_summary
from cost_view import update_cost_view


@dataclass(frozen=True)
class DashboardSnapshot:
    status: ForwardStatus | None
    market: MarketSnapshot | None
    market_error: str | None
    status_error: str | None
    v310_portfolio: PortfolioSnapshot | None
    v31_portfolio: PortfolioSnapshot | None
    portfolio_errors: tuple[str, ...]
    latest_report: str
    history: list[dict[str, str]]
    runner_state: dict[str, object]
    refreshed_at: datetime
    market_last_successful_update: datetime | None
    execution_summary: str = ""
    ai_view: dict | None = None
    combined_portfolio: PortfolioSnapshot | None = None


class MonitorController:
    """Deep interface separating read-only refresh from model execution."""

    def __init__(
        self, config: AppConfig, storage: MonitorStorage,
        runner: DailyModelRunner, market_client: BinanceMarketClient,
        *, clock: Callable[[], datetime] | None = None,
        ai_orchestrator=None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.runner = runner
        self.market_client = market_client
        self.ai = ai_orchestrator
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.last_market: MarketSnapshot | None = None
        self.market_last_successful_update: datetime | None = None

    def refresh(self) -> DashboardSnapshot:
        """Read status/history and fetch market data; never launch a model."""
        now = self.clock().astimezone()
        market_error: str | None = None
        status_error: str | None = None
        try:
            self.last_market = self.market_client.fetch()
            self.market_last_successful_update = now
        except MarketError as exc:
            market_error = str(exc)
        try:
            status = parse_status_file(self.config.status_file)
        except (FileNotFoundError, ValueError, OSError) as exc:
            status = None
            status_error = str(exc)
        portfolios: list[PortfolioSnapshot | None] = []
        portfolio_errors: list[str] = []
        for label, path in (
            ("V3.10", self.config.v310_portfolio_file),
            ("V3.1", self.config.v31_portfolio_file),
        ):
            try:
                portfolios.append(load_portfolio(
                    path, self.last_market, cost_path=self.config.app_data_dir / "data/average_cost.json",
                    model="Q" if label == "V3.10" else "B",
                ))
            except (PortfolioError, OSError) as exc:
                portfolios.append(None)
                portfolio_errors.append(f"{label}: {exc}")
        history = self.storage.load_history()
        runner_state = self.storage.load_runner_state()
        runner_state["last_refresh_time"] = now.isoformat()
        self.storage.save_runner_state(runner_state)
        report = build_latest_report(status, self.last_market) if status else "LATEST REPORT\n\nSTATUS FILE NOT FOUND OR INVALID."
        ai_view = self.load_ai_view()
        try:
            combined = load_combined_portfolio(ai_view, self.last_market)
        except (PortfolioError, TypeError) as exc:
            combined = None
            portfolio_errors.append(f"V3.10＋AI: {exc}")
        if market_error:
            # A failed refresh does not make cached prices current again.
            def cached(portfolio):
                return replace(portfolio, valuation="行情更新失敗 · 沿用上次估值，非最新價格") if portfolio else None
            portfolios = [cached(p) for p in portfolios]
            combined = cached(combined)
        return DashboardSnapshot(
            status=status, market=self.last_market, market_error=market_error,
            status_error=status_error, v310_portfolio=portfolios[0], v31_portfolio=portfolios[1],
            portfolio_errors=tuple(portfolio_errors),
            latest_report=report, history=history,
            runner_state=runner_state, refreshed_at=now,
            market_last_successful_update=self.market_last_successful_update,
            execution_summary=self.load_execution_summary(),
            ai_view=ai_view, combined_portfolio=combined,
        )

    def auto_refresh_tick(self) -> DashboardSnapshot:
        return self.refresh()

    def refresh_now(self) -> DashboardSnapshot:
        return self.refresh()

    def run_daily_model(self, *, force: bool = False) -> RunResult:
        start = self.clock().astimezone()
        directory = self.config.status_file.parent
        before = read_ledgers(directory)
        result = self.runner.run(force=force)
        if result.outcome == "TODAY_ALREADY_COMPLETED":
            cost_message = update_cost_view(self.config)
            return replace(result, execution_summary="今天已成功執行過，沒有重複執行；以下是先前紀錄。\n" + cost_message + "\n\n" + self.load_execution_summary())
        delta = appended_rows(before, read_ledgers(directory))
        end = self.clock().astimezone()
        context = f"本次操作：{start.isoformat()} 至 {end.isoformat()}\n執行結果：{result.outcome}"
        if not result.completed:
            context += f"\n模型執行未成功：{result.message}。以下僅呈現帳本差異，不代表執行已完整完成。"
        summary = render_summary(delta, heading="本次模型執行摘要", context=context)
        if result.completed:
            summary += "\n\n【持倉均價】\n" + update_cost_view(self.config)
        try:
            self.storage.save_execution_summary(summary, end)
        except (OSError, StorageError) as exc:
            summary += f"\n\n摘要保存失敗（不影響模型原始結果）：{exc}"
        return replace(result, execution_summary=summary)

    def run_daily_cycle(self, *, force: bool = False, progress=None):
        from ai_shadow.daily_cycle import DailyCycleOrchestrator
        if self.ai:
            self.ai.progress = progress or (lambda _: None)
        cycle = DailyCycleOrchestrator(self.run_daily_model, self.ai, progress).run(force=force)
        if self.ai and self.ai.settings().get('strategy_mode') == 'v310_hybrid':
            from ai_shadow.combined import render_combined_result
            try:
                quant, _, _ = self.ai.read_forward()
                combined = render_combined_result(quant, cycle.ai, self.load_ai_view())
            except Exception:
                # Presentation failure cannot invalidate an already committed
                # quant/AI cycle or cause the user to repeat paper execution.
                combined = '綜合摘要暫時無法讀取；請查看原始執行紀錄，不需重複下達模型執行。'
            summary = combined+'\n\n【純 V3.10 執行紀錄】\n'+cycle.v310.execution_summary
            try:
                self.storage.save_execution_summary(summary, self.clock().astimezone())
            except (OSError, StorageError):
                summary += '\n摘要未能保存；原始模型與紙上帳本結果不受影響。'
            cycle = replace(cycle, v310=replace(cycle.v310, execution_summary=summary))
        return cycle

    def load_ai_view(self):
        try:
            return self.ai.view() if self.ai else None
        except Exception:
            return {'outcome':'AI_STATE_READ_FAILED'}

    def load_execution_summary(self) -> str:
        try:
            return self.storage.load_execution_summary() or latest_ledger_summary(self.config.status_file.parent)
        except (OSError, UnicodeError) as exc:
            return f"執行摘要無法讀取：{exc}"
