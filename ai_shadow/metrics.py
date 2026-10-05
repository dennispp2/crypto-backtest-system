"""Cash-flow-neutral performance, with sample limitations made explicit."""
import math
import statistics as stats

from ai_shadow.portfolio import weights
from ai_shadow.snapshot import utc


def performance(genesis, records, state, benchmark):
    states = [genesis['state']] + [r['payload']['state'] for r in records if r['payload'].get('state') and r['kind'] != 'GENESIS'] + [state]
    eod = {}
    for s in states:
        eod[utc(s['timestamp']).date()] = s
    days = sorted(eod)
    # Never call variable-duration or missing-day observations daily returns.
    returns = [eod[b]['unit_nav']/eod[a]['unit_nav']-1 for a,b in zip(days, days[1:]) if (b-a).days == 1]
    elapsed = (utc(state['timestamp'])-utc(genesis['genesis_timestamp'])).total_seconds()/86400
    volatility = stats.stdev(returns)*math.sqrt(365) if len(returns) >= 2 else None
    mean = stats.mean(returns) if returns else None
    sharpe = mean*365/volatility if volatility else None
    downside = math.sqrt(stats.mean([min(r,0)**2 for r in returns]))*math.sqrt(365) if len(returns) >= 2 else None
    sortino = mean*365/downside if downside else None
    # Annualization over a tiny forward window would be misleading.
    cagr = state['unit_nav']**(365.25/elapsed)-1 if elapsed >= 30 else None
    calmar = cagr/abs(state['max_drawdown']) if cagr is not None and state['max_drawdown'] < 0 else None
    allocation = weights(state, {'BTC':state['btc_price'], 'ETH':state['eth_price']})
    benchmarks = [{'timestamp':genesis['genesis_timestamp'], 'unit_nav':1., 'exposure':
                   (genesis['state']['btc_value']+genesis['state']['eth_value'])/genesis['state']['nav']}]
    benchmarks += [r['payload']['benchmark'] for r in records if r['payload'].get('benchmark')]
    benchmarks.append(benchmark)
    benchmark_eod = {utc(b['timestamp']).date():b for b in benchmarks}
    benchmark_days = sorted(benchmark_eod)
    benchmark_returns = [benchmark_eod[b]['unit_nav']/benchmark_eod[a]['unit_nav']-1
        for a,b in zip(benchmark_days, benchmark_days[1:]) if (b-a).days == 1]
    benchmark_volatility = stats.stdev(benchmark_returns)*math.sqrt(365) if len(benchmark_returns)>=2 else None
    peak, benchmark_dd = 1., 0.
    for b in benchmarks:
        peak = max(peak, b['unit_nav'])
        benchmark_dd = min(benchmark_dd, b['unit_nav']/peak-1)
    costs = benchmark.get('costs', {'status':'MISSING'})
    result = {'timestamp':state['timestamp'], 'nav':state['nav'], 'total_return_since_genesis':state['unit_nav']-1,
              'v310_return_since_same_genesis':benchmark['return_since_genesis'],
              'alpha_since_genesis':state['unit_nav']-benchmark['unit_nav'], 'max_drawdown':state['max_drawdown'],
              'volatility':volatility, 'sharpe':sharpe, 'sortino':sortino, 'twr_cagr':cagr, 'calmar':calmar,
              'tactical_turnover':state['turnover_notional']/state['initial_nav'], 'trade_count':state['trade_count'],
              'fees':state['fees'], 'slippage':state['slippage'], 'external_contributions':state['external_contributions'],
              'exposure':allocation['BTC']+allocation['ETH'], 'btc_weight':allocation['BTC'], 'eth_weight':allocation['ETH'],
              'cash_weight':allocation['Cash'], 'consecutive_daily_return_samples':len(returns),
              'sample_warning':'CAGR withheld below 30 days; risk ratios require 2 consecutive daily returns',
              'average_exposure_observed':stats.mean((s['btc_value']+s['eth_value'])/s['nav'] for s in states),
              'v310_max_drawdown':benchmark_dd, 'v310_volatility':benchmark_volatility,
              'v310_exposure':benchmark['exposure'],
              'v310_average_exposure_observed':stats.mean(b['exposure'] for b in benchmarks),
              'v310_turnover':costs.get('tactical_turnover'), 'v310_fees':costs.get('total_fees'),
              'v310_trade_count':costs.get('total_asset_trade_count'), 'v310_cost_status':costs['status'],
              'v310_tactical_asset_trade_count':costs.get('tactical_asset_trade_count'),
              'benchmark_warning':'NOT_SAME_TICK: frozen contribution is known at completed-bar close; '
              'benchmark is frozen unit NAV endpoint-rebased. V3.10 DD/volatility use observed AI-cycle marks, '
              'not full lifetime or intrabar extrema. Total asset trade count unavailable from grouped DCA log.'}
    return result
