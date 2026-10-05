"""Presentation regressions without creating windows or touching live ledgers."""
from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_monitor import FixedMarket, NOW, SAMPLE
from app import CryptoForwardMonitorApp
from controller import DashboardSnapshot
from parser import parse_status


class Value:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class DashboardPresentationTests(unittest.TestCase):
    def setUp(self):
        self.view = SimpleNamespace(
            vars=defaultdict(Value), action_var=Value(), footer_var=Value(),
            daily_model_label=Mock(), btc_change_label=Mock(), eth_change_label=Mock(),
            market_status_label=Mock(), eligibility_label=Mock(), oos_bar={}, candidate_bar={},
            oos_text=Mock(), candidate_text=Mock(), recent_list=Mock(),
            _update_portfolio=Mock(), _write_report=Mock(), _write_execution_summary=Mock(),
        )
        self.snapshot = DashboardSnapshot(
            status=parse_status(SAMPLE), market=FixedMarket().fetch(), market_error=None,
            status_error=None, v310_portfolio=None, v31_portfolio=None, portfolio_errors=(),
            latest_report="測試報告", history=[], runner_state={"last_run_time": "2026-09-04T17:25:30+00:00"},
            refreshed_at=NOW, market_last_successful_update=NOW,
        )

    def render(self, **changes):
        CryptoForwardMonitorApp.apply_snapshot(self.view, replace(self.snapshot, **changes))

    def test_chinese_state_and_actions_preserve_raw_audit(self):
        self.render()
        self.assertEqual(self.view.vars["q_state_label"].get(), "新牛市確認期")
        self.assertEqual(self.view.vars["q_state"].get(), "NEW_BULL")
        self.assertIn("分批恢復曝險", self.view.action_var.get())
        self.assertIn("NEW_BULL_REDEPLOY:EXECUTED", self.view.vars["action_raw"].get())

    def test_safety_failure_is_not_hidden_by_insufficient_samples(self):
        status = replace(self.snapshot.status, current_evaluation="D. V3.10 FORWARD SAFETY FAIL")
        self.render(status=status)
        self.assertIn("安全驗證未通過", self.view.vars["evaluation_eligibility"].get())
        self.view.eligibility_label.configure.assert_called_with(style="Danger.TLabel")

    def test_fractional_progress_keeps_days_units(self):
        self.render(status=replace(self.snapshot.status, oos_elapsed=1.8333333333))
        self.view.oos_text.configure.assert_called_with(text="1.83 天 / 180 天")
        self.assertAlmostEqual(self.view.oos_bar["value"], 1.8333333333)

    def test_market_failure_remains_visible(self):
        self.render(market_error="offline")
        self.assertIn("暫時無法取得", self.view.vars["market_status"].get())
        self.view.market_status_label.configure.assert_called_with(style="Warning.TLabel")

    def test_missing_status_has_explicit_warning(self):
        self.render(status=None, status_error="missing")
        self.assertIn("無法讀取", self.view.vars["evaluation_eligibility"].get())

    def test_last_run_shows_date_not_only_time(self):
        self.render()
        self.assertEqual(self.view.vars["last_model_run"].get(), "09-04 17:25")


if __name__ == "__main__":
    unittest.main()
