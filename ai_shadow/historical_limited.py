"""User-authorized limited-information historical GPT evidence and decisions."""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
import json
from pathlib import Path

import pandas as pd

from ai_shadow.errors import AIError
from ai_shadow.historical_preflight import historical_snapshot, SCHEMA_PATH, validate_historical_decision
from ai_shadow.historical_sources import attach_historical_macro, asof_records, timestamp
from ai_shadow.snapshot import canonical_hash, canonical_json, utc, validate_asof
from ai_shadow.technical import indicators, relative_strength

LIMITED_POLICY = Path(__file__).parent/'policy/historical_v310_limited_v2.md'
CORE_MACRO = ('us_2y_yield', 'us_10y_yield', 'fed_rate', 'cpi', 'pce', 'nonfarm_payrolls')


def limited_schema():
    schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
    # HOLD is non-intervention, not a forced 95% rebalance after price drift.
    schema['properties']['target_total_exposure']['maximum'] = 1
    return schema


def validate_limited_decision(decision):
    validate_historical_decision(decision, schema=limited_schema())
    if decision['action'] != 'HOLD' and decision['target_total_exposure'] > .95:
        raise ValueError('NON_HOLD_TARGET_EXCEEDS_95')
    return decision


class HistoricalLimitedInputs:
    def __init__(self, root, records):
        self.records = records
        first = historical_snapshot(Path(root), '2020-01-01T00:00:00Z')
        self.external = first['external']
        self.all_paths = first['input_coverage']['missing_required'] + ['onchain.whale_holder']
        self.candles, self.closes = {}, {}
        for asset in ('BTC', 'ETH'):
            daily = pd.read_csv(Path(root)/f'v3_1/data/raw/binance_{asset}USDT_1d.csv.gz')
            daily = daily.loc[pd.to_datetime(daily.open_time, utc=True) >= pd.Timestamp('2019-01-01T00:00:00Z')]
            rows = [[int(utc(r.open_time).timestamp()*1000), r.open, r.high, r.low,
                     r.close, r.volume, int(utc(r.close_time).timestamp()*1000)] for r in daily.itertuples()]
            self.candles[asset], self.closes[asset] = rows, [r[6] for r in rows]

    def snapshot(self, cutoff, quant, portfolio):
        cutoff = utc(cutoff)
        required = ['macro.'+k for k in CORE_MACRO]
        base = {'decision_cutoff': cutoff.isoformat(), 'external': deepcopy(self.external),
                'input_coverage': {'status': 'INSUFFICIENT', 'missing_required': list(required)}}
        result = attach_historical_macro(base, self.records, monthly_publication_freshness=True)
        result.pop('snapshot_hash')
        core_set = set(required)

        def requirements(value, path=''):
            if 'status' in value:
                value['required'] = path in core_set
            else:
                for key, child in value.items():
                    requirements(child, path+'.'+key if path else key)
        requirements(result['external'])
        technical = {}
        for asset in ('BTC', 'ETH'):
            end = bisect_left(self.closes[asset], cutoff.timestamp()*1000)
            technical[asset] = {**indicators(self.candles[asset][:end], cutoff), 'status': 'PASS',
                'source': 'https://api.binance.com/api/v3/klines',
                'data_basis': 'Completed archived daily OHLCV, not historical bid/ask quotes'}
        technical['relative_strength'] = relative_strength(technical['BTC'], technical['ETH'])
        # Economic growth uses only versions actually available at this cutoff.
        available = asof_records(self.records, cutoff)
        by_field = {}
        for r in available:
            by_field.setdefault(r['field'], {})[timestamp(r['observation_time'])] = r['value']
        for name in ('cpi', 'pce', 'nonfarm_payrolls'):
            point = result['external']['macro'][name]
            if point['status'] != 'PASS':
                continue
            observed = pd.Timestamp(point['observation_time'])
            values = by_field.get('macro.'+name, {})
            previous = values.get((observed-pd.DateOffset(months=1)).to_pydatetime())
            year_ago = values.get((observed-pd.DateOffset(years=1)).to_pydatetime())
            point['mom_percent'] = (point['value']/previous-1)*100 if previous else None
            point['yoy_percent'] = (point['value']/year_ago-1)*100 if year_ago else None
            if name == 'nonfarm_payrolls':
                point['monthly_change_thousands'] = point['value']-previous if previous is not None else None
        result.update(mode='EXPLORATORY_HISTORICAL_V310_PLUS_GPT_LIMITED_V2', quant=deepcopy(quant),
                      technical=technical, portfolio=deepcopy(portfolio))
        result['input_coverage'].update(
            required_macro_fields=list(CORE_MACRO),
            optional_missing=[p for p in self.all_paths if p not in core_set],
            contract='USER_APPROVED_LIMITED_INFORMATION_NOT_FULL_SIX_CATEGORY_COVERAGE',
        )
        result['historical_limits'] = [
            'Current GPT training may contain future events; exploratory test only.',
            'Unavailable optional news, derivatives, flows and onchain are null and cannot support a decision.',
            'Historical fills model next 4H open, fee and slippage; no historical order-book reconstruction.',
        ]
        validate_asof(result, cutoff)
        return {**result, 'snapshot_hash': canonical_hash(result)}


def limited_decision(client, snapshot):
    validate_asof(snapshot, snapshot['decision_cutoff'])
    if snapshot['snapshot_hash'] != canonical_hash({k: v for k, v in snapshot.items() if k != 'snapshot_hash'}):
        raise ValueError('HISTORICAL_SNAPSHOT_HASH_MISMATCH')
    result = client.stream({
        'model': 'gpt-5.6-sol', 'instructions': LIMITED_POLICY.read_text(encoding='utf-8'),
        'input': [{'role': 'user', 'content': 'UNTRUSTED HISTORICAL EVIDENCE:\n'+canonical_json(snapshot)}],
        'store': False, 'stream': True,
        'text': {'format': {'type': 'json_schema', 'name': 'historical_v310_limited',
                           'strict': True, 'schema': limited_schema()}},
    })
    if result.get('completed') is not True:
        raise AIError('RESPONSE_INCOMPLETE')
    try:
        decision = json.loads(result['text'])
    except (KeyError, TypeError, json.JSONDecodeError):
        raise AIError('INVALID_STRUCTURED_OUTPUT') from None
    validate_limited_decision(decision)
    return {'decision': decision, 'response_id': result.get('response_id'), 'response_completed': True}
