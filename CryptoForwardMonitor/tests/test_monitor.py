from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from config import AppConfig
from controller import MonitorController
from market import BinanceMarketClient, MarketError, MarketQuote, MarketSnapshot
from parser import StatusValidationError, parse_status
from portfolio import PortfolioError, load_portfolio
from report import build_latest_report
from runner import DailyModelRunner, ModelRunInProgress
from storage import MonitorStorage, StorageError


SAMPLE = """# DAILY FORWARD STATUS

* Label: `FORWARD_PAPER_ONLY`
* Date: `2026-09-04T04:00:00+00:00`
* BTC: `$80,656.87`
* ETH: `$2,504.39`
* V3.10 State / Stage / Target / Actual Exposure: `NEW_BULL` / `0` / `95.00%` / `48.71%`
* V3.1 Shadow State / Stage / Target / Actual Exposure: `NEW_BULL` / `0` / `95.00%` / `48.69%`
* Stage3 Candidate: `NO`
* Crash: `NO`
* AHR999: `0.5477930955779716`
* Today Tactical Action: `NEW_BULL_CONFIRMED|NEW_BULL_REDEPLOY:EXECUTED|STAGE3_ELIGIBILITY_ACTIVATED`
* Next Risk Trigger: `Frozen V3.10 Stage4 / Crash / candidate-resolution rules only`
* Current Drawdown: `-0.5033%`
* OOS elapsed: `1.00 calendar days`
* Resolved Candidates: `0 / minimum 3`
* Frozen Hash Status: `PASS`
* Current Evaluation: `INSUFFICIENT_EVIDENCE`
"""

PORTFOLIO_SAMPLE = """record_id,record_type,timestamp,portfolio_value,btc_value,eth_value,unit_nav,drawdown,twr_return,external_flow,normal_cash,pending_dca_cash,tactical_bear_cash,temporary_hedge_cash,crypto_exposure,macro_state,sell_stage,active_target,cycle_id,BTC_close,ETH_close,prev_record_hash,record_hash
Q:OOS:2026-09-04T04:00:00+00:00,OOS_BAR,2026-09-04T04:00:00+00:00,20345.995330955644,6484.778009114309,3425.2468174457535,1.0167,-0.005,-0.0008,2,326.61281452780167,7.1224798054479255,10102.23521006233,0,0.4870749583,NEW_BULL,0,0.95,3,80656.87,2504.39,prev,hash
"""


NOW = datetime(2026, 9, 4, 17, 25, 30, tzinfo=timezone.utc)


class FakeExecutor:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.count = 0

    def __call__(self, command: str, workdir: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        self.count += 1
        return subprocess.CompletedProcess(command, self.returncode, stdout="ok", stderr="bad" if self.returncode else "")


class FixedMarket:
    def fetch(self) -> MarketSnapshot:
        quote_time = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)
        return MarketSnapshot(
            MarketQuote("BTCUSDT", 81000.0, 1.2, quote_time),
            MarketQuote("ETHUSDT", 2500.0, -0.3, quote_time), quote_time,
        )


class FailingMarket:
    def fetch(self) -> MarketSnapshot:
        raise MarketError("MARKET API FAILED")


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.status_path = self.root / "DAILY_FORWARD_STATUS.md"
        self.status_path.write_text(SAMPLE, encoding="utf-8")
        self.v310_portfolio_path = self.root / "forward_v310_portfolio.csv"
        self.v31_portfolio_path = self.root / "forward_v31_shadow_portfolio.csv"
        self.v310_portfolio_path.write_text(PORTFOLIO_SAMPLE, encoding="utf-8")
        self.v31_portfolio_path.write_text(PORTFOLIO_SAMPLE.replace("Q:OOS", "B:OOS"), encoding="utf-8")
        self.storage = MonitorStorage(self.root / "app data")
        self.config = AppConfig(
            model_command="python fake_model.py", model_workdir=self.root,
            status_file=self.status_path, app_data_dir=self.storage.root,
            v310_portfolio_file=self.v310_portfolio_path,
            v31_portfolio_file=self.v31_portfolio_path,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_runner(self, executor: FakeExecutor | None = None) -> tuple[DailyModelRunner, FakeExecutor]:
        fake = executor or FakeExecutor()
        return DailyModelRunner(self.config, self.storage, executor=fake, clock=lambda: NOW), fake

    def test_01_parse_current_status(self) -> None:
        status = parse_status(SAMPLE)
        self.assertEqual(status.v310_state, "NEW_BULL")
        self.assertEqual(status.v310_stage, 0)
        self.assertEqual(status.current_evaluation, "INSUFFICIENT_EVIDENCE")

    def test_02_money_symbols_and_commas(self) -> None:
        status = parse_status(SAMPLE)
        self.assertEqual(status.btc, 80656.87)
        self.assertEqual(status.eth, 2504.39)

    def test_03_exposure_percentages(self) -> None:
        status = parse_status(SAMPLE)
        self.assertAlmostEqual(status.v310_target_exposure, 95.0)
        self.assertAlmostEqual(status.v310_actual_exposure, 48.71)
        self.assertAlmostEqual(status.v310_exposure_gap, 46.29)

    def test_04_first_daily_run_succeeds(self) -> None:
        runner, fake = self.make_runner()
        result = runner.run()
        self.assertTrue(result.completed)
        self.assertEqual(fake.count, 1)
        self.assertEqual(len(self.storage.load_history()), 1)

    def test_05_second_normal_run_same_day_blocked(self) -> None:
        runner, fake = self.make_runner()
        self.assertTrue(runner.run().completed)
        result = runner.run()
        self.assertEqual(result.outcome, "TODAY_ALREADY_COMPLETED")
        self.assertEqual(fake.count, 1)

    def test_06_force_run_executes(self) -> None:
        runner, fake = self.make_runner()
        runner.run()
        result = runner.run(force=True)
        self.assertTrue(result.completed)
        self.assertTrue(result.force_run)
        self.assertEqual(fake.count, 2)

    def test_07_force_run_does_not_duplicate_status_date(self) -> None:
        runner, _ = self.make_runner()
        runner.run(); runner.run(force=True)
        self.assertEqual(len(self.storage.load_history()), 1)

    def test_08_missing_v310_state_validation_fails(self) -> None:
        broken = "\n".join(line for line in SAMPLE.splitlines() if "V3.10 State" not in line)
        with self.assertRaises(StatusValidationError):
            parse_status(broken)

    def test_09_hash_fail_is_saved_with_warning(self) -> None:
        self.status_path.write_text(SAMPLE.replace("Hash Status: `PASS`", "Hash Status: `FAIL`"), encoding="utf-8")
        runner, _ = self.make_runner()
        self.assertTrue(runner.run().completed)
        row = self.storage.load_history()[0]
        self.assertEqual(row["hash_warning"], "True")
        self.assertEqual(row["frozen_hash_status"], "FAIL")

    def test_10_nonzero_return_does_not_complete(self) -> None:
        runner, _ = self.make_runner(FakeExecutor(7))
        result = runner.run()
        self.assertFalse(result.completed)
        self.assertIsNone(self.storage.load_runner_state()["last_successful_local_date"])

    def test_11_archive_created(self) -> None:
        result = self.storage.archive_status(self.status_path, NOW)
        self.assertTrue(result.path.exists())
        self.assertEqual(result.path.read_text(encoding="utf-8"), SAMPLE)

    def test_12_same_day_archive_never_overwrites(self) -> None:
        first = self.storage.archive_status(self.status_path, NOW)
        second = self.storage.archive_status(self.status_path, NOW)
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(first.path.exists() and second.path.exists())

    def test_13_active_candidate_is_recorded(self) -> None:
        status = parse_status(SAMPLE.replace("Candidate: `NO`", "Candidate: `YES`"))
        result = self.storage.record_candidate(status, NOW)
        self.assertEqual(result.status, "APPENDED")
        self.assertEqual(len(self.storage.load_candidates()), 1)
        self.assertEqual(self.storage.load_candidates()[0]["resolution_status"], "UNRESOLVED")

    def test_14_no_candidate_adds_nothing(self) -> None:
        result = self.storage.record_candidate(parse_status(SAMPLE), NOW)
        self.assertEqual(result.status, "NOT_APPLICABLE")
        self.assertEqual(len(self.storage.load_candidates()), 0)

    def test_15_shadow_exposure_difference(self) -> None:
        self.assertAlmostEqual(parse_status(SAMPLE).shadow_actual_exposure_diff or 0, 0.02)

    def test_16_oos_progress(self) -> None:
        self.assertEqual(parse_status(SAMPLE).oos_elapsed, 1.0)

    def test_17_resolved_candidate_progress(self) -> None:
        changed = SAMPLE.replace("0 / minimum 3", "2 / minimum 3")
        self.assertEqual(parse_status(changed).resolved_candidates, 2)

    def test_18_180_days_but_too_few_candidates(self) -> None:
        changed = SAMPLE.replace("1.00 calendar days", "180 calendar days")
        self.assertFalse(parse_status(changed).evaluation_eligible)

    def test_19_three_candidates_but_too_few_days(self) -> None:
        changed = SAMPLE.replace("0 / minimum 3", "3 / minimum 3")
        self.assertFalse(parse_status(changed).evaluation_eligible)

    def test_20_both_gates_make_evaluation_available(self) -> None:
        changed = SAMPLE.replace("1.00 calendar days", "180 calendar days").replace("0 / minimum 3", "3 / minimum 3")
        self.assertTrue(parse_status(changed).evaluation_eligible)

    def test_21_auto_refresh_100_times_never_runs_model(self) -> None:
        runner, fake = self.make_runner()
        controller = MonitorController(self.config, self.storage, runner, FixedMarket(), clock=lambda: NOW)
        for _ in range(100):
            controller.auto_refresh_tick()
        self.assertEqual(fake.count, 0)

    def test_22_refresh_now_never_runs_model(self) -> None:
        runner, fake = self.make_runner()
        MonitorController(self.config, self.storage, runner, FixedMarket(), clock=lambda: NOW).refresh_now()
        self.assertEqual(fake.count, 0)

    def test_23_run_daily_is_only_controller_model_path(self) -> None:
        runner, fake = self.make_runner()
        result = MonitorController(self.config, self.storage, runner, FixedMarket(), clock=lambda: NOW).run_daily_model()
        self.assertTrue(result.completed)
        self.assertEqual(fake.count, 1)

    def test_24_market_failure_does_not_crash_refresh(self) -> None:
        runner, _ = self.make_runner()
        snap = MonitorController(self.config, self.storage, runner, FailingMarket(), clock=lambda: NOW).refresh()
        self.assertIn("MARKET API FAILED", snap.market_error or "")
        self.assertIsNotNone(snap.status)

    def test_25_missing_status_does_not_crash_refresh(self) -> None:
        self.status_path.unlink()
        runner, _ = self.make_runner()
        snap = MonitorController(self.config, self.storage, runner, FixedMarket(), clock=lambda: NOW).refresh()
        self.assertIsNone(snap.status)
        self.assertIn("STATUS FILE NOT FOUND", snap.status_error or "")
        self.assertIsNotNone(snap.market)

    def test_26_excel_locked_csv_reports_error(self) -> None:
        status = parse_status(SAMPLE)
        with mock.patch("storage.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(StorageError) as caught:
                self.storage.write_history(status, run_local_time=NOW, model_return_code=0, force_run=False)
        self.assertIn("EXCEL", str(caught.exception))

    def test_27_chinese_windows_path(self) -> None:
        storage = MonitorStorage(self.root / "中文資料夾" / "虛擬貨幣")
        result = storage.write_history(parse_status(SAMPLE), run_local_time=NOW, model_return_code=0, force_run=False)
        self.assertEqual(result.status, "APPENDED")

    def test_28_space_in_path(self) -> None:
        storage = MonitorStorage(self.root / "folder with spaces")
        self.assertTrue(storage.state_path.exists())

    def test_29_runner_state_atomic_update(self) -> None:
        state = self.storage.load_runner_state(); state["last_return_code"] = 9
        self.storage.save_runner_state(state)
        loaded = json.loads(self.storage.state_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["last_return_code"], 9)
        self.assertEqual(list(self.storage.data_dir.glob("*.tmp")), [])

    def test_30_concurrent_model_run_rejected(self) -> None:
        runner, _ = self.make_runner()
        runner.lock_path.write_text("busy", encoding="ascii")
        with self.assertRaises(ModelRunInProgress):
            runner.run()

    def test_31_traditional_chinese_report_preserves_raw_audit_values(self) -> None:
        report = build_latest_report(parse_status(SAMPLE), FixedMarket().fetch())
        self.assertIn("最新報告｜白話版", report)
        self.assertIn("【今天模型做了什麼】", report)
        self.assertIn("模型檔案完整性", report)
        self.assertIn("牛市重新進入條件已全部成立", report)
        self.assertIn("資料仍不足，暫時不能判定策略好壞", report)
        self.assertIn("NEW_BULL", report)
        self.assertIn("PASS", report)

    def test_32_portfolio_at_recorded_close_reconciles_total(self) -> None:
        portfolio = load_portfolio(self.v310_portfolio_path, None)
        self.assertAlmostEqual(portfolio.total_value, 20345.995330955644, places=6)

    def test_33_portfolio_is_repriced_with_live_market(self) -> None:
        portfolio = load_portfolio(self.v310_portfolio_path, FixedMarket().fetch())
        expected = portfolio.btc_units * 81000 + portfolio.eth_units * 2500 + portfolio.cash_value
        self.assertAlmostEqual(portfolio.total_value, expected, places=6)
        self.assertEqual(portfolio.valuation, "Binance 即時市價")

    def test_34_portfolio_allocation_sums_to_100_percent(self) -> None:
        portfolio = load_portfolio(self.v310_portfolio_path, FixedMarket().fetch())
        self.assertAlmostEqual(portfolio.btc_percent + portfolio.eth_percent + portfolio.cash_percent, 100.0)

    def test_35_controller_loads_both_portfolios_without_running_model(self) -> None:
        runner, fake = self.make_runner()
        snapshot = MonitorController(self.config, self.storage, runner, FixedMarket(), clock=lambda: NOW).refresh_now()
        self.assertIsNotNone(snapshot.v310_portfolio)
        self.assertIsNotNone(snapshot.v31_portfolio)
        self.assertEqual(snapshot.portfolio_errors, ())
        self.assertEqual(fake.count, 0)

    def test_36_bad_portfolio_file_fails_closed(self) -> None:
        self.v310_portfolio_path.write_text("bad,data\n", encoding="utf-8")
        with self.assertRaises(PortfolioError):
            load_portfolio(self.v310_portfolio_path, FixedMarket().fetch())


if __name__ == "__main__":
    unittest.main()
