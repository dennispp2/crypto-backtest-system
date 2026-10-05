"""Hybrid-left / pure-right contracts; no production funds or inference."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock

import test_monitor
import test_dashboard_presentation
from test_monitor import FixedMarket, FailingMarket
from portfolio import PortfolioError, load_combined_portfolio
from app import CryptoForwardMonitorApp


def hybrid_view():
    return {
        "genesis": {"strategy_mode": "v310_hybrid"},
        "state": {
            "timestamp": "2026-09-04T08:00:00+00:00", "btc_units": .1,
            "eth_units": 2., "cash": 1000., "btc_price": 80000., "eth_price": 2000.,
            "btc_cost_basis": 8000., "eth_cost_basis": 4000.,
        },
    }


class CombinedPortfolioTests(unittest.TestCase):
    def test_render_qa_does_not_mix_hundred_dollar_fixture_with_binance_prices(self):
        import tempfile
        from pathlib import Path
        from scripts.qa_ai_ui import mock_snapshot
        with tempfile.TemporaryDirectory() as directory:
            snapshot = mock_snapshot(Path(directory))
            self.assertAlmostEqual(snapshot.combined_portfolio.total_value, snapshot.v310_portfolio.total_value)
            self.assertAlmostEqual(snapshot.combined_portfolio.btc_units, snapshot.v310_portfolio.btc_units)
            self.assertAlmostEqual(snapshot.combined_portfolio.eth_units, snapshot.v310_portfolio.eth_units)
            self.assertAlmostEqual(snapshot.combined_portfolio.btc_average_cost, 80656.87)

    def test_fresh_mark_preserves_holdings_and_saved_view(self):
        view = hybrid_view()
        before = deepcopy(view)
        marked = load_combined_portfolio(view, FixedMarket().fetch())
        self.assertAlmostEqual(marked.total_value, 14100.)
        self.assertAlmostEqual(marked.btc_average_cost, 80000.)
        self.assertAlmostEqual(marked.unrealized_return("eth"), 25.)
        self.assertAlmostEqual(marked.btc_percent + marked.eth_percent + marked.cash_percent, 100.)
        self.assertEqual(view, before)
        self.assertIn("非原 V3.10", marked.cost_status)
        self.assertIn("09/04", marked.valuation)

    def test_restart_uses_saved_positions_not_fresh_capital(self):
        first = load_combined_portfolio(hybrid_view(), FixedMarket().fetch())
        second = load_combined_portfolio(deepcopy(hybrid_view()), FixedMarket().fetch())
        self.assertEqual(first, second)
        self.assertEqual(first.cash_value, 1000.)
        self.assertNotEqual(first.total_value, 20000.)

    def test_independent_legacy_is_not_relabelled_as_combined(self):
        view = hybrid_view()
        view["genesis"]["strategy_mode"] = "independent"
        self.assertIsNone(load_combined_portfolio(view, FixedMarket().fetch()))
        self.assertIsNone(load_combined_portfolio(None, FixedMarket().fetch()))

    def test_no_quote_has_explicit_last_valuation(self):
        marked = load_combined_portfolio(hybrid_view(), None)
        self.assertEqual(marked.total_value, 13000.)
        self.assertIn("尚未取得最新行情", marked.valuation)

    def test_invalid_numbers_and_timestamp_fail_closed(self):
        for key, value in (("cash", -1), ("btc_units", float("nan")),
                           ("btc_cost_basis", float("inf")), ("timestamp", "invalid")):
            view = hybrid_view()
            view["state"][key] = value
            with self.assertRaises(PortfolioError):
                load_combined_portfolio(view, FixedMarket().fetch())

    def test_controller_refresh_never_executes_quant_or_ai(self):
        fixture = test_monitor.MonitorTests()
        fixture.setUp()
        try:
            runner, executor = fixture.make_runner()
            from controller import MonitorController
            ai = Mock()
            ai.view.return_value = hybrid_view()
            controller = MonitorController(fixture.config, fixture.storage, runner, FixedMarket(), ai_orchestrator=ai)
            before = fixture.v310_portfolio_path.read_bytes()
            first = controller.refresh()
            controller.market_client = FailingMarket()
            second = controller.refresh()
            self.assertEqual(first.combined_portfolio.total_value, second.combined_portfolio.total_value)
            self.assertIn("非最新價格", second.combined_portfolio.valuation)
            self.assertIn("非最新價格", second.v310_portfolio.valuation)
            self.assertEqual(fixture.v310_portfolio_path.read_bytes(), before)
            self.assertEqual(executor.count, 0)
            ai.run.assert_not_called()
            ai.initialize.assert_not_called()
        finally:
            fixture.tearDown()

    def test_dashboard_uses_live_exposure_and_separate_decision_times(self):
        fixture = test_dashboard_presentation.DashboardPresentationTests()
        fixture.setUp()
        view = hybrid_view()
        view["cycle"] = {"risk_gateway": {"action": "HOLD", "exposure": .8},
                         "state": {"timestamp": "2026-09-04T08:00:00+00:00"}}
        portfolio = load_combined_portfolio(view, FixedMarket().fetch())
        snapshot = replace(fixture.snapshot, ai_view=view, combined_portfolio=portfolio, v310_portfolio=portfolio)
        CryptoForwardMonitorApp.apply_snapshot(fixture.view, snapshot)
        self.assertEqual(fixture.view.vars["h_target"].get(), "80.00%")
        self.assertEqual(fixture.view.vars["q_actual"].get(), "92.91%")
        self.assertIn("最後 AI 決策", fixture.view.vars["h_decision_time"].get())
        self.assertIn("4H 棒起點", fixture.view.vars["q_decision_time"].get())
        fixture.view._update_portfolio.assert_any_call("h", portfolio)
        fixture.view._update_portfolio.assert_any_call("q", portfolio)
