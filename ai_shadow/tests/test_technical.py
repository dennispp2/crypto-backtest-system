from datetime import datetime, timezone

import pytest

from ai_shadow.technical import indicators


def candles(count=240):
    return [[i*86400000, 100+i, 102+i, 99+i, 101+i, 1000+i,
             (i+1)*86400000-1] for i in range(count)]


def test_indicators_use_only_completed_bars():
    asof = datetime.fromtimestamp(240*86400, timezone.utc)
    data = candles(241)
    result = indicators(data, asof)
    data[-1][4] = 1_000_000
    assert indicators(data, asof) == result
    assert result['sma20'] == pytest.approx(sum(range(321, 341))/20)
    assert result['rsi14'] == 100
    assert result['atr14'] == 3
    assert result['daily_close'] == 340
    assert result['structure'] == 'HH_HL'


def test_insufficient_or_gapped_daily_history_blocks():
    asof = datetime.fromtimestamp(240*86400, timezone.utc)
    with pytest.raises(ValueError):
        indicators(candles(100), asof)
    data = candles()
    data.pop(200)
    with pytest.raises(ValueError):
        indicators(data, asof)
