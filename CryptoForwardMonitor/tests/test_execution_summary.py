"""Synthetic ledger regressions: no network, no production model execution."""
import csv
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_monitor import APP_DIR
from controller import MonitorController
from execution_summary import LEDGERS, appended_rows, latest_ledger_summary, read_ledgers, render_summary
from runner import RunResult
from storage import MonitorStorage


TRADE = dict(record_id="t1", execution_timestamp="2026-09-07T00:00:00+00:00",
             side="BUY", reason="TEN_DAY_NEW_BULL_REDEPLOY", btc_notional_usd="700.493",
             eth_notional_usd="420.2958", fee_usd="1.12", slippage_usd="0.56")
DCA = dict(record_id="d1", timestamp="2026-09-07T04:00:00+00:00", external_flow="2",
           executed_dca="0", pending_dca_cash="4")


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.write("tactical", [])
        self.write("dca", [])

    def write(self, kind, rows):
        name, fields = LEDGERS[kind]
        with (self.root / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=sorted(fields))
            writer.writeheader()
            writer.writerows(rows)

    def render(self, snapshot=None):
        return render_summary(snapshot or read_ledgers(self.root), heading="test", context="test")

    def test_exact_money_reason_and_quantity_limitation(self):
        self.write("tactical", [TRADE])
        text = self.render()
        self.assertIn("$700.49", text)
        self.assertIn("$420.30", text)
        self.assertIn("分十天", text)
        self.assertIn("成交幣數：原始帳本未提供", text)

    def test_dca_contribution_is_not_fill(self):
        self.write("dca", [DCA])
        text = self.render()
        self.assertIn("本筆未成交", text)
        self.assertIn("定投實際執行 $0.00", text)

    def test_dca_fill_and_no_asset_split_inference(self):
        self.write("dca", [{**DCA, "executed_dca": "5.1"}])
        text = self.render()
        self.assertIn("定投買入合計 $5.10", text)
        self.assertIn("不提供每筆幣種成交拆分", text)

    def test_only_appended_records_in_run_summary(self):
        self.write("tactical", [TRADE])
        before = read_ledgers(self.root)
        self.write("tactical", [TRADE, {**TRADE, "record_id": "t2", "side": "SELL"}])
        delta = appended_rows(before, read_ledgers(self.root))
        self.assertEqual(len(delta.rows["tactical"]), 1)
        self.assertIn("戰術買入 $0.00", self.render(delta))
        self.assertIn("戰術賣出 $1,120.79", self.render(delta))

    def test_rewrite_is_not_reported_as_no_trade(self):
        self.write("tactical", [TRADE])
        before = read_ledgers(self.root)
        self.write("tactical", [])
        text = self.render(appended_rows(before, read_ledgers(self.root)))
        self.assertIn("不能判定有無成交", text)
        self.assertNotIn("沒有新增戰術成交", text)

    def test_missing_ledger_is_not_zero_trades(self):
        (self.root / LEDGERS["dca"][0]).unlink()
        self.assertIn("不能判定有無成交", self.render())

    def test_invalid_and_duplicate_records_fail_closed(self):
        for rows in ([TRADE, TRADE], [{**TRADE, "fee_usd": "NaN"}],
                     [{**TRADE, "execution_timestamp": "2026-09-07T00:00:00"}],
                     [{**TRADE, "side": "UNKNOWN"}]):
            with self.subTest(rows=rows):
                self.write("tactical", rows)
                self.assertIn("不能判定有無成交", self.render())

    def test_unknown_reason_not_invented(self):
        self.write("tactical", [{**TRADE, "reason": "NEW_UNKNOWN_RULE"}])
        text = self.render()
        self.assertIn("尚無白話對照", text)
        self.assertIn("NEW_UNKNOWN_RULE", text)

    def test_retrospective_is_labelled_and_latest_day_only(self):
        self.write("tactical", [TRADE, {**TRADE, "record_id": "old", "execution_timestamp": "2026-09-01T00:00:00+00:00"}])
        text = latest_ledger_summary(self.root)
        self.assertIn("不是本次執行", text)
        self.assertIn("戰術買入 $1,120.79", text)

    def controller(self, runner):
        config = SimpleNamespace(status_file=self.root / "status.md")
        storage = MonitorStorage(self.root / "monitor")
        return MonitorController(config, storage, runner, Mock(), clock=lambda: datetime.now(timezone.utc))

    def test_controller_persists_delta_and_repeat_does_not_duplicate(self):
        runner = Mock()
        def run(**kwargs):
            self.write("tactical", [TRADE])
            return RunResult("COMPLETED", True, 0, False, "ok")
        runner.run.side_effect = run
        controller = self.controller(runner)
        result = controller.run_daily_model()
        self.assertTrue(result.completed)
        self.assertIn("$700.49", result.execution_summary)
        self.assertEqual(controller.load_execution_summary(), result.execution_summary)
        runner.run.side_effect = None
        runner.run.return_value = RunResult("TODAY_ALREADY_COMPLETED", False, 0, False, "skip")
        skipped = controller.run_daily_model()
        self.assertIn("沒有重複執行", skipped.execution_summary)
        self.assertEqual(len(list((controller.storage.archive_dir / "execution_summaries").glob("*.txt"))), 1)

    def test_failed_run_not_labelled_successful(self):
        runner = Mock()
        runner.run.return_value = RunResult("FAILED", False, 1, False, "bad")
        result = self.controller(runner).run_daily_model()
        self.assertFalse(result.completed)
        self.assertIn("模型執行未成功", result.execution_summary)

    def test_model_completion_opens_summary_page(self):
        from app import CryptoForwardMonitorApp
        view = SimpleNamespace(_model_reset=Mock(), _write_execution_summary=Mock(),
                               show_page=Mock(), notify=Mock(), refresh_dashboard=Mock())
        result = RunResult("COMPLETED", True, 0, False, "ok", execution_summary="交易摘要")
        CryptoForwardMonitorApp.model_finished(view, result)
        view.show_page.assert_called_once_with("執行摘要")
        view._write_execution_summary.assert_called_once_with("交易摘要")
