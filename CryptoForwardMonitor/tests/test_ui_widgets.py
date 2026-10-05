"""Withdrawn-window widget checks using temporary files and mocked networking.

These tests never execute the forward engine or load production portfolios.
"""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest import mock

from test_monitor import APP_DIR, FixedMarket, NOW, SAMPLE
from app import CryptoForwardMonitorApp
from controller import DashboardSnapshot
from parser import parse_status


class WidgetTests(unittest.TestCase):
    def test_pages_feedback_and_resizing_without_live_model(self):
        real_init = tk.Tk.__init__

        def hidden_init(root, *args, **kwargs):
            real_init(root, *args, **kwargs)
            tk.Tk.withdraw(root)

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            config = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
            config.update(model_command="NEVER_EXECUTE", model_workdir=str(temporary),
                          status_file=str(temporary / "status.md"), app_data_dir=str(temporary),
                          v310_portfolio_file=str(temporary / "q.csv"),
                          v31_portfolio_file=str(temporary / "b.csv"), auto_refresh=False)
            config_path = temporary / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with mock.patch.object(tk.Tk, "__init__", hidden_init), \
                    mock.patch.object(CryptoForwardMonitorApp, "refresh_dashboard") as refresh, \
                    mock.patch("app.MonitorController") as controller:
                window = CryptoForwardMonitorApp(config_path)
                try:
                    self.assertEqual(window.state(), "withdrawn")
                    snapshot = DashboardSnapshot(
                        status=parse_status(SAMPLE), market=FixedMarket().fetch(),
                        market_error=None, status_error=None, v310_portfolio=None,
                        v31_portfolio=None, portfolio_errors=(), latest_report="最新報告\n\n【測試】\n測試內容",
                        history=[], runner_state={}, refreshed_at=NOW, market_last_successful_update=NOW,
                    )
                    window.apply_snapshot(snapshot)
                    window.update_idletasks()
                    self.assertEqual(window.report_text.get("1.0", "end-1c"), snapshot.latest_report)
                    for title in ("資產總覽", "白話報告", "執行摘要", "原始資料"):
                        window.show_page(title)
                        self.assertEqual(window.page_title.cget("text"), title)
                    for width in (900, 1200, 1500):
                        # Exercise logical-width breakpoints, not Windows display settings.
                        from customtkinter import ScalingTracker
                        scale = ScalingTracker.get_widget_scaling(window.main_grid)
                        window._responsive_layout(mock.Mock(width=width * scale))
                        self.assertEqual(window._wide, width >= 1160)
                    window.notify("操作完成")
                    self.assertIsNotNone(window._notice_after_id)
                    window.notify("測試錯誤", error=True)
                    self.assertIsNone(window._notice_after_id)
                    self.assertEqual(window.notice_text.cget("text"), "測試錯誤")
                    window.dismiss_notice()
                    self.assertIsNone(window._notice_message)
                    window.show_help()
                    window.open_history()
                    first = window.history_window
                    self.assertEqual(str(first.transient()), str(window))
                    window.open_history()
                    self.assertIs(window.history_window, first)
                    first.destroy()
                    self.assertIsNone(first._present_after_id)
                    window.open_history()
                    self.assertIsNot(window.history_window, first)
                    window._write_execution_summary("本次買入 BTC $10，原因：固定定投")
                    self.assertIn("BTC $10", window.execution_text.get("1.0", "end"))
                    window.update_idletasks()
                    controller.return_value.run_daily_model.assert_not_called()
                    controller.return_value.refresh_now.assert_not_called()
                finally:
                    window.close()
