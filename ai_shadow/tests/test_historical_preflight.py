"""The historical data gate is deterministic, regardless of GPT's opinion."""
from ai_shadow.historical_preflight import apply_data_gate


def test_missing_required_history_cannot_increase_exposure():
    snapshot = {
        'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': ['macro.dxy']},
        'portfolio': {'btc_weight': .4, 'eth_weight': .3, 'cash_weight': .3},
    }
    requested = {
        'action': 'ADD', 'target_total_exposure': .9,
        'target_btc_weight': .6, 'target_eth_weight': .3, 'target_cash_weight': .1,
    }
    result = apply_data_gate(requested, snapshot)
    assert result['effective_decision']['action'] == 'HOLD'
    assert result['effective_decision']['target_total_exposure'] == .7
    assert result['effective_decision']['target_cash_weight'] == .3
    assert requested['action'] == 'ADD'
    assert result['gate'] == 'INSUFFICIENT_DATA_HOLD'


def test_snapshot_uses_first_formal_signal_and_only_completed_candles():
    from pathlib import Path
    from ai_shadow.historical_preflight import historical_snapshot
    from ai_shadow.snapshot import utc, validate_asof
    root = Path(__file__).resolve().parents[2]
    snapshot = historical_snapshot(root, utc('2020-01-01T00:00:00Z'))
    assert snapshot['quant']['signal_date'] == '2019-12-31T00:00:00+00:00'
    assert snapshot['quant']['state'] == 'BULL'
    assert snapshot['technical']['BTC']['indicator_asof'] == '2019-12-31T23:59:59+00:00'
    assert snapshot['technical']['ETH']['completed_daily_bars'] == 365
    assert snapshot['input_coverage']['status'] == 'INSUFFICIENT'
    assert 'macro.dxy' in snapshot['input_coverage']['missing_required']
    assert 'derivatives.BTC.liquidations' in snapshot['input_coverage']['missing_required']
    assert 'etf_flow.ETH' in snapshot['input_coverage']['missing_required']
    assert snapshot['portfolio']['cash_weight'] == .3
    validate_asof(snapshot, snapshot['decision_cutoff'])


def test_required_history_is_explicit_missing_not_a_current_proxy():
    from pathlib import Path
    from ai_shadow.historical_preflight import historical_snapshot
    from ai_shadow.snapshot import utc
    snapshot = historical_snapshot(Path(__file__).resolve().parents[2], utc('2020-01-01T00:00:00Z'))
    assert snapshot['external']['macro']['dxy']['value'] is None
    assert snapshot['external']['events']['value'] is None
    assert snapshot['external']['macro']['dxy']['status'] == 'MISSING'
    assert snapshot['external']['onchain']['whale_holder']['required'] is False


def test_unknown_health_and_probabilities_are_null_not_fabricated_scores():
    from ai_shadow.historical_preflight import validate_historical_decision
    decision = {
        'action': 'HOLD', 'confidence': None, 'market_health': None,
        'bull_probability': None, 'base_probability': None, 'bear_probability': None,
        'target_total_exposure': .7, 'target_btc_weight': .4375,
        'target_eth_weight': .2625, 'target_cash_weight': .3,
        'thesis': ['資料不足，維持起始配置'], 'key_positive_factors': [],
        'key_risks': ['缺少歷史宏觀與資金流'], 'invalidation_conditions': [],
        'data_quality': 'POOR', 'missing_inputs': ['macro.dxy'],
    }
    assert validate_historical_decision(decision)['market_health'] is None
    import pytest
    decision['bull_probability'] = .3
    with pytest.raises(ValueError, match='PARTIAL_PROBABILITIES'):
        validate_historical_decision(decision)
