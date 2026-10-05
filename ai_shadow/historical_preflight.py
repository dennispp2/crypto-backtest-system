"""Historical input audit; never writes the frozen or live portfolio.

This is NOT a portfolio backtest. It prevents missing point-in-time evidence
from being hidden by thousands of GPT calls or a reused quant equity curve.
"""
from copy import deepcopy
import json
import math
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

from ai_shadow.snapshot import canonical_hash, utc, validate_asof
from ai_shadow.technical import indicators, relative_strength

POLICY_PATH = Path(__file__).parent/'policy/historical_v310_preflight_v1.md'
SCHEMA_PATH = Path(__file__).parent/'schemas/historical_decision_v1.schema.json'


def validate_historical_decision(decision, *, schema=None):
    schema = schema if schema is not None else json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    Draft202012Validator(schema).validate(decision)
    numbers = [v for v in decision.values() if isinstance(v, (float, int)) and not isinstance(v, bool)]
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError('NONFINITE_DECISION')
    probabilities = [decision[k] for k in ('bull_probability', 'base_probability', 'bear_probability')]
    if any(v is None for v in probabilities) and not all(v is None for v in probabilities):
        raise ValueError('PARTIAL_PROBABILITIES')
    if all(v is not None for v in probabilities) and abs(sum(probabilities)-1) > 1e-6:
        raise ValueError('PROBABILITIES_SUM')
    if abs(sum(decision[k] for k in ('target_btc_weight', 'target_eth_weight', 'target_cash_weight'))-1) > 1e-6:
        raise ValueError('WEIGHTS_SUM')
    if abs(decision['target_btc_weight']+decision['target_eth_weight']-decision['target_total_exposure']) > 1e-6:
        raise ValueError('EXPOSURE_SUM')
    return decision


def apply_data_gate(decision, snapshot):
    effective = deepcopy(decision)
    insufficient = snapshot['input_coverage']['status'] != 'PASS'
    if insufficient:
        allocation = snapshot['portfolio']
        effective.update(
            action='HOLD',
            target_total_exposure=allocation['btc_weight']+allocation['eth_weight'],
            target_btc_weight=allocation['btc_weight'],
            target_eth_weight=allocation['eth_weight'],
            target_cash_weight=allocation['cash_weight'],
        )
    return {'requested_decision': deepcopy(decision), 'effective_decision': effective,
            'gate': 'INSUFFICIENT_DATA_HOLD' if insufficient else 'PASS',
            'missing_required': list(snapshot['input_coverage']['missing_required'])}


def historical_snapshot(root, cutoff):
    """Build the FIRST decision's input, not a fabricated evolving portfolio.

    Quant signal outputs are selected by their recorded availability, with an
    explicit allowlist. Candles must have closed strictly before the cutoff.
    No current news, current FRED revisions, or resolved labels are imported.
    """
    cutoff = utc(cutoff)
    if cutoff != utc('2020-01-01T00:00:00Z'):
        raise ValueError('FIRST_DECISION_PREFLIGHT_ONLY_NOT_A_FULL_BACKTEST')
    signals = pd.read_csv(root/'v3_10/results/regime_log_v3_10.csv')
    available = pd.to_datetime(signals['signal_available_at'], utc=True)
    selected = signals.loc[(signals['model'] == 'Q') & (available <= cutoff)]
    if selected.empty:
        raise ValueError('HISTORICAL_QUANT_SIGNAL_UNAVAILABLE')
    selected = selected.assign(_available=available.loc[selected.index]).sort_values('_available')
    row = selected.iloc[-1]
    if utc(row['signal_date']) >= cutoff:
        raise ValueError('FUTURE_QUANT_SIGNAL')
    flag = lambda value: str(value).lower() == 'true'
    quant = {
        'signal_date': utc(row['signal_date']).isoformat(),
        'status_available_at': utc(row['signal_available_at']).isoformat(),
        'state': str(row['state_after']), 'stage': int(row['stage_after']),
        'target_exposure': float(row['active_target_after']),
        'actual_exposure': float(row['crypto_exposure_before']),
        'drawdown': 0.0,
        'drawdown_basis': 'Fresh formal start; no earlier formal equity peak',
        'stage3_candidate': flag(row['stage3_candidate_active']),
        'stage3_raw_signal': flag(row['stage3_confirmed']),
        'crash_level1_raw': flag(row['crash_level1_raw']),
        'crash_level2_raw': flag(row['crash_level2_market_raw']),
        'tactical_action': str(row['actions']) if pd.notna(row['actions']) else 'NONE',
    }
    technical = {}
    for asset in ('BTC', 'ETH'):
        path = root/'v3_1/data/raw'/('binance_'+asset+'USDT_1d.csv.gz')
        daily = pd.read_csv(path)
        opens = pd.to_datetime(daily['open_time'], utc=True)
        closes = pd.to_datetime(daily['close_time'], utc=True)
        prefix = daily.loc[(opens >= utc('2019-01-01T00:00:00Z')) & (closes < cutoff)]
        candles = [[int(utc(r.open_time).timestamp()*1000), r.open, r.high,
                    r.low, r.close, r.volume, int(utc(r.close_time).timestamp()*1000)]
                   for r in prefix.itertuples()]
        technical[asset] = {
            **indicators(candles, cutoff), 'status': 'PASS',
            'source': 'https://api.binance.com/api/v3/klines',
            'data_basis': 'Archived completed daily OHLCV; not historical order-book quotes',
        }
    technical['relative_strength'] = relative_strength(technical['BTC'], technical['ETH'])

    def unavailable(required=True):
        return {'value': None, 'status': 'MISSING', 'required': required,
                'source_timestamp': None, 'publication_timestamp': None,
                'reason': 'NO_VERIFIED_POINT_IN_TIME_ARCHIVE_IN_PROJECT'}

    external = {
        'macro': {k: unavailable() for k in ('dxy', 'us_2y_yield', 'us_10y_yield',
                  'vix', 'fed_rate', 'cpi', 'pce', 'nonfarm_payrolls')},
        'derivatives': {a: {k: unavailable() for k in ('funding', 'open_interest',
                       'open_interest_change', 'basis', 'long_short_ratio', 'liquidations')}
                        for a in ('BTC', 'ETH')},
        'etf_flow': {a: unavailable() for a in ('BTC', 'ETH')},
        'liquidity': {'stablecoins': unavailable()},
        'onchain': {'exchange_inflow': unavailable(), 'exchange_outflow': unavailable(),
                    'whale_holder': unavailable(False)},
        'events': unavailable(),
    }
    missing = []

    def walk(value, path=''):
        if 'status' in value:
            if value['required']:
                missing.append(path)
            return
        for key, child in value.items():
            walk(child, path+'.'+key if path else key)

    walk(external)
    snapshot = {
        'mode': 'HISTORICAL_FIRST_DECISION_PREFLIGHT_NOT_PERFORMANCE_BACKTEST',
        'decision_cutoff': cutoff.isoformat(), 'warmup_start': '2019-01-01',
        'quant': quant, 'technical': technical, 'external': external,
        'portfolio': {'nav': 20000.0, 'btc_weight': .4375, 'eth_weight': .2625,
                      'cash_weight': .3, 'exposure': .7,
                      'basis': 'Fresh initial allocation plan before combined-engine execution; not executed holdings'},
        'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': missing,
                          'optional_missing': ['onchain.whale_holder'],
                          'etf_period_applicability': 'Not inferred: no instrument inception/calendar contract verified'},
        'historical_limits': [
            'Current GPT may know later events despite the restricted input.',
            'Full backtest and next-bar execution are not implemented by this preflight.',
            'Unavailable fields are null, never zero or current-data substitutes.',
        ],
    }
    validate_asof(snapshot, cutoff)
    return {**snapshot, 'snapshot_hash': canonical_hash(snapshot)}
