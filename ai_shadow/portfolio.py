"""Independent spot ledger and unitized cash flows; never writes quant data."""
from __future__ import annotations

import copy
import math
from datetime import timedelta

from ai_shadow.snapshot import utc

CASH_FIELDS = ('normal_cash', 'pending_dca_cash', 'tactical_bear_cash', 'temporary_hedge_cash')


def available_at(row):
    # Frozen rows are labelled by bar OPEN but contain the closing valuation.
    return utc(row['timestamp'])+timedelta(hours=4)


def prices_from_row(row):
    return {a: float(row[a+'_close']) for a in ('BTC', 'ETH')}


def holdings_from_row(row):
    return {'btc_units': float(row['btc_value'])/float(row['BTC_close']),
            'eth_units': float(row['eth_value'])/float(row['ETH_close']),
            'cash': sum(float(row[f]) for f in CASH_FIELDS)}


def mark(state, prices):
    state = copy.deepcopy(state)
    values = {a: state[a.lower()+'_units']*prices[a] for a in ('BTC', 'ETH')}
    if any(not math.isfinite(v) or v < 0 for v in (*values.values(), state['cash'], *prices.values())) or min(prices.values()) <= 0:
        raise ValueError('AI_ACCOUNTING_INVALID')
    state.update({'btc_value': values['BTC'], 'eth_value': values['ETH'], 'nav': sum(values.values())+state['cash'],
                  'btc_price': prices['BTC'], 'eth_price': prices['ETH']})
    if state['nav'] <= 0 or state['fund_units'] <= 0:
        raise ValueError('AI_NAV_INVALID')
    state['unit_nav'] = state['nav']/state['fund_units']
    state['peak_unit_nav'] = max(state.get('peak_unit_nav', 1), state['unit_nav'])
    state['drawdown'] = state['unit_nav']/state['peak_unit_nav']-1
    state['max_drawdown'] = min(state.get('max_drawdown', 0), state['drawdown'])
    return state


def weights(state, prices):
    state = mark(state, prices)
    return {'BTC': state['btc_value']/state['nav'], 'ETH': state['eth_value']/state['nav'], 'Cash': state['cash']/state['nav']}


def genesis_payload(row, source_hash, timestamp, model, policy_hash, experiment_id, *, prices=None, risk=None):
    timestamp = utc(timestamp)
    if available_at(row) > timestamp:
        raise ValueError('GENESIS_FUTURE_SOURCE')
    prices = prices or prices_from_row(row)
    initial = holdings_from_row(row)
    initial_nav = initial['cash'] + initial['btc_units']*prices['BTC'] + initial['eth_units']*prices['ETH']
    state = {**initial, 'fund_units': initial_nav, 'initial_nav': initial_nav, 'external_contributions': 0.,
             'source_cursor': row['record_id'], 'source_cursor_hash': row['record_hash'], 'timestamp': timestamp.isoformat(),
             'btc_cost_basis': initial['btc_units']*prices['BTC'], 'eth_cost_basis': initial['eth_units']*prices['ETH'],
             'cost_basis_label': 'Genesis mark basis (not inherited historical average)', 'fees': 0., 'slippage': 0.,
             'turnover_notional': 0., 'trade_count': 0, 'realized_pnl': 0.}
    state = mark(state, prices)
    return {'label': 'AI_SHADOW_V1_PAPER_ONLY', 'experiment_id': experiment_id, 'genesis_timestamp': timestamp.isoformat(),
            'source_v310_timestamp': row['timestamp'], 'source_v310_available_at': available_at(row).isoformat(),
            'source_v310_file_hash': source_hash, 'source_v310_record_id': row['record_id'],
            'source_v310_record_hash': row['record_hash'], 'source_v310_nav': float(row['portfolio_value']),
            'source_v310_unit_nav': float(row['unit_nav']), 'source_v310_mark_adjustment': initial_nav/float(row['portfolio_value']),
            **initial, 'btc_price': prices['BTC'], 'eth_price': prices['ETH'],
            'policy_version': 'decision_policy_v1', 'policy_hash': policy_hash, 'model_slug': model,
            'fee_bps': 10, 'slippage_bps': 5, 'min_notional_usd': 5, 'risk_rules': risk or {},
            'cash_flow_method': 'Mirror each appended frozen $2/4H row; recognize only after bar completion; cash only',
            'state': state}


def sync_contributions(state, rows, asof):
    """Cash receipts have both scheduled time and knowledge/recognition time.

    Units are issued at pre-receipt NAV. A frozen contribution is never counted
    twice and cannot be credited before its completed source bar is available.
    After an error all receipts catch up atomically on the next successful cycle.
    """
    state = copy.deepcopy(state)
    cursor = next((i for i, r in enumerate(rows) if r['record_id'] == state['source_cursor']), None)
    if cursor is None or rows[cursor]['record_hash'] != state['source_cursor_hash']:
        raise ValueError('SOURCE_PREFIX_CHANGED')
    receipts = []
    for row in rows[cursor+1:]:
        if available_at(row) > utc(asof):
            break
        amount = float(row['external_flow'])
        if not math.isfinite(amount) or amount != 2.0:
            raise ValueError('UNEXPECTED_FROZEN_CONTRIBUTION')
        state = mark(state, prices_from_row(row))
        state['fund_units'] += amount/state['unit_nav']
        state['cash'] += amount
        state['external_contributions'] += amount
        state = mark(state, prices_from_row(row))
        state.update(source_cursor=row['record_id'], source_cursor_hash=row['record_hash'])
        receipts.append({'timestamp': row['timestamp'], 'available_at': available_at(row).isoformat(),
                         'recognized_at': utc(asof).isoformat(), 'amount': amount,
                         'source': row['record_id'], 'source_record_hash': row['record_hash']})
    return state, receipts


def benchmark(genesis, rows, prices, timestamp):
    row = rows[-1]
    nav = holdings_from_row(row)
    live_nav = nav['cash'] + nav['btc_units']*prices['BTC'] + nav['eth_units']*prices['ETH']
    adjusted_unit = (float(row['unit_nav'])/genesis['source_v310_unit_nav'] *
                     (live_nav/float(row['portfolio_value']))/genesis['source_v310_mark_adjustment'])
    return {'timestamp': timestamp, 'source_record_id': row['record_id'], 'nav': live_nav,
            'unit_nav': adjusted_unit, 'return_since_genesis': adjusted_unit-1,
            'exposure': 1-nav['cash']/live_nav,
            'method': 'Frozen cash-flow-neutral unit NAV rebased to Genesis, live-mark adjusted at both endpoints'}
