from __future__ import annotations

import os
import sys
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
import customtkinter as ctk

from config import AppConfig, ConfigError, load_config, save_config
from controller import DashboardSnapshot, MonitorController
from market import BinanceMarketClient
from portfolio import PortfolioSnapshot
from runner import DailyModelRunner, ModelRunInProgress, RunResult
from storage import MonitorStorage
from report import STATE_LABELS, _action_explanation
from ui import DashboardLayout, UI_COLORS, UI_FONT
from ui_components import font
from ui_dispatch import UiDispatcher


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
ICON_PATH = APP_DIR / "CryptoForwardMonitor.ico" if getattr(sys, "frozen", False) else APP_DIR / "assets" / "CryptoForwardMonitor.ico"


def fmt_money(value: float | None) -> str:
    return "N/A" if value is None else f"${value:,.2f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}%"


class HistoryViewer(ctk.CTkToplevel):
    def __init__(self, parent: tk.Misc, history: list[dict[str, str]]) -> None:
        super().__init__(parent)
        self.configure(fg_color=UI_COLORS["background"])
        self.title("Crypto Forward Monitor｜歷史紀錄")
        self.geometry("1200x580")
        # Keep this owned by the monitor, not behind it when CTk restores focus
        # after its Windows titlebar redraw. Do not use global always-on-top.
        self.transient(parent)
        self._present_after_id = None
        self.history = history
        controls = ttk.Frame(self, padding=14, style="App.TFrame")
        controls.pack(fill="x")
        ttk.Label(controls, text="顯示範圍：").pack(side="left")
        self.range_var = tk.StringVar(value="最近 30 天")
        combo = ctk.CTkOptionMenu(
            controls, variable=self.range_var, width=130, font=font(14), dropdown_font=font(14),
            values=["最近 30 天", "最近 90 天", "全部"], command=lambda _: self.populate(),
            fg_color=UI_COLORS["surface_alt"], button_color=UI_COLORS["surface_alt"],
            button_hover_color=UI_COLORS["track"], dropdown_fg_color=UI_COLORS["surface_alt"],
        )
        combo.pack(side="left", padx=6)
        columns = (
            "status_date", "btc", "eth", "v310_state", "v310_stage",
            "v310_target_exposure", "v310_actual_exposure", "v310_exposure_gap",
            "current_drawdown", "stage3_candidate", "crash", "ahr999",
            "frozen_hash_status", "current_evaluation",
        )
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.tree = ttk.Treeview(frame, columns=columns, show="headings")
        labels = {
            "status_date": "狀態日期", "btc": "BTC", "eth": "ETH", "v310_state": "狀態",
            "v310_stage": "階段", "v310_target_exposure": "目標曝險 %",
            "v310_actual_exposure": "實際曝險 %", "v310_exposure_gap": "曝險差距 %",
            "current_drawdown": "目前回撤 %", "stage3_candidate": "Stage3 候選", "crash": "崩盤訊號",
            "ahr999": "AHR999", "frozen_hash_status": "凍結雜湊", "current_evaluation": "目前評估",
        }
        scale = ctk.ScalingTracker.get_window_scaling(parent)
        for column in columns:
            self.tree.heading(column, text=labels[column])
            self.tree.column(column, width=round(125 * scale), anchor="center")
        self.tree.column("status_date", width=round(240 * scale))
        self.tree.column("current_evaluation", width=round(260 * scale))
        ybar = ctk.CTkScrollbar(frame, orientation="vertical", command=self.tree.yview,
                              button_color=UI_COLORS["track"])
        xbar = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.tree.xview,
                              button_color=UI_COLORS["track"])
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        self.populate()

    def present(self) -> None:
        self.deiconify()
        self.lift()
        if self._present_after_id is not None:
            self.after_cancel(self._present_after_id)
        self._present_after_id = self.after(250, self._focus_ready)

    def _focus_ready(self) -> None:
        self._present_after_id = None
        self.lift()
        self.tree.focus_set()

    def destroy(self) -> None:
        if self._present_after_id is not None:
            self.after_cancel(self._present_after_id)
            self._present_after_id = None
        super().destroy()

    def populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        days = {"最近 30 天": 30, "最近 90 天": 90, "全部": None}[self.range_var.get()]
        rows = self.history
        if days:
            cutoff = datetime.now().astimezone() - timedelta(days=days)
            filtered: list[dict[str, str]] = []
            for row in rows:
                try:
                    if datetime.fromisoformat(row.get("status_date", "").replace("Z", "+00:00")) >= cutoff:
                        filtered.append(row)
                except (TypeError, ValueError):
                    continue
            rows = filtered
        for row in reversed(rows):
            self.tree.insert("", "end", values=[row.get(column, "") for column in self.tree["columns"]])


class CryptoForwardMonitorApp(DashboardLayout, ctk.CTk):
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        ctk.set_appearance_mode("dark")
        # Enable awareness before Tk creates a window or caches screen metrics.
        # The packaged EXE also declares this in app.manifest.
        ctk.ScalingTracker.activate_high_dpi_awareness()
        super().__init__()
        self.title("Crypto Forward Monitor｜加密貨幣前瞻監控")
        if ICON_PATH.is_file():
            try:
                self.iconbitmap(default=str(ICON_PATH))
            except tk.TclError:
                pass
        scale = ctk.ScalingTracker.get_window_scaling(self)
        width = min(1560, int(self.winfo_screenwidth() / scale) - 80)
        height = min(960, int(self.winfo_screenheight() / scale) - 110)
        self.geometry(f"{width}x{height}+40+30")
        self.minsize(1080, 680)
        self.config_path = config_path
        self.config_data = load_config(config_path)
        self.storage = MonitorStorage(self.config_data.app_data_dir)
        self.runner = DailyModelRunner(self.config_data, self.storage)
        self.controller = MonitorController(
            self.config_data, self.storage, self.runner,
            BinanceMarketClient(timeout=self.config_data.market_timeout_seconds),
        )
        self.refresh_in_progress = False
        self.model_in_progress = False
        self.history_window: HistoryViewer | None = None
        self.latest_snapshot: DashboardSnapshot | None = None
        self.auto_after_id: str | None = None
        self.dispatcher = UiDispatcher()
        self._poll_after_id = None
        self._variables()
        self._styles()
        self._layout()
        self._tick_clock()
        self._drain_ui_events()
        self.after(100, self.refresh_dashboard)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def _variables(self) -> None:
        self.vars = {name: tk.StringVar(value="--") for name in [
            "current_time", "last_refresh", "last_model_run", "daily_model", "market_status",
            "btc_price", "btc_change", "btc_time", "eth_price", "eth_change", "eth_time",
            "q_state", "q_stage", "q_target", "q_actual", "q_gap",
            "b_state", "b_stage", "b_target", "b_actual", "b_diff",
            "stage3", "crash", "ahr", "drawdown", "frozen_hash", "evaluation", "next_trigger",
            "evaluation_eligibility", "status_utc", "status_local", "warning",
            "q_portfolio_total", "q_portfolio_btc", "q_portfolio_eth", "q_portfolio_cash", "q_portfolio_time",
            "b_portfolio_total", "b_portfolio_btc", "b_portfolio_eth", "b_portfolio_cash", "b_portfolio_time",
            "portfolio_status",
            "q_btc_average", "q_eth_average", "b_btc_average", "b_eth_average",
            "q_cost_status", "b_cost_status",
            "q_btc_pnl", "q_eth_pnl", "b_btc_pnl", "b_eth_pnl",
            "q_state_label", "b_state_label", "action_raw", "crash_label", "stage3_label",
        ]}
        self.allocation_percentages = {"q": (0.0, 0.0, 0.0), "b": (0.0, 0.0, 0.0)}
        self.allocation_canvases: dict[str, tk.Canvas] = {}
        self.auto_var = tk.BooleanVar(value=self.config_data.auto_refresh)
        seconds_to_label = {10: "10 秒", 30: "30 秒", 60: "60 秒", 300: "5 分鐘"}
        self.interval_var = tk.StringVar(value=seconds_to_label[self.config_data.market_refresh_seconds])
        self.action_var = tk.StringVar(value="NO_ACTION（無動作）")


    def _tick_clock(self) -> None:
        self.vars["current_time"].set(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))
        self._clock_after_id = self.after(1000, self._tick_clock)

    def _drain_ui_events(self) -> None:
        try:
            self.dispatcher.drain()
        finally:
            self._poll_after_id = self.after(60, self._drain_ui_events)

    def auto_changed(self) -> None:
        mapping = {"10 秒": 10, "30 秒": 30, "60 秒": 60, "5 分鐘": 300}
        self.config_data = replace(
            self.config_data, auto_refresh=self.auto_var.get(),
            market_refresh_seconds=mapping[self.interval_var.get()],
        )
        try:
            save_config(self.config_path, self.config_data)
        except OSError as exc:
            messagebox.showerror("設定錯誤", str(exc), parent=self)
        self.schedule_auto_refresh()

    def schedule_auto_refresh(self) -> None:
        if self.auto_after_id:
            self.after_cancel(self.auto_after_id); self.auto_after_id = None
        if self.auto_var.get():
            self.auto_after_id = self.after(self.config_data.market_refresh_seconds * 1000, self._auto_tick)

    def _auto_tick(self) -> None:
        self.auto_after_id = None
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        self.refresh_button.configure(state="disabled", text="更新中…")
        self.footer_var.set("正在重新整理市場與狀態（不執行模型）……")

        def worker() -> None:
            try:
                snapshot = self.controller.refresh_now()
                self.dispatcher.post(self.apply_snapshot, snapshot)
            except Exception as exc:
                self.dispatcher.post(self.show_error, "重新整理失敗", exc)
            finally:
                self.dispatcher.post(self._refresh_finished)
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_finished(self) -> None:
        self.refresh_in_progress = False
        self.refresh_button.configure(state="normal", text="更新行情")
        self.schedule_auto_refresh()

    def apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self.latest_snapshot = snapshot
        self.vars["last_refresh"].set(snapshot.refreshed_at.strftime("%H:%M:%S"))
        state = snapshot.runner_state
        last_run = str(state.get("last_run_time") or "從未執行")
        self.vars["last_model_run"].set(last_run[5:16].replace("T", " ") if len(last_run) >= 19 else last_run)
        completed = state.get("last_successful_local_date") == datetime.now().astimezone().date().isoformat()
        self.vars["daily_model"].set("今日已完成" if completed else "今日尚未執行")
        self.daily_model_label.configure(style="MetricSuccess.TLabel" if completed else "MetricWarning.TLabel")
        if getattr(self, "model_in_progress", False):
            self.vars["daily_model"].set("模型執行中…")
            self.daily_model_label.configure(style="MetricWarning.TLabel")
        if snapshot.market:
            self.vars["btc_price"].set(fmt_money(snapshot.market.btc.price))
            self.vars["btc_change"].set(f"{snapshot.market.btc.change_24h_percent:+.2f}% / 24h")
            self.vars["btc_time"].set(snapshot.market.btc.data_timestamp.astimezone().strftime("更新於 %H:%M:%S"))
            self.vars["eth_price"].set(fmt_money(snapshot.market.eth.price))
            self.vars["eth_change"].set(f"{snapshot.market.eth.change_24h_percent:+.2f}% / 24h")
            self.vars["eth_time"].set(snapshot.market.eth.data_timestamp.astimezone().strftime("更新於 %H:%M:%S"))
            for asset, change in (
                ("btc", snapshot.market.btc.change_24h_percent),
                ("eth", snapshot.market.eth.change_24h_percent),
            ):
                style_name = "Positive.TLabel" if change > 0 else "Negative.TLabel" if change < 0 else "Neutral.TLabel"
                getattr(self, f"{asset}_change_label").configure(style=style_name)
        if snapshot.market_error:
            last = snapshot.market_last_successful_update.strftime("%H:%M:%S") if snapshot.market_last_successful_update else "無"
            self.vars["market_status"].set(f"市場資料暫時無法取得｜上次成功更新：{last}")
            self.market_status_label.configure(style="Warning.TLabel")
        else:
            self.vars["market_status"].set("市場資料即時連線中")
            self.market_status_label.configure(style="Success.TLabel")
        if snapshot.status_error:
            self.footer_var.set(snapshot.status_error)
        self._update_portfolio("q", snapshot.v310_portfolio)
        self._update_portfolio("b", snapshot.v31_portfolio)
        self.vars["portfolio_status"].set(
            "資產配置讀取失敗｜" + "｜".join(snapshot.portfolio_errors)
            if snapshot.portfolio_errors else "依各模型紙上持倉計算；即時價格變動不代表模型已執行交易。"
        )
        status = snapshot.status
        if status:
            for key, value in {
                "q_state": status.v310_state, "q_stage": str(status.v310_stage),
                "q_target": fmt_pct(status.v310_target_exposure), "q_actual": fmt_pct(status.v310_actual_exposure),
                "q_gap": fmt_pct(status.v310_exposure_gap), "b_state": status.v31_state or "N/A",
                "b_stage": str(status.v31_stage if status.v31_stage is not None else "N/A"),
                "b_target": fmt_pct(status.v31_target_exposure), "b_actual": fmt_pct(status.v31_actual_exposure),
                "b_diff": fmt_pct(status.shadow_actual_exposure_diff), "stage3": status.stage3_candidate,
                "crash": status.crash, "ahr": "N/A" if status.ahr999 is None else f"{status.ahr999:.6f}",
                "drawdown": fmt_pct(status.current_drawdown, 4), "frozen_hash": status.frozen_hash_status,
                "evaluation": status.current_evaluation, "next_trigger": status.next_risk_trigger,
                "evaluation_eligibility": "可進行正式評估" if status.evaluation_eligible else "證據不足，暫不可正式評估",
                "status_utc": status.status_date.isoformat(),
                "status_local": status.status_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
            }.items():
                self.vars[key].set(value)
            self.vars["q_state_label"].set(STATE_LABELS.get(status.v310_state, status.v310_state))
            self.vars["b_state_label"].set(STATE_LABELS.get(status.v31_state, status.v31_state or "等待資料"))
            for key, raw in (("crash_label", status.crash), ("stage3_label", status.stage3_candidate)):
                self.vars[key].set({"YES": "有", "NO": "無"}.get(raw.upper(), raw))
            safety_failed = "FAIL" in status.current_evaluation.upper() or status.frozen_hash_status != "PASS"
            if safety_failed:
                self.vars["evaluation_eligibility"].set("安全驗證未通過 · 請查看報告與日誌")
            self.eligibility_label.configure(style="Danger.TLabel" if safety_failed else "Warning.TLabel")
            warnings = []
            if status.crash.upper() == "YES": warnings.append("崩盤訊號已啟動")
            if status.stage3_candidate.upper() != "NO": warnings.append("出現新的 Stage3 候選")
            if status.frozen_hash_status != "PASS": warnings.append("凍結雜湊警告")
            self.vars["warning"].set(" | ".join(warnings))
            actions = [item.strip() for item in status.today_tactical_action.split("|") if item.strip()]
            self.action_var.set("\n\n".join(_action_explanation(item).split("\n")[0] for item in actions) or "今天沒有新的紙上模型動作")
            self.vars["action_raw"].set("\n".join(actions) or "NO_ACTION")
            oos = status.oos_elapsed or 0; resolved = status.resolved_candidates or 0
            self.oos_bar["value"] = min(180, oos); self.oos_text.configure(text=f"{oos:.2f} 天 / 180 天")
            self.candidate_bar["value"] = min(3, resolved); self.candidate_text.configure(text=f"{resolved} 個 / 3 個")
        else:
            self.vars["evaluation_eligibility"].set("模型狀態無法讀取 · 請查看日誌")
            self.eligibility_label.configure(style="Danger.TLabel")
        self._write_report(snapshot.latest_report)
        self._write_execution_summary(snapshot.execution_summary)
        self.recent_list.delete(0, "end")
        for row in reversed(snapshot.history[-10:]):
            date = row.get("status_date", "")[:10]
            action = row.get("today_tactical_action", "") or "NO_ACTION（無動作）"
            self.recent_list.insert("end", f"{date}  {action}")
        if not snapshot.status_error:
            self.footer_var.set("重新整理完成；本次未執行模型。")

    def _update_portfolio(self, prefix: str, portfolio: PortfolioSnapshot | None) -> None:
        if portfolio is None:
            for asset in ("btc", "eth"):
                self.vars[f"{prefix}_{asset}_average"].set("均價：無資料")
                self.vars[f"{prefix}_{asset}_pnl"].set("浮動盈虧：—")
                self._set_pnl_color(prefix, asset, None)
            self.vars[f"{prefix}_cost_status"].set("持倉無法讀取，均價不可用")
            for key in ("total", "btc", "eth", "cash"):
                self.vars[f"{prefix}_portfolio_{key}"].set("無資料")
            self.vars[f"{prefix}_portfolio_time"].set("持倉資料無法讀取")
            self.allocation_percentages[prefix] = (0.0, 0.0, 0.0)
        else:
            for asset in ("btc", "eth"):
                average = getattr(portfolio, f"{asset}_average_cost")
                units = getattr(portfolio, f"{asset}_units")
                value = fmt_money(average) if average is not None else ("未持有" if units <= 1e-12 else "待核對")
                self.vars[f"{prefix}_{asset}_average"].set(f"成本均價：{value}")
                pnl = portfolio.unrealized_return(asset)
                self.vars[f"{prefix}_{asset}_pnl"].set("浮動盈虧：—" if pnl is None else f"浮動盈虧：{pnl:+.2f}%")
                self._set_pnl_color(prefix, asset, pnl)
            self.vars[f"{prefix}_cost_status"].set(portfolio.cost_status)
            self.vars[f"{prefix}_portfolio_total"].set(fmt_money(portfolio.total_value))
            self.vars[f"{prefix}_portfolio_btc"].set(f"{fmt_money(portfolio.btc_value)}｜{portfolio.btc_percent:.2f}%")
            self.vars[f"{prefix}_portfolio_eth"].set(f"{fmt_money(portfolio.eth_value)}｜{portfolio.eth_percent:.2f}%")
            self.vars[f"{prefix}_portfolio_cash"].set(f"{fmt_money(portfolio.cash_value)}｜{portfolio.cash_percent:.2f}%")
            local_time = portfolio.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
            self.vars[f"{prefix}_portfolio_time"].set(f"持倉：{local_time}\n估值：{portfolio.valuation}")
            self.allocation_percentages[prefix] = (
                portfolio.btc_percent, portfolio.eth_percent, portfolio.cash_percent,
            )
        self._draw_allocation_bar(prefix)

    def _set_pnl_color(self, prefix: str, asset: str, value: float | None) -> None:
        color = "muted" if value is None or abs(value) < 0.005 else ("green" if value > 0 else "red")
        self.pnl_labels[f"{prefix}_{asset}"].configure(text_color=UI_COLORS[color])

    def _draw_allocation_bar(self, prefix: str) -> None:
        bar = self.allocation_canvases.get(prefix)
        if bar is not None:
            bar.set_allocation(self.allocation_percentages[prefix])

    def _write_report(self, report: str) -> None:
        if self.report_text.get("1.0", "end-1c") == report:
            return
        scroll_position = self.report_text.yview()[0]
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", report)
        for line_number, line in enumerate(report.splitlines(), start=1):
            start = f"{line_number}.0"
            end = f"{line_number}.end"
            if line.startswith("最新報告"):
                self.report_text.tag_add("report_title", start, end)
            elif line.startswith("【"):
                self.report_text.tag_add("report_section", start, end)
            elif line.startswith("注意："):
                self.report_text.tag_add("report_note", start, end)
        self.report_text.configure(state="disabled")
        self.report_text.yview_moveto(scroll_position)

    def run_model(self) -> None:
        self._start_model(force=False)

    def _write_execution_summary(self, summary: str) -> None:
        if self.execution_text.get("1.0", "end-1c") == summary:
            return
        self.execution_text.configure(state="normal")
        self.execution_text.delete("1.0", "end")
        self.execution_text.insert("1.0", summary or "尚無執行摘要；請更新畫面讀取既有帳本。")
        self.execution_text.configure(state="disabled")

    def force_run(self) -> None:
        approved = messagebox.askyesno(
            "確認強制執行",
            "這會重新執行今天的前瞻測試。\n\n凍結模型規則不會被修改。\n\n確定要繼續嗎？",
            parent=self,
        )
        if approved:
            self._start_model(force=True)

    def _start_model(self, *, force: bool) -> None:
        if self.model_in_progress:
            self.notify("模型目前已在執行中，可以繼續瀏覽其他分頁。")
            return
        self.model_in_progress = True
        self.run_button.configure(state="disabled", text="模型執行中…")
        self.vars["daily_model"].set("模型執行中……")
        self.footer_var.set("模型執行中……")

        def worker() -> None:
            try:
                result = self.controller.run_daily_model(force=force)
                self.dispatcher.post(self.model_finished, result)
            except ModelRunInProgress as exc:
                self.dispatcher.post(self.show_error, "模型", exc)
                self.dispatcher.post(self._model_reset)
            except Exception as exc:
                self.dispatcher.post(self.show_error, "模型執行失敗", exc)
                self.dispatcher.post(self._model_reset)
        threading.Thread(target=worker, daemon=True).start()

    def model_finished(self, result: RunResult) -> None:
        self._model_reset()
        if result.execution_summary:
            self._write_execution_summary(result.execution_summary)
            self.show_page("執行摘要")
        if result.outcome == "TODAY_ALREADY_COMPLETED":
            self.notify("今天已成功執行過，未重複執行。")
        elif result.completed:
            self.notify("模型執行完成，正在更新資產與報告。")
        else:
            self.notify("模型執行失敗：" + result.message, error=True)
        self.refresh_dashboard()

    def _model_reset(self) -> None:
        self.model_in_progress = False
        self.run_button.configure(state="normal", text="執行每日模型")

    def open_history(self) -> None:
        rows = self.storage.load_history()
        if self.history_window is None or not self.history_window.winfo_exists():
            self.history_window = HistoryViewer(self, rows)
        else:
            self.history_window.history = rows
            self.history_window.populate()
        self.history_window.present()

    def open_path(self, path: Path) -> None:
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                raise OSError("開啟功能僅支援 Windows。")
        except OSError as exc:
            self.show_error("開啟失敗", exc)

    def show_error(self, title: str, error: BaseException) -> None:
        self.footer_var.set(f"{title}: {error}")
        self.notify(f"{title}：{error}", error=True)

    def close(self) -> None:
        self.dispatcher.close()
        for timer in (self._poll_after_id, self._clock_after_id, self._notice_after_id):
            if timer:
                self.after_cancel(timer)
        if self.auto_after_id:
            self.after_cancel(self.auto_after_id)
        self.destroy()


def main() -> int:
    try:
        app = CryptoForwardMonitorApp()
    except ConfigError as exc:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("設定錯誤", str(exc), parent=root)
        root.destroy()
        return 2
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
