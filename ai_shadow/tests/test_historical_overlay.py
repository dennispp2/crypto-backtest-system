"""The isolated extension must exactly reproduce V3.10 when AI does nothing."""
from pathlib import Path

import pandas as pd


def test_noop_overlay_is_row_identical_to_the_frozen_engine():
    from ai_shadow.historical_overlay import load_frozen_inputs, run_overlay_engine
    root = Path(__file__).resolve().parents[2]
    frame, rules = load_frozen_inputs(root)
    import crypto_backtest.v310_engine as frozen
    from crypto_backtest.v31_engine import run_v31_backtest
    from run_backtest_v3_10 import make_scenario
    frame = frame.head(36).copy()
    a = run_v31_backtest(frame, rules, make_scenario('A', rules))
    b = run_v31_backtest(frame, rules, make_scenario('B', rules), model_a=a)
    expected = frozen.run_v310_backtest(frame, rules, make_scenario('Q', rules), model_a=a, shadow_v31=b)
    observed = []
    actual = run_overlay_engine(root, frame, rules, make_scenario('Q', rules), a, b,
                                lambda context: observed.append(context))
    pd.testing.assert_frame_equal(actual.history, expected.history)
    pd.testing.assert_frame_equal(actual.trades, expected.trades)
    pd.testing.assert_frame_equal(actual.signals, expected.signals)
    assert len(observed) == 36
    assert 'BTC_close' not in observed[0]['row']
    assert 'ETH_close' not in observed[0]['row']
    assert 'future_min_return_60d' not in observed[0]['row']
    assert observed[0]['timestamp'] == pd.Timestamp('2020-01-01T00:00:00Z')


def execution_context():
    from ai_shadow.historical_overlay import load_frozen_inputs
    root = Path(__file__).resolve().parents[2]
    _, rules = load_frozen_inputs(root)
    from crypto_backtest.v31_engine import V31State
    from run_backtest_v3_10 import make_scenario
    state = V31State(normal_cash=6000, qty={'BTC': 87.5, 'ETH': 52.5})
    return {'state': state, 'prices': {'BTC': 100., 'ETH': 100.}, 'trades': [],
            'timestamp': pd.Timestamp('2020-01-01T04:00:00Z'), 'scenario': make_scenario('Q', rules),
            'row': {'signal_date': pd.Timestamp('2019-12-31T00:00:00Z'),
                    'crash_level1_raw': False, 'crash_level2_market_raw': False},
            'actions': []}, rules


def exit_decision():
    return {'action': 'EXIT', 'confidence': .8, 'market_health': None,
            'bull_probability': None, 'base_probability': None, 'bear_probability': None,
            'target_total_exposure': 0., 'target_btc_weight': 0., 'target_eth_weight': 0.,
            'target_cash_weight': 1., 'thesis': [], 'key_positive_factors': [], 'key_risks': [],
            'invalidation_conditions': [], 'data_quality': 'PARTIAL', 'missing_inputs': []}


def test_ai_exit_is_clamped_and_protected_cash_and_dca_are_untouched():
    from ai_shadow.historical_overlay import execute_ai_overlay
    context, rules = execution_context()
    context['state'].normal_cash = 5000
    context['state'].tactical_bear_cash = 1000
    result = execute_ai_overlay(context, exit_decision(), '2020-01-01T00:00:00Z', 'test-1', rules)
    state = context['state']
    nav = state.normal_cash+state.tactical_bear_cash+sum(state.qty[a]*100 for a in ('BTC', 'ETH'))
    assert abs(sum(state.qty[a]*100 for a in ('BTC', 'ETH'))/nav-.5) < 1e-6
    assert state.tactical_bear_cash == 1000
    assert state.pending == {'BTC': 0., 'ETH': 0.}
    assert len(context['trades']) == 2
    assert result['gateway_status'] == 'CLAMP'
    assert 'EXPOSURE_CHANGE_CLAMP' in result['gateway_reasons']


def test_ai_hold_leaves_original_engine_state_untouched():
    from ai_shadow.historical_overlay import execute_ai_overlay
    from dataclasses import asdict
    context, rules = execution_context()
    before = asdict(context['state'])
    decision = exit_decision()
    decision.update(action='HOLD', target_total_exposure=.7, target_btc_weight=.4375,
                    target_eth_weight=.2625, target_cash_weight=.3)
    result = execute_ai_overlay(context, decision, '2020-01-01T00:00:00Z', 'test-2', rules)
    assert asdict(context['state']) == before
    assert context['trades'] == []
    assert result['executed_asset_trades'] == 0


def add_decision():
    decision = exit_decision()
    decision.update(action='ADD', target_total_exposure=.95, target_btc_weight=.59375,
                    target_eth_weight=.35625, target_cash_weight=.05)
    return decision


def test_add_cannot_spend_cash_reserved_for_original_v310_hedges():
    from ai_shadow.historical_overlay import execute_ai_overlay
    from dataclasses import asdict
    context, rules = execution_context()
    context['state'].normal_cash = 1000
    context['state'].tactical_bear_cash = 5000
    before = asdict(context['state'])
    result = execute_ai_overlay(context, add_decision(), '2020-01-01T00:00:00Z', 'test-3', rules)
    assert result['gateway_reasons'] == ['PROTECTED_V310_CASH_UNAVAILABLE_TO_AI']
    assert asdict(context['state']) == before
    assert context['trades'] == []


def test_crash_priority_blocks_ai_add_without_changing_primary_rules():
    from ai_shadow.historical_overlay import execute_ai_overlay
    from dataclasses import asdict
    context, rules = execution_context()
    context['state'].crash_level1_days_remaining = 5
    before = asdict(context['state'])
    result = execute_ai_overlay(context, add_decision(), '2020-01-01T00:00:00Z', 'test-4', rules)
    assert result['gateway_reasons'] == ['V310_CRASH_STAGE4_PRIORITY']
    assert asdict(context['state']) == before
