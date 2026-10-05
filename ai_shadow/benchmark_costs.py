"""Post-decision read-only cost diagnostics; NEVER part of GPT input.

Frozen forward output groups tactical fills and omits per-asset DCA fills.
Exact DCA fee/slippage dollars can be derived from its executed budget and
frozen buy formula, but a TOTAL per-asset trade count cannot be invented.
"""
import csv
import hashlib
import json
import math
from pathlib import Path

from ai_shadow.snapshot import canonical_json, utc


def read_chain(path):
    raw = Path(path).read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    previous, ids = 'GENESIS', set()
    for row in rows:
        body = {k:v for k,v in row.items() if k not in {'prev_record_hash','record_hash'}}
        digest = hashlib.sha256((previous+'|'+canonical_json(body)).encode()).hexdigest()
        if row['prev_record_hash']!=previous or row['record_hash']!=digest or row['record_id'] in ids:
            raise ValueError('BENCHMARK_COST_CHAIN_INVALID')
        ids.add(row['record_id'])
        previous = digest
    return rows, hashlib.sha256(raw).hexdigest()


def frozen_costs(project_root, genesis, asof):
    root = Path(project_root)
    folder = root/'v3_10_forward'
    trades, trade_hash = read_chain(folder/'forward_trade_log_v310.csv')
    dca, dca_hash = read_chain(folder/'forward_fixed_dca_log.csv')
    rules = json.loads((root/'config/config_frozen_v3_1.json').read_text(encoding='utf-8'))
    # The forward config retains the exact engine cost assumptions.
    fee, slip = float(rules['costs']['fee']), float(rules['costs']['slippage'])
    start, end = utc(genesis['genesis_timestamp']), utc(asof)
    trades = [r for r in trades if start < utc(r['execution_timestamp']) <= end]
    dca = [r for r in dca if start < utc(r['timestamp']) <= end]
    tactical_fee = sum(float(r['fee_usd']) for r in trades)
    tactical_slip = sum(float(r['slippage_usd']) for r in trades)
    notional = sum(float(r['total_gross_notional_usd']) for r in trades)
    budget = sum(float(r['executed_dca']) for r in dca)
    amounts = [tactical_fee, tactical_slip, notional, budget]
    if not all(math.isfinite(v) and v>=0 for v in amounts):
        raise ValueError('BENCHMARK_COST_INVALID')
    # Frozen _buy: units=budget/(open*(1+slip)*(1+fee)).
    dca_fee = budget*fee/(1+fee)
    dca_slip = budget*slip/((1+slip)*(1+fee))
    return {'status':'PARTIAL', 'tactical_turnover':notional/genesis['state']['initial_nav'],
            'tactical_asset_trade_count':sum(float(r[a+'_notional_usd'])>0 for r in trades for a in ('btc','eth')),
            'total_asset_trade_count':None, 'dca_active_bar_count':sum(float(r['executed_dca'])>0 for r in dca),
            'total_fees':tactical_fee+dca_fee, 'total_slippage':tactical_slip+dca_slip,
            'tactical_fees':tactical_fee, 'derived_dca_fees':dca_fee,
            'trade_log_sha256':trade_hash, 'dca_log_sha256':dca_hash,
            'method':'Frozen grouped tactical log + DCA executed budget/frozen buy formula. '
                     'DCA asset fill count unavailable; timestamps strictly after Genesis and <=asof.'}
