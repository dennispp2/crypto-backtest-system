"""Delivery contracts: inspectable journals, costs and recoverable projections."""
from dataclasses import asdict

import pytest

from ai_shadow.paper_broker import BrokerConfig
from ai_shadow.snapshot import canonical_hash
from ai_shadow.storage import ShadowStorage
from ai_shadow.tests.test_orchestrator import setup
from ai_shadow.tests.test_paper import broker, quotes, state, NOW
from ai_shadow.clients.mock import hold_decision
from ai_shadow.risk_gateway import RiskGateway
from ai_shadow.portfolio import weights


def test_cycle_metadata_and_readable_journal(tmp_path):
    app, _ = setup(tmp_path)
    assert app.run().completed
    store = app.storage()
    cycle = store.cycles()[0]
    assert cycle['research_hash'] == canonical_hash(cycle['research'])
    assert cycle['genesis_hash'] == canonical_hash(store.genesis())
    assert cycle['policy_version'] == 'decision_policy_v1'
    assert cycle['timestamp'] == cycle['state']['timestamp']
    journal = store.root / 'decision_journal' / (cycle['decision_id'] + '.md')
    assert journal.is_file() and cycle['decision_id'] in journal.read_text(encoding='utf-8')


def test_projection_failure_visible_after_reload_and_repair(tmp_path, monkeypatch):
    app, client = setup(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(ShadowStorage, 'export', lambda _: (_ for _ in ()).throw(OSError('locked')))
        assert app.run().completed
    assert app.view()['export_warning'] == 'AUDIT_EXPORT_PENDING'
    app.repair_exports()
    assert app.view()['export_warning'] is None
    assert app.run().outcome == 'TODAY_AI_ALREADY_COMPLETED'
    assert client.calls.count('decide') == 1


def test_disable_keeps_portfolio_but_shows_disabled(tmp_path):
    app, _ = setup(tmp_path)
    assert app.run().completed
    app.configure(enabled=False)
    assert app.view()['outcome'] == 'AI_DISABLED'
    assert app.view()['state']['nav'] > 0


def test_broker_configuration_frozen_at_genesis(tmp_path):
    app, _ = setup(tmp_path)
    app.broker_config = BrokerConfig(fee_bps=8, slippage_bps=3)
    app.initialize('mock-model')
    assert app.storage().genesis()['broker_config'] == asdict(app.broker_config)
    assert app.run().completed
    app.broker_config = BrokerConfig(fee_bps=9)
    assert app.run().outcome == 'TODAY_AI_ALREADY_COMPLETED'
    # A new UTC day bypasses only the completed-day gate, not frozen settings.
    from datetime import timedelta
    clock = app.clock
    app.clock = lambda: clock() + timedelta(days=1)
    assert app.run().outcome == 'EXPERIMENT_VERSION_MISMATCH'


def test_fill_has_complete_cash_accounting(tmp_path):
    decision = hold_decision(.9)
    decision['action'] = 'ADD'
    approved = RiskGateway().evaluate(decision, weights(state(), {'BTC':100, 'ETH':10}))
    end, orders = broker().execute(state(), approved, quotes(), 'id', NOW)
    assert sum(o['net_cash_change'] for o in orders) == pytest.approx(end['cash'] - state()['cash'])
    assert all({'timestamp','units','bid','ask','slippage_bps','gross_notional'} <= o.keys() for o in orders)


def test_comparison_metrics_explain_cost_limitations(tmp_path):
    app, _ = setup(tmp_path)
    assert app.run().completed
    metrics = app.storage().cycles()[0]['metrics']
    assert metrics['v310_max_drawdown'] == 0
    assert metrics['v310_volatility'] is None
    assert metrics['v310_cost_status'] == 'MISSING'
    assert 'NOT_SAME_TICK' in metrics['benchmark_warning']


def test_sqlite_connection_closed_on_context_exit(tmp_path):
    import sqlite3
    store = ShadowStorage(tmp_path)
    with store._connect() as connection:
        connection.execute('SELECT 1')
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
