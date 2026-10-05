from datetime import datetime, timezone

from ai_shadow.snapshot import canonical_hash, completed_candles


def test_snapshot_hash_deterministic():
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_incomplete_daily_candle_excluded():
    asof = datetime(2026, 10, 5, tzinfo=timezone.utc)
    rows = [[0, "1", "2", "1", "2", "10", 1791158399999],
            [1, "2", "3", "1", "3", "12", 1791244799999]]
    assert len(completed_candles(rows, asof)) == 1
