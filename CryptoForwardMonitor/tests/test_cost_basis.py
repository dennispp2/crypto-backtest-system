"""Cost-display regressions. No production model or network calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_monitor import APP_DIR, FixedMarket, PORTFOLIO_SAMPLE
from cost_basis import account_trades
from cost_view import read_costs, update_cost_view
from portfolio import load_portfolio


def trade(side, quantity, cash, asset="BTC"):
    return dict(side=side, quantity=quantity, cash_change_usd=cash, asset=asset)


class AverageAccountingTests(unittest.TestCase):
    def test_buys_use_cash_spent_including_costs(self):
        book = account_trades([trade("BUY", 2, -202), trade("BUY", 1, -121)])
        self.assertAlmostEqual(book["BTC"].average, 323 / 3)

    def test_sell_does_not_reduce_average_by_sale_proceeds(self):
        book = account_trades([trade("BUY", 2, -202), trade("SELL", 1, 200)])
        self.assertEqual(book["BTC"].cost, 101)
        self.assertEqual(book["BTC"].average, 101)

    def test_exit_and_reentry_reset_average(self):
        book = account_trades([trade("BUY", 2, -202), trade("SELL", 2, 400)])
        self.assertIsNone(book["BTC"].average)
        account_trades([trade("BUY", 1, -301)], book)
        self.assertEqual(book["BTC"].average, 301)

    def test_scaling_holdings_and_cost_preserves_average(self):
        book = account_trades([trade("BUY", 2, -202)])
        book["BTC"].units *= .05
        book["BTC"].cost *= .05
        self.assertAlmostEqual(book["BTC"].average, 101)

    def test_invalid_fills_are_rejected(self):
        for row in (trade("BUY", 1, 10), trade("BUY", float("nan"), -1),
                    trade("SELL", 1, 10), trade("HOLD", 1, -10)):
            with self.subTest(row=row), self.assertRaises(ValueError):
                account_trades([row])


class CostCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "cost.json"
        self.payload = {
            "schema_version": 1, "method": "inherited_moving_average_including_buy_costs",
            "models": {"Q": {"portfolio_sha256": "hash", "timestamp": "time", "assets": {
                "BTC": {"units": 2, "cost_usd": 202, "average_cost": 101},
                "ETH": {"units": 1, "cost_usd": 55, "average_cost": 55},
            }}},
        }

    def read(self, payload=None, **kwargs):
        self.path.write_text(json.dumps(payload or self.payload), encoding="utf-8")
        return read_costs(self.path, model="Q", portfolio_hash=kwargs.get("hash", "hash"),
                          timestamp="time", units=kwargs.get("units", (2, 1)))

    def test_valid_cost(self):
        btc, eth, status = self.read()
        self.assertEqual((btc, eth), (101, 55))
        self.assertIn("歷史承接", status)

    def test_stale_ledger_and_unit_mismatch_do_not_show_old_average(self):
        for args in ({"hash": "new"}, {"units": (3, 1)}):
            self.assertEqual(self.read(**args)[:2], (None, None))

    def test_nonfinite_wrong_schema_and_inconsistent_average(self):
        bad = deepcopy(self.payload)
        bad["models"]["Q"]["assets"]["BTC"]["average_cost"] = float("nan")
        self.assertEqual(self.read(bad)[:2], (None, None))
        bad["models"]["Q"]["assets"]["BTC"]["average_cost"] = 200
        self.assertEqual(self.read(bad)[:2], (None, None))
        bad = {**self.payload, "schema_version": 99}
        self.assertEqual(self.read(bad)[:2], (None, None))

    def test_missing_cache_is_not_zero_cost(self):
        result = read_costs(self.path, model="Q", portfolio_hash="hash", timestamp="time", units=(2, 1))
        self.assertEqual(result[:2], (None, None))
        self.assertIn("尚無資料", result[2])

    def test_live_market_changes_value_not_average(self):
        path = self.root / "portfolio.csv"
        path.write_text(PORTFOLIO_SAMPLE, encoding="utf-8")
        base = load_portfolio(path, None)
        item = self.payload["models"]["Q"]
        item["portfolio_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        item["timestamp"] = base.timestamp.isoformat()
        for asset, units in (("BTC", base.btc_units), ("ETH", base.eth_units)):
            item["assets"][asset]["units"] = units
            item["assets"][asset]["cost_usd"] = units * item["assets"][asset]["average_cost"]
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        recorded = load_portfolio(path, None, cost_path=self.path, model="Q")
        live = load_portfolio(path, FixedMarket().fetch(), cost_path=self.path, model="Q")
        self.assertEqual(recorded.btc_average_cost, live.btc_average_cost)
        self.assertEqual(live.btc_average_cost, 101)
        self.assertNotEqual(recorded.btc_value, live.btc_value)

    def test_post_run_helper_failure_is_nonfatal(self):
        config = SimpleNamespace(model_workdir=self.root, app_data_dir=self.root)
        with patch("cost_view.Path.is_file", return_value=True), \
                patch("cost_view.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="mismatch", stdout="")) as run:
            self.assertIn("均價核對失敗", update_cost_view(config))
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_unrealized_return_profit_loss_and_missing(self):
        from dataclasses import replace
        path = self.root / "p.csv"
        path.write_text(PORTFOLIO_SAMPLE, encoding="utf-8")
        base = load_portfolio(path, None)
        gain = replace(base, btc_units=2, btc_value=220, btc_average_cost=100)
        loss = replace(gain, btc_value=180)
        self.assertAlmostEqual(gain.unrealized_return("btc"), 10)
        self.assertAlmostEqual(loss.unrealized_return("btc"), -10)
        self.assertIsNone(base.unrealized_return("btc"))
        self.assertIsNone(replace(gain, btc_units=0).unrealized_return("btc"))

    def test_unrealized_colors_are_signed_and_missing_is_neutral(self):
        from app import CryptoForwardMonitorApp
        from ui import UI_COLORS
        label = Mock()
        view = SimpleNamespace(pnl_labels={"q_btc": label})
        for number, color in ((12.3, "green"), (-2, "red"), (None, "muted"), (0, "muted")):
            CryptoForwardMonitorApp._set_pnl_color(view, "q", "btc", number)
            label.configure.assert_called_with(text_color=UI_COLORS[color])

    def test_average_visible_for_each_model_and_missing_is_explicit(self):
        from app import CryptoForwardMonitorApp
        variables = {f"{p}_{name}": Mock() for p in ("q", "b") for name in (
            "btc_average", "eth_average", "btc_pnl", "eth_pnl", "cost_status", "portfolio_total", "portfolio_btc",
            "portfolio_eth", "portfolio_cash", "portfolio_time")}
        view = SimpleNamespace(vars=variables, allocation_percentages={}, _draw_allocation_bar=Mock(), _set_pnl_color=Mock())
        path = self.root / "p.csv"
        path.write_text(PORTFOLIO_SAMPLE, encoding="utf-8")
        from dataclasses import replace
        data = replace(load_portfolio(path, None), btc_average_cost=71000, eth_average_cost=2100)
        for prefix in ("q", "b"):
            CryptoForwardMonitorApp._update_portfolio(view, prefix, data)
            variables[f"{prefix}_btc_average"].set.assert_called_with("成本均價：$71,000.00")
            variables[f"{prefix}_eth_average"].set.assert_called_with("成本均價：$2,100.00")
        CryptoForwardMonitorApp._update_portfolio(view, "q", None)
        variables["q_btc_average"].set.assert_called_with("均價：無資料")
