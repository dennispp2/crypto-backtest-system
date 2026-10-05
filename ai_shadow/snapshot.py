"""Point-in-time data contracts. No imports from trading engines or outcomes."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path


def utc(value=None):
    value = value or datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def completed_candles(rows, asof):
    cutoff = utc(asof).timestamp() * 1000
    completed = [row for row in rows if int(row[6]) < cutoff]
    if any(int(left[0]) >= int(right[0]) for left, right in zip(completed, completed[1:])):
        raise ValueError("CANDLE_ORDER_INVALID")
    for row in completed:
        if any(not math.isfinite(float(row[i])) or float(row[i]) < 0 for i in range(1, 6)):
            raise ValueError("CANDLE_VALUE_INVALID")
        if float(row[1]) <= 0 or float(row[4]) <= 0:
            raise ValueError("CANDLE_PRICE_INVALID")
    return completed


def validate_asof(value, decision_time):
    """Reject future evidence, credentials and forbidden forward outcome fields."""
    forbidden = {"access_token", "refresh_token", "id_token", "authorization", "api_key",
                 "future_return", "candidate_outcome", "candidate_resolution", "resolved_result",
                 'future_min_return_60d','bear_label','label_end_date','resolution_date',
                 'maturity_date','q_return','v31_return','return_edge_q_minus_v31','forward_candidate_outcomes'}
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in forbidden:
                raise ValueError("FORBIDDEN_SNAPSHOT_FIELD")
            if key in {"source_timestamp", "fetched_at", "indicator_asof", "spot_asof", "status_date", 'status_available_at', 'query_time', 'publication_timestamp', 'available_at', 'observation_time'} and child:
                if utc(child) > utc(decision_time):
                    raise ValueError("FUTURE_EVIDENCE")
            validate_asof(child, decision_time)
    elif isinstance(value, list):
        for child in value:
            validate_asof(child, decision_time)


def build_snapshot(*, quant, technical, external, portfolio, created_at, freshness=None):
    from ai_shadow.configuration import FreshnessPolicy
    freshness = freshness or FreshnessPolicy()
    timestamp = utc(created_at).isoformat()
    def statuses(value):
        if isinstance(value, dict):
            return ([value['status']] if 'status' in value else []) + [s for v in value.values() for s in statuses(v)]
        if isinstance(value, list):
            return [s for v in value for s in statuses(v)]
        return []
    critical = True
    for asset in ('BTC', 'ETH'):
        item = technical.get(asset, {})
        critical &= item.get('status') == 'PASS'
        for key, limit in (('indicator_asof', freshness.daily_max_age_seconds), ('spot_asof', freshness.spot_max_age_seconds)):
            critical &= bool(item.get(key)) and 0 <= (utc(created_at)-utc(item[key])).total_seconds() <= limit
    critical &= bool(quant.get('status_available_at')) and 0 <= (utc(created_at)-utc(quant['status_available_at'])).total_seconds() <= freshness.quant_max_age_seconds
    content = {"created_at": timestamp, "quant": quant, "technical": technical,
               "portfolio": portfolio, "external": external,
               **{k: external.get(k, {}) for k in ('macro', 'risk_assets', 'derivatives', 'etf_flow', 'liquidity', 'onchain', 'events')},
               "data_freshness": {"critical": "PASS" if critical else 'STALE', "supplementary": "PASS" if
                   all(s == "PASS" for s in statuses(external)) else "PARTIAL"}}
    validate_asof(content, created_at)
    digest = canonical_hash(content)
    return {**content, "snapshot_id": digest[:24], "snapshot_hash": digest}


def read_frozen_portfolio(path: Path):
    """Verify the whole append-only chain and reconcile every input row."""
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    previous, seen, last_time = "GENESIS", set(), None
    for row in rows:
        body = {k: v for k, v in row.items() if k not in {"prev_record_hash", "record_hash"}}
        digest = hashlib.sha256((previous + "|" + canonical_json(body)).encode()).hexdigest()
        if row["prev_record_hash"] != previous or row["record_hash"] != digest or row["record_id"] in seen:
            raise ValueError("FROZEN_LEDGER_CHAIN_INVALID")
        seen.add(row["record_id"])
        previous = digest
        stamp = utc(row['timestamp'])
        if last_time is not None and (stamp-last_time).total_seconds() != 4*3600:
            raise ValueError('FROZEN_LEDGER_TIME_GAP')
        last_time = stamp
        prices = {a: float(row[a + "_close"]) for a in ("BTC", "ETH")}
        values = [float(row[k]) for k in ("btc_value", "eth_value", "normal_cash",
                  "pending_dca_cash", "tactical_bear_cash", "temporary_hedge_cash")]
        if any(not math.isfinite(x) or x < 0 for x in values) or any(not math.isfinite(x) or x <= 0 for x in prices.values()):
            raise ValueError("FROZEN_LEDGER_ACCOUNTING_INVALID")
        if not math.isfinite(float(row['portfolio_value'])) or abs(sum(values) - float(row["portfolio_value"])) > 0.01:
            raise ValueError("FROZEN_LEDGER_NAV_MISMATCH")
    if not rows:
        raise ValueError("FROZEN_LEDGER_EMPTY")
    return rows, hashlib.sha256(raw).hexdigest()
