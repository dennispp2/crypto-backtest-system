"""Daily technical calculations, entirely from completed contiguous candles.

EMA seeds from an SMA; Wilder RSI/ATR seed from 14 observations. Bollinger
uses population standard deviation. Structure compares the last two disjoint
20-day high/low windows (not retrospectively labelled pivots).
"""
from __future__ import annotations

import math
import statistics as stats
from datetime import datetime, timezone

from ai_shadow.snapshot import completed_candles, utc


def ema(values, period):
    result = [None] * (period-1)
    current = stats.mean(values[:period])
    result.append(current)
    for value in values[period:]:
        current += 2/(period+1) * (value-current)
        result.append(current)
    return result


def wilder(values, period=14):
    current = stats.mean(values[:period])
    for value in values[period:]:
        current = (current*(period-1) + value)/period
    return current


def indicators(rows, asof):
    rows = completed_candles(rows, asof)
    if len(rows) < 205:
        raise ValueError('TECHNICAL_HISTORY_INSUFFICIENT')
    if any(int(b[0])-int(a[0]) != 86400000 for a, b in zip(rows, rows[1:])):
        raise ValueError('DAILY_CANDLE_GAP')
    closes = [float(r[4]) for r in rows]
    highs, lows = [float(r[2]) for r in rows], [float(r[3]) for r in rows]
    volumes = [float(r[5]) for r in rows]
    changes = [b-a for a, b in zip(closes, closes[1:])]
    gain, loss = wilder([max(0, d) for d in changes]), wilder([max(0, -d) for d in changes])
    rsi = 100 if loss == 0 and gain > 0 else 50 if loss == gain == 0 else 100-100/(1+gain/loss)
    tr = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(rows))]
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a-b for a, b in zip(fast[25:], slow[25:])]
    signal = ema(macd, 9)[-1]
    close, middle, spread = closes[-1], stats.mean(closes[-20:]), stats.pstdev(closes[-20:])
    volume_mean, volume_std = stats.mean(volumes[-20:]), stats.pstdev(volumes[-20:])
    log_returns = [math.log(b/a) for a, b in zip(closes, closes[1:])]
    high_up = max(highs[-20:]) > max(highs[-40:-20])
    low_up = min(lows[-20:]) > min(lows[-40:-20])
    structure = 'HH_HL' if high_up and low_up else 'LH_LL' if not high_up and not low_up else 'MIXED'
    result = {'daily_close': close, 'indicator_asof': datetime.fromtimestamp(int(rows[-1][6])/1000, timezone.utc).isoformat(),
              'completed_daily_bars': len(rows), 'ema20': ema(closes, 20)[-1],
              'bb20_middle': middle, 'bb20_upper': middle+2*spread, 'bb20_lower': middle-2*spread,
              'atr14': wilder(tr), 'rsi14': rsi, 'macd': macd[-1], 'macd_signal': signal,
              'macd_histogram': macd[-1]-signal, 'volume': volumes[-1], 'volume_ma20': volume_mean,
              'volume_ratio': volumes[-1]/volume_mean if volume_mean else None,
              'volume_zscore': (volumes[-1]-volume_mean)/volume_std if volume_std else None,
              'structure': structure, 'high20': max(highs[-20:]), 'low20': min(lows[-20:]),
              'high50': max(highs[-50:]), 'low50': min(lows[-50:]),
              'realized_volatility30': stats.pstdev(log_returns[-30:])*math.sqrt(365)}
    for n in (10, 20, 50, 200):
        average = stats.mean(closes[-n:])
        result.update({f'sma{n}': average, f'price_vs_sma{n}': close/average-1,
                       f'sma{n}_slope5': average/stats.mean(closes[-n-5:-5])-1})
    for n in (1, 7, 30, 90):
        result[f'return{n}d'] = close/closes[-n-1]-1
    if utc(result['indicator_asof']) > utc(asof):
        raise ValueError('FUTURE_TECHNICAL')
    return result


def relative_strength(btc, eth):
    if btc['indicator_asof'] != eth['indicator_asof']:
        raise ValueError('RELATIVE_STRENGTH_ASOF_MISMATCH')
    return {f'eth_vs_btc_{n}d': (1+eth[f'return{n}d'])/(1+btc[f'return{n}d'])-1 for n in (1, 7, 30, 90)}
