from __future__ import annotations

import copy
import hashlib
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import pandas as pd

from . import v31_engine as v31
from . import v310_engine as v310
from .v31_engine import ASSETS_V31, V31BacktestResult, V31Scenario, V31State


UTC = "UTC"
HASH_COLUMNS = ("prev_record_hash", "record_hash")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.isoformat()
    if value is pd.NaT or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def capture_return_locals(
    function: Callable[..., Any], *args: Any, capture: tuple[str, ...], **kwargs: Any,
) -> tuple[Any, dict[str, Any]]:
    """Run a frozen engine unchanged and capture selected locals at return.

    ``sys.setprofile`` emits only call/return events, so this bridge does not
    modify trading decisions and is much lighter than line tracing.
    """
    captured: dict[str, Any] = {}
    prior = sys.getprofile()

    def profiler(frame: Any, event: str, arg: Any) -> None:
        if event == "return" and frame.f_code is function.__code__:
            for name in capture:
                if name in frame.f_locals:
                    captured[name] = copy.deepcopy(frame.f_locals[name])

    sys.setprofile(profiler)
    try:
        result = function(*args, **kwargs)
    finally:
        sys.setprofile(prior)
    missing = sorted(set(capture) - set(captured))
    if missing:
        raise RuntimeError(f"Frozen state capture missed locals: {missing}")
    return result, captured


def state_to_dict(state: V31State) -> dict[str, Any]:
    return _jsonable(asdict(state))


_STATE_DATE_FIELDS = {
    "last_signal_date", "accumulation_lock_until", "last_drift_sell_at", "bear_low_date",
}
_LOT_DATE_FIELDS = {"created_signal_date", "unwind_started_date", "closed_date"}
_CYCLE_DATE_FIELDS = {
    "start", "end", "confirmed_date", "new_bull_date",
    "stage1_date", "stage2_date", "stage3_date", "stage4_date",
}


def _timestamp_or_none(value: Any) -> Any:
    if value in (None, "", "NaT"):
        return None
    return pd.Timestamp(value)


def state_from_dict(payload: dict[str, Any]) -> V31State:
    data = copy.deepcopy(payload)
    for key in _STATE_DATE_FIELDS:
        data[key] = _timestamp_or_none(data.get(key))
    if data.get("bear_low_price") == "Infinity":
        data["bear_low_price"] = float("inf")
    for lot in data.get("temporary_lots", []):
        for key in _LOT_DATE_FIELDS:
            if key in lot:
                lot[key] = pd.NaT if lot[key] in (None, "", "NaT") else pd.Timestamp(lot[key])
    return V31State(**data)


def cycles_from_json(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = copy.deepcopy(rows)
    for row in values:
        for key in _CYCLE_DATE_FIELDS:
            if key in row:
                row[key] = pd.NaT if row[key] in (None, "", "NaT") else pd.Timestamp(row[key])
    return values


def scale_state(state: V31State, scale: float) -> V31State:
    out = copy.deepcopy(state)
    out.qty = {asset: float(value) * scale for asset, value in out.qty.items()}
    out.normal_cash *= scale
    out.pending = {asset: float(value) * scale for asset, value in out.pending.items()}
    out.tactical_bear_cash *= scale
    for lot in out.temporary_lots:
        for key in ("cash_remaining", "original_proceeds"):
            if key in lot and pd.notna(lot[key]):
                lot[key] = float(lot[key]) * scale
    return out


def scale_cycles(cycles: pd.DataFrame, scale: float) -> list[dict[str, Any]]:
    rows = cycles.to_dict("records") if not cycles.empty else []
    for row in rows:
        for key in ("temporary_hedge_amount", *[f"stage{i}_tactical_cash" for i in range(1, 5)]):
            if key in row and pd.notna(row[key]):
                row[key] = float(row[key]) * scale
    return _jsonable(rows)


def state_value(state: V31State, prices: dict[str, float]) -> float:
    return float(v31._portfolio_value(state, prices))


def state_exposure(state: V31State, prices: dict[str, float]) -> float:
    return float(v31._exposure(state, prices))


@contextmanager
def resume_patch(state: V31State, cycles: list[dict[str, Any]]) -> Iterator[None]:
    """Inject a frozen cutoff state without changing either frozen engine file."""
    original_v31_state = v31.V31State
    original_v310_state = v310.V31State
    original_v31_buy = v31._buy
    original_v310_buy = v310._buy
    original_v31_cycle = v31._cycle
    original_v310_cycle = v310._cycle
    seed = copy.deepcopy(state)
    seed._forward_cycles = cycles  # type: ignore[attr-defined]

    def state_factory(*args: Any, **kwargs: Any) -> V31State:
        return copy.deepcopy(seed)

    def buy_without_fresh_start(*args: Any, **kwargs: Any) -> float:
        if kwargs.get("action") == "INITIAL_ALLOCATION":
            return 0.0
        return original_v31_buy(*args, **kwargs)

    def cycle_with_cutoff(state_arg: V31State, local: list[dict[str, Any]]) -> dict[str, Any] | None:
        found = original_v31_cycle(state_arg, local)
        if found is not None:
            return found
        return original_v31_cycle(state_arg, getattr(state_arg, "_forward_cycles", []))

    v31.V31State = state_factory  # type: ignore[assignment]
    v310.V31State = state_factory  # type: ignore[assignment]
    v31._buy = buy_without_fresh_start  # type: ignore[assignment]
    v310._buy = buy_without_fresh_start  # type: ignore[assignment]
    v31._cycle = cycle_with_cutoff  # type: ignore[assignment]
    v310._cycle = cycle_with_cutoff  # type: ignore[assignment]
    try:
        yield
    finally:
        v31.V31State = original_v31_state  # type: ignore[assignment]
        v310.V31State = original_v310_state  # type: ignore[assignment]
        v31._buy = original_v31_buy  # type: ignore[assignment]
        v310._buy = original_v310_buy  # type: ignore[assignment]
        v31._cycle = original_v31_cycle  # type: ignore[assignment]
        v310._cycle = original_v310_cycle  # type: ignore[assignment]


def make_forward_scenario(model: str, rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "A": "FORWARD DCA PLANNER - V3.1 FIXED DCA",
        "B": "FORWARD SHADOW - V3.1 MODEL B",
        "Q": "FORWARD CHAMPION - V3.10 MODEL Q",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "Q"}, use_ai=False,
        hard_floor=float(rules["hard_floor"]), initial_capital=20_000.0,
        capital_test="forward_paper_only", fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
    )


def run_resumed_oos(
    frame: pd.DataFrame, rules: dict[str, Any], cutoff_snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Replay the complete OOS prefix from immutable normalized cutoff states."""
    if frame.empty:
        return {}, {}

    results: dict[str, Any] = {}
    runtime: dict[str, dict[str, Any]] = {}

    state_a = state_from_dict(cutoff_snapshot["A"]["state"])
    cycles_a = cycles_from_json(cutoff_snapshot["A"]["cycles"])
    with resume_patch(state_a, cycles_a):
        result_a, local_a = capture_return_locals(
            v31.run_v31_backtest, frame, rules, make_forward_scenario("A", rules),
            capture=("state", "cycles", "counters"),
        )
    results["A"] = result_a
    runtime["A"] = {"state": state_to_dict(local_a["state"]), "counters": _jsonable(local_a["counters"])}

    state_b = state_from_dict(cutoff_snapshot["B"]["state"])
    cycles_b = cycles_from_json(cutoff_snapshot["B"]["cycles"])
    with resume_patch(state_b, cycles_b):
        result_b, local_b = capture_return_locals(
            v31.run_v31_backtest, frame, rules, make_forward_scenario("B", rules),
            model_a=result_a, capture=("state", "cycles", "counters"),
        )
    results["B"] = result_b
    runtime["B"] = {"state": state_to_dict(local_b["state"]), "counters": _jsonable(local_b["counters"])}

    state_q = state_from_dict(cutoff_snapshot["Q"]["state"])
    cycles_q = cycles_from_json(cutoff_snapshot["Q"]["cycles"])
    with resume_patch(state_q, cycles_q):
        result_q, local_q = capture_return_locals(
            v310.run_v310_backtest, frame, rules, make_forward_scenario("Q", rules),
            model_a=result_a, shadow_v31=result_b,
            capture=(
                "state", "cycles", "counters", "stage3_eligible",
                "eligibility_started_at", "sma200_failure_streak", "candidate",
                "next_candidate_id", "last_causal_candidate_id",
            ),
        )
    results["Q"] = result_q
    runtime["Q"] = {
        "state": state_to_dict(local_q["state"]),
        "counters": _jsonable(local_q["counters"]),
        "stage3_eligible": bool(local_q["stage3_eligible"]),
        "eligibility_started_at": _jsonable(local_q["eligibility_started_at"]),
        "sma200_failure_streak": int(local_q["sma200_failure_streak"]),
        "candidate": _jsonable(local_q["candidate"]),
        "next_candidate_id": int(local_q["next_candidate_id"]),
        "last_causal_candidate_id": _jsonable(local_q["last_causal_candidate_id"]),
    }
    return results, runtime


def _stable_text(value: Any) -> str:
    if value is None or value is pd.NaT or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return "true" if bool(value) else "false"
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)):
        return format(float(value), ".17g")
    return str(value)


def add_hash_chain(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().reset_index(drop=True)
    if "record_id" not in out:
        raise ValueError("Append-only ledger requires record_id")
    if out["record_id"].astype(str).duplicated().any():
        raise ValueError("Duplicate record_id in append-only ledger")
    out = out.drop(columns=list(HASH_COLUMNS), errors="ignore")
    for column in out.columns:
        out[column] = out[column].map(_stable_text)
    previous = "GENESIS"
    prev_values: list[str] = []
    hashes: list[str] = []
    for row in out.to_dict("records"):
        digest = hashlib.sha256((previous + "|" + canonical_json(row)).encode("utf-8")).hexdigest()
        prev_values.append(previous)
        hashes.append(digest)
        previous = digest
    out["prev_record_hash"] = prev_values
    out["record_hash"] = hashes
    return out


def append_verified(frame: pd.DataFrame, path: Path) -> tuple[int, str]:
    """Append only the deterministic suffix after verifying the stored prefix."""
    chained = add_hash_chain(frame)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = 0
    if path.exists() and path.stat().st_size:
        existing = pd.read_csv(path, dtype=str, keep_default_na=False)
        existing_rows = len(existing)
        if existing_rows > len(chained):
            raise RuntimeError(f"Append-only ledger shrank: {path.name}")
        expected_ids = chained.iloc[:existing_rows]["record_id"].astype(str).tolist()
        expected_hashes = chained.iloc[:existing_rows]["record_hash"].astype(str).tolist()
        if existing["record_id"].tolist() != expected_ids or existing["record_hash"].tolist() != expected_hashes:
            raise RuntimeError(f"Append-only prefix mismatch: {path.name}")
    suffix = chained.iloc[existing_rows:]
    if not suffix.empty:
        suffix.to_csv(
            path, mode="a" if existing_rows else "w", header=not bool(existing_rows),
            index=False, date_format="%Y-%m-%dT%H:%M:%S%z", na_rep="",
        )
    elif not path.exists():
        chained.to_csv(path, index=False)
    last_hash = chained.iloc[-1]["record_hash"] if not chained.empty else "GENESIS"
    return len(suffix), str(last_hash)


def verify_hash_chain(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return True
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    rebuilt = add_hash_chain(frame.drop(columns=list(HASH_COLUMNS), errors="ignore"))
    return bool(
        frame["prev_record_hash"].astype(str).equals(rebuilt["prev_record_hash"].astype(str))
        and frame["record_hash"].astype(str).equals(rebuilt["record_hash"].astype(str))
    )


def dataframe_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return _jsonable(frame.to_dict("records"))


__all__ = [
    "add_hash_chain", "append_verified", "canonical_json", "capture_return_locals",
    "cycles_from_json", "dataframe_records", "make_forward_scenario", "run_resumed_oos",
    "scale_cycles", "scale_state", "state_exposure", "state_from_dict", "state_to_dict",
    "state_value", "verify_hash_chain",
]
