from pathlib import Path


def test_optional_historical_gaps_do_not_block_user_approved_limited_mode():
    from ai_shadow.historical_limited import HistoricalLimitedInputs
    from ai_shadow.snapshot import validate_asof
    root = Path(__file__).resolve().parents[2]
    records = [
        {'field': 'macro.'+name, 'value': value, 'pit_status': 'VINTAGE_VERIFIED',
         'observation_time': '2019-12-01T00:00:00Z' if name in ('cpi', 'pce', 'nonfarm_payrolls') else '2019-12-29T00:00:00Z',
         'available_at': '2019-12-31T00:00:00Z'}
        for name, value in [('us_2y_yield', 1.5), ('us_10y_yield', 1.9),
                            ('fed_target_lower', 1.5), ('fed_target_upper', 1.75),
                            ('cpi', 250), ('pce', 110), ('nonfarm_payrolls', 150000)]
    ]
    quant = {'state': 'BULL', 'stage': 0, 'target_exposure': .95,
             'status_available_at': '2020-01-01T00:00:00Z'}
    portfolio = {'nav': 20000, 'btc_weight': .4375, 'eth_weight': .2625, 'cash_weight': .3}
    snapshot = HistoricalLimitedInputs(root, records).snapshot('2020-01-01T00:00:00Z', quant, portfolio)
    assert snapshot['input_coverage']['status'] == 'PASS'
    assert snapshot['input_coverage']['missing_required'] == []
    assert 'macro.dxy' in snapshot['input_coverage']['optional_missing']
    assert 'events' in snapshot['input_coverage']['optional_missing']
    assert snapshot['external']['macro']['dxy']['value'] is None
    assert snapshot['external']['macro']['dxy']['required'] is False
    assert snapshot['technical']['BTC']['indicator_asof'] == '2019-12-31T23:59:59+00:00'
    validate_asof(snapshot, snapshot['decision_cutoff'])


def test_hold_can_preserve_natural_price_drift_above_95_without_forced_trading():
    from ai_shadow.historical_limited import validate_limited_decision
    decision = {'action': 'HOLD', 'confidence': None, 'market_health': None,
        'bull_probability': None, 'base_probability': None, 'bear_probability': None,
        'target_total_exposure': .97, 'target_btc_weight': .6,
        'target_eth_weight': .37, 'target_cash_weight': .03,
        'thesis': [], 'key_positive_factors': [], 'key_risks': [],
        'invalidation_conditions': [], 'data_quality': 'PARTIAL', 'missing_inputs': []}
    assert validate_limited_decision(decision)['action'] == 'HOLD'
