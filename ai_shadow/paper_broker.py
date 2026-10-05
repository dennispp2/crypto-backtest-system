"""Deterministic target-weight spot fills from a NEW post-decision bid/ask.

No external trading SDK, order endpoint, leverage, or credentials. Plans are
applied to a copy; validation failure discards ALL fills before journal commit.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from ai_shadow.portfolio import mark
from ai_shadow.snapshot import canonical_hash, utc
from ai_shadow.risk_gateway import RiskConfig


@dataclass(frozen=True)
class BrokerConfig:
    fee_bps: float = 10
    slippage_bps: float = 5
    min_notional_usd: float = 5
    quote_max_age_seconds: float = 30
    max_spread_fraction: float = .01

    def __post_init__(self):
        if not all(math.isfinite(v) and v >= 0 for v in (self.fee_bps, self.slippage_bps, self.min_notional_usd)):
            raise ValueError('BROKER_CONFIG_INVALID')
        if self.fee_bps > 100 or self.slippage_bps > 100 or not math.isfinite(self.quote_max_age_seconds) or self.quote_max_age_seconds <= 0:
            raise ValueError('BROKER_CONFIG_INVALID')
        if not math.isfinite(self.max_spread_fraction) or not 0 < self.max_spread_fraction <= .01:
            raise ValueError('BROKER_CONFIG_INVALID')


class PaperBroker:
    def __init__(self, config=None, clock=utc, risk_config=None):
        self.config, self.clock = config or BrokerConfig(), clock
        self.risk_config = risk_config or RiskConfig()

    def execute(self, state, approved, quotes, decision_id, decision_completed):
        now = self.clock()
        for asset in ('BTC', 'ETH'):
            quote = quotes[asset]
            bid, ask = quote['bid'], quote['ask']
            if not all(math.isfinite(p) and p > 0 for p in (bid, ask)) or bid > ask or ask/bid-1 > self.config.max_spread_fraction:
                raise ValueError('QUOTE_INVALID')
            if utc(quote['requested_at']) < utc(decision_completed):
                raise ValueError('QUOTE_BEFORE_DECISION')
            if utc(quote['quote_time']) > now or utc(quote['quote_time']) < utc(quote['requested_at']) or (now-utc(quote['quote_time'])).total_seconds() > self.config.quote_max_age_seconds:
                raise ValueError('QUOTE_STALE')
        prices = {a: (q['bid']+q['ask'])/2 for a, q in quotes.items()}
        state = mark(copy.deepcopy(state), prices)
        state['timestamp'] = now.isoformat()
        if approved.status == 'BLOCK' or approved.action == 'HOLD':
            return state, []
        original_nav = state['nav']
        original_exposure = (state['btc_value']+state['eth_value'])/original_nav
        fee_rate, slip_rate = self.config.fee_bps/10000, self.config.slippage_bps/10000
        # Solve the post-cost NAV. Merely reserving an arbitrary budget would
        # over-reduce a clamped EXIT beyond its permitted 20 percentage points.
        target_nav = original_nav
        for _ in range(60):
            cost = 0.
            for a in prices:
                delta = target_nav*approved.weights[a]-state[a.lower()+'_value']
                q = quotes[a]
                friction = (q['ask']*(1+slip_rate)*(1+fee_rate)/prices[a]-1 if delta >= 0 else
                            1-q['bid']*(1-slip_rate)*(1-fee_rate)/prices[a])
                cost += abs(delta)*friction
            new_target = original_nav-cost
            if abs(new_target-target_nav) < 1e-9:
                target_nav = new_target
                break
            target_nav = new_target
        orders = []
        for side in ('SELL', 'BUY'):
            for asset in ('BTC', 'ETH'):
                key, cost_key = asset.lower()+'_units', asset.lower()+'_cost_basis'
                current_value = state[key]*prices[asset]
                delta = target_nav*approved.weights[asset]-current_value
                if (side == 'SELL' and delta >= -1e-7) or (side == 'BUY' and delta <= 1e-7):
                    continue
                quote = quotes[asset]
                reference = quote['ask'] if side == 'BUY' else quote['bid']
                fill = reference*(1+slip_rate if side == 'BUY' else 1-slip_rate)
                quantity = abs(delta)/prices[asset]
                if side == 'BUY':
                    quantity = min(quantity, state['cash']/(fill*(1+fee_rate)))
                else:
                    quantity = min(quantity, state[key])
                notional = quantity*fill
                base = {'order_id': canonical_hash({'decision': decision_id, 'asset': asset, 'side': side}),
                        'decision_id': decision_id, 'asset': asset, 'side': side, 'quote_time': quote['quote_time'],
                        'fill_time': now.isoformat(), 'reference_price': reference, 'fill_price': fill,
                        'quantity': quantity, 'notional': notional, 'reason': approved.action,
                        'timestamp':now.isoformat(), 'units':quantity, 'bid':quote['bid'], 'ask':quote['ask'],
                        'slippage_bps':self.config.slippage_bps, 'gross_notional':notional, 'net_cash_change':0.,
                        'fee': 0., 'slippage': 0., 'source': quote['source']}
                if notional < self.config.min_notional_usd:
                    orders.append({**base, 'status': 'SKIPPED', 'reason': 'MIN_NOTIONAL'})
                    continue
                fee = notional*fee_rate
                slippage = quantity*abs(fill-reference)
                spread_cost = quantity*abs(reference-prices[asset])
                if side == 'SELL':
                    removed_cost = state[cost_key]*quantity/state[key]
                    state[key] -= quantity
                    state[cost_key] -= removed_cost
                    state['cash'] += notional-fee
                    state['realized_pnl'] += notional-fee-removed_cost
                else:
                    state[key] += quantity
                    state[cost_key] += notional+fee
                    state['cash'] -= notional+fee
                state['fees'] += fee
                state['slippage'] += slippage
                state['spread_cost'] = state.get('spread_cost',0)+spread_cost
                state['turnover_notional'] += notional
                state['trade_count'] += 1
                orders.append({**base, 'status': 'FILLED', 'fee': fee, 'slippage': slippage, 'spread_cost':spread_cost,
                               'net_cash_change':notional-fee if side=='SELL' else -notional-fee})
        state = mark(state, prices)
        exposure = (state['btc_value']+state['eth_value'])/state['nav']
        # Price movement can cause drift above 95% on HOLD, but a new plan may not.
        if exposure > self.risk_config.max_total_crypto_exposure+1e-6 and approved.action in {'ADD', 'STRONG_ADD'}:
            raise ValueError('POST_FILL_EXPOSURE_LIMIT')
        if abs(exposure-original_exposure) > self.risk_config.max_single_cycle_exposure_change+1e-6:
            raise ValueError('POST_FILL_EXPOSURE_CHANGE_LIMIT')
        if state['cash'] < -1e-8 or min(state['btc_units'], state['eth_units']) < 0:
            raise ValueError('POST_FILL_ACCOUNTING_INVALID')
        return state, orders
