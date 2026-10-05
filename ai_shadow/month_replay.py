"""Read-only continuation of the original forward anchor for a bounded replay."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ai_shadow.historical_limited import HistoricalLimitedInputs
from ai_shadow.historical_overlay import run_overlay_engine
from ai_shadow.snapshot import utc


def load_month(root, days=30):
    from run_forward_v3_10 import build_oos_frame, _combine_series
    from crypto_backtest.v310_forward import canonical_json

    root = Path(root)
    state_file = root/'v3_10_forward/forward_v310_state.json'
    frozen_file = root/'v3_10_forward/forward_config_frozen.json'
    state = json.loads(state_file.read_text(encoding='utf-8'))
    forward = json.loads(frozen_file.read_text(encoding='utf-8'))
    seed = state['cutoff_snapshot']
    if hashlib.sha256(canonical_json(seed).encode('utf-8')).hexdigest() != forward['cutoff_state_sha256']:
        raise ValueError('FORWARD_SEED_HASH_MISMATCH')
    rules = json.loads((root/'config/config_frozen_v3_1.json').read_text(encoding='utf-8'))
    frame, source_contract = build_oos_frame(int(utc().timestamp()*1000), rules)
    if len(frame) < days*6:
        raise ValueError('MONTH_WINDOW_NOT_COMPLETE')
    frame = frame.head(days*6).copy()
    candles = {a:_combine_series(a, a+'USDT', '1d') for a in ('BTC', 'ETH')}
    return frame, rules, seed, candles, source_contract, state['evaluation']


class MonthInputs(HistoricalLimitedInputs):
    def __init__(self, root, records, candles):
        super().__init__(root, records)
        for asset, daily in candles.items():
            daily = daily.loc[pd.to_datetime(daily.open_time, utc=True) >= pd.Timestamp('2019-01-01T00:00:00Z')]
            rows = [[int(utc(r.open_time).timestamp()*1000), r.open, r.high, r.low,
                     r.close, r.volume, int(utc(r.close_time).timestamp()*1000)] for r in daily.itertuples()]
            self.candles[asset], self.closes[asset] = rows, [r[6] for r in rows]


def run_seeded_overlay(root, frame, rules, seed, a, b, callback):
    # Compile the isolated hook INSIDE resume_patch, so the runtime module
    # imports the seeded state and suppressed initial-allocation functions.
    from crypto_backtest.v310_forward import state_from_dict, cycles_from_json, resume_patch, make_forward_scenario
    with resume_patch(state_from_dict(seed['Q']['state']), cycles_from_json(seed['Q']['cycles'])):
        return run_overlay_engine(root, frame, rules, make_forward_scenario('Q', rules), a, b, callback)


def period_metrics(history, trades, initial_value):
    """Recompute period return/DD from cash flows, not engine summary labels."""
    values = history.portfolio_value.astype(float).to_numpy()
    flows = history.external_flow.astype(float).to_numpy()
    previous = np.r_[initial_value, values[:-1]]
    nav = np.cumprod(values/(previous+flows))
    peak = np.maximum.accumulate(np.r_[1., nav])[1:]
    if not np.allclose(nav, history.unit_nav.astype(float), atol=1e-11, rtol=1e-11):
        raise ValueError('INDEPENDENT_TWR_RECONCILIATION_FAILED')
    return {'initial_value':float(initial_value), 'final_value':float(values[-1]),
            'contributions':float(flows.sum()), 'total_invested':float(initial_value+flows.sum()),
            'net_profit':float(values[-1]-initial_value-flows.sum()),
            'twr_return':float(nav[-1]-1), 'max_drawdown':float((nav/peak-1).min()),
            'trade_count':len(trades),
            'fees':float(trades.fee_usd.sum()) if not trades.empty else 0.,
            'slippage':float(trades.slippage_usd.sum()) if not trades.empty else 0.,
            'annualized_metrics':'NOT_REPORTED_SHORT_30_DAY_WINDOW'}
