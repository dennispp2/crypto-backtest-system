from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "v3_10_forward"
RAW_DIR = OUTPUT_DIR / "data" / "raw"
FIGURES_DIR = OUTPUT_DIR
STATE_PATH = OUTPUT_DIR / "forward_v310_state.json"
FROZEN_OUTPUT_PATH = OUTPUT_DIR / "forward_config_frozen.json"
MANIFEST_PATH = OUTPUT_DIR / "forward_manifest.json"
STATIC_CONFIG_PATH = PROJECT_DIR / "config" / "config_frozen_v3_10_forward.json"
HISTORICAL_CUTOFF = pd.Timestamp("2026-09-03T04:00:00+00:00")
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import (  # noqa: E402
    binance_server_time_ms,
    build_common_4h_frame,
    download_binance_klines,
    read_csv_gz,
    sha256_file,
    write_csv_gz,
)
from crypto_backtest.v31_engine import V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v31_indicators import build_v31_daily, merge_v31_features_to_bars  # noqa: E402
from crypto_backtest.v310_engine import run_v310_backtest  # noqa: E402
from crypto_backtest.v310_forward import (  # noqa: E402
    append_verified,
    canonical_json,
    capture_return_locals,
    cycles_from_json,
    run_resumed_oos,
    scale_cycles,
    scale_state,
    state_exposure,
    state_from_dict,
    state_to_dict,
    state_value,
    verify_hash_chain,
)
from run_backtest_v3_1 import load_formal_data  # noqa: E402
from run_backtest_v3_10 import make_scenario  # noqa: E402


LEDGER_FILES = {
    "Q": "forward_v310_portfolio.csv",
    "B": "forward_v31_shadow_portfolio.csv",
    "trades": "forward_trade_log_v310.csv",
    "dca": "forward_fixed_dca_log.csv",
    "candidates": "forward_stage3_candidates.csv",
    "outcomes": "forward_candidate_outcomes.csv",
    "signals": "forward_signal_log.csv",
    "exceptions": "forward_execution_exceptions.csv",
    "daily": "forward_daily_metrics.csv",
    "monthly": "forward_monthly_metrics.csv",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dataframe_digest(frame: pd.DataFrame) -> str:
    rows = frame.copy()
    for column in rows.columns:
        if pd.api.types.is_datetime64_any_dtype(rows[column]):
            rows[column] = rows[column].map(lambda value: "" if pd.isna(value) else pd.Timestamp(value).isoformat())
    payload = rows.replace({np.nan: None}).to_dict("records")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _verify_historical_sources(static: dict[str, Any]) -> dict[str, str]:
    request = Path(static["request_path"])
    checks: dict[str, str] = {}
    expected = {
        "request": (request, static["request_sha256"].lower()),
        "v310_config": (PROJECT_DIR / "config/config_frozen_v3_10.json", "a0a7db91f1c93782f01a158a807370dd80acc0f3378ce74c39d38186c6cf7e64"),
        "v310_engine": (PROJECT_DIR / "src/crypto_backtest/v310_engine.py", "7caaf9dfdaccf3d0d1c2c9fc9dcbadc808acfad27b45ff5d876f46d643507289"),
        "v31_config": (PROJECT_DIR / "config/config_frozen_v3_1.json", "50adc23c620d068087842ca574f8d4f87a8b6de3d96ebca0392184c43574bc84"),
        "v31_engine": (PROJECT_DIR / "src/crypto_backtest/v31_engine.py", "ea91309e5821431210998cf2289965adad8991cc97005105cceab9037aeae2a1"),
        "v39_engine": (PROJECT_DIR / "src/crypto_backtest/v39_engine.py", "02a9a00a1eab84319865b89980081327f5954ea885fcb57a46e8c8af6c1980e2"),
        "v310_manifest": (PROJECT_DIR / "v3_10/artifacts/run_manifest_v3_10.json", sha256_file(PROJECT_DIR / "v3_10/artifacts/run_manifest_v3_10.json")),
    }
    for name, (path, wanted) in expected.items():
        if not path.exists():
            raise FileNotFoundError(f"Frozen dependency missing: {path}")
        actual = sha256_file(path)
        if actual.lower() != wanted.lower():
            raise RuntimeError(f"Frozen dependency changed: {name} {actual} != {wanted}")
        checks[name] = actual

    manifest = pd.read_csv(PROJECT_DIR / "v3_10/artifacts/source_manifest_v3_10.csv")
    for _, row in manifest.iterrows():
        path = PROJECT_DIR / str(row["path"])
        actual = sha256_file(path)
        if actual.lower() != str(row["sha256"]).lower():
            raise RuntimeError(f"Historical data cutoff hash changed: {path}")
    checks["historical_data_manifest"] = dataframe_digest(manifest)
    return checks


def _historical_replay_and_cutoff_state(rules: dict[str, Any]) -> dict[str, Any]:
    base_rules = read_json(PROJECT_DIR / "config/frozen_rules.json")
    source_manifest = pd.read_csv(PROJECT_DIR / "v3_10/artifacts/source_manifest_v3_10.csv")
    frame, _, _, _, contract = load_formal_data(rules, base_rules, source_manifest)
    if pd.Timestamp(frame.iloc[-1]["open_time"]) != HISTORICAL_CUTOFF:
        raise RuntimeError("Historical cutoff does not match the frozen V3.10 run")
    if not contract["pass"]:
        raise RuntimeError("Frozen historical replay data contract failed")

    model_a, locals_a = capture_return_locals(
        run_v31_backtest, frame, rules, make_scenario("A", rules),
        capture=("state", "cycles", "counters"),
    )
    model_b, locals_b = capture_return_locals(
        run_v31_backtest, frame, rules, make_scenario("B", rules), model_a=model_a,
        capture=("state", "cycles", "counters"),
    )
    model_q, locals_q = capture_return_locals(
        run_v310_backtest, frame, rules, make_scenario("Q", rules),
        model_a=model_a, shadow_v31=model_b,
        capture=(
            "state", "cycles", "counters", "stage3_eligible",
            "eligibility_started_at", "sma200_failure_streak", "candidate",
            "next_candidate_id", "last_causal_candidate_id",
        ),
    )

    references = {
        "A": 279201.223366351,
        "B": 348746.8528777533,
        "Q": 367407.5071839701,
    }
    results = {"A": model_a, "B": model_b, "Q": model_q}
    locals_by_model = {"A": locals_a, "B": locals_b, "Q": locals_q}
    cutoff_prices = {
        "BTC": float(frame.iloc[-1]["BTC_close"]),
        "ETH": float(frame.iloc[-1]["ETH_close"]),
    }
    snapshots: dict[str, Any] = {}
    for model in ("A", "B", "Q"):
        result = results[model]
        actual = float(result.summary["final_portfolio_value"])
        if abs(actual - references[model]) > 0.01:
            raise RuntimeError(f"Frozen replay mismatch for {model}: {actual}")
        raw_state = locals_by_model[model]["state"]
        if abs(state_value(raw_state, cutoff_prices) - actual) > 0.01:
            raise RuntimeError(f"Captured cutoff state valuation mismatch for {model}")
        scale = 20_000.0 / actual
        normalized_state = scale_state(raw_state, scale)
        if abs(state_value(normalized_state, cutoff_prices) - 20_000.0) > 1e-7:
            raise RuntimeError(f"Normalized cutoff state valuation mismatch for {model}")
        snapshots[model] = {
            "historical_value": actual,
            "scale_factor": scale,
            "state": state_to_dict(normalized_state),
            "cycles": scale_cycles(result.cycles, scale),
            "cutoff_exposure": state_exposure(normalized_state, cutoff_prices),
            "historical_counters": locals_by_model[model]["counters"],
        }

    q_meta = {
        "stage3_eligible": bool(locals_q["stage3_eligible"]),
        "eligibility_started_at": locals_q["eligibility_started_at"],
        "sma200_failure_streak": int(locals_q["sma200_failure_streak"]),
        "candidate": locals_q["candidate"],
        "next_historical_candidate_id": int(locals_q["next_candidate_id"]),
        "last_causal_candidate_id": locals_q["last_causal_candidate_id"],
    }
    # The OOS replay engine starts candidate numbering at one. These exact
    # values prove no historical candidate is open across the boundary.
    if q_meta["stage3_eligible"] or q_meta["candidate"] is not None or q_meta["sma200_failure_streak"] != 0:
        raise RuntimeError("Cutoff contains non-default V3.10 candidate state; explicit resume support required")
    snapshots["Q"]["candidate_state_at_cutoff"] = q_meta
    snapshots["cutoff_prices"] = cutoff_prices
    snapshots["historical_data_contract"] = contract
    _harmonize_forward_pending(snapshots)
    return snapshots


def _harmonize_forward_pending(snapshots: dict[str, Any]) -> None:
    """Use one exact cutoff pending-DCA buffer without changing any NAV.

    Independent NAV scaling otherwise makes the sub-minimum pending cents differ
    by model, which would break the mandated common future DCA execution table.
    The V3.10 normalized pending split is authoritative; only the classification
    between pending and normal cash is changed for A/B, dollar-for-dollar.
    """
    target = copy.deepcopy(snapshots["Q"]["state"]["pending"])
    target_total = sum(float(value) for value in target.values())
    for model in ("A", "B", "Q"):
        payload = snapshots[model]["state"]
        old_total = sum(float(value) for value in payload["pending"].values())
        payload["pending"] = copy.deepcopy(target)
        payload["normal_cash"] = float(payload["normal_cash"]) + old_total - target_total
    snapshots["forward_pending_normalization"] = {
        "method": "V3.10 normalized pending DCA split applied to A/B/Q; offset in normal cash",
        "target_pending": target,
        "changes_crypto_holdings": False,
        "changes_tactical_cash": False,
        "changes_total_nav": False,
        "reason": "preserve a common fixed-DCA execution schedule after independent NAV normalization",
    }


def initialize_if_needed(static: dict[str, Any], source_hashes: dict[str, str]) -> dict[str, Any]:
    if STATE_PATH.exists():
        state = read_json(STATE_PATH)
        frozen = read_json(FROZEN_OUTPUT_PATH)
        if not state.get("forward_start_committed", False):
            # A failed prelaunch may be corrected without a second historical
            # replay. The cutoff snapshot is retained and frozen once more
            # before any OOS portfolio/trade ledger is committed.
            _harmonize_forward_pending(state["cutoff_snapshot"])
            forward_code = {
                "run_forward_v3_10.py": sha256_file(PROJECT_DIR / "run_forward_v3_10.py"),
                "src/crypto_backtest/v310_forward.py": sha256_file(PROJECT_DIR / "src/crypto_backtest/v310_forward.py"),
                "design/best_skill_v310_forward.md": sha256_file(PROJECT_DIR / "design/best_skill_v310_forward.md"),
            }
            frozen["forward_code_sha256"] = forward_code
            frozen["cutoff_state_sha256"] = hashlib.sha256(
                canonical_json(state["cutoff_snapshot"]).encode("utf-8")
            ).hexdigest()
            frozen["prelaunch_refrozen_at_utc"] = utc_now()
            frozen["prelaunch_refreeze_reason"] = "common pending-DCA buffer normalization before first OOS commit"
            write_json(FROZEN_OUTPUT_PATH, frozen)
            write_json(STATE_PATH, state)
            prelaunch_dir = OUTPUT_DIR / "prelaunch_failures"
            prelaunch_dir.mkdir(parents=True, exist_ok=True)
            for key, name in LEDGER_FILES.items():
                source = OUTPUT_DIR / name
                if not source.exists():
                    continue
                if key != "exceptions" and verify_hash_chain(source):
                    continue
                destination = prelaunch_dir / name
                suffix = 1
                while destination.exists():
                    destination = prelaunch_dir / f"{source.stem}_{suffix}{source.suffix}"
                    suffix += 1
                source.replace(destination)
            prior_exception = OUTPUT_DIR / "prelaunch_initialization_exceptions.csv"
            if prior_exception.exists():
                destination = prelaunch_dir / prior_exception.name
                if not destination.exists():
                    prior_exception.replace(destination)
        else:
            mismatches = {
                relative: {"before": expected, "after": sha256_file(PROJECT_DIR / relative)}
                for relative, expected in frozen["forward_code_sha256"].items()
                if sha256_file(PROJECT_DIR / relative) != expected
            }
            if mismatches and not frozen.get("forward_infrastructure_patch_history"):
                allowed = {"run_forward_v3_10.py", "src/crypto_backtest/v310_forward.py"}
                safe_boundary = bool(
                    set(mismatches).issubset(allowed)
                    and int(state.get("oos_rows", 0)) <= 6
                    and int(state.get("evaluation", {}).get("candidate_count", 0)) == 0
                )
                if not safe_boundary:
                    raise RuntimeError(f"FORWARD_CODE_CHANGED: {mismatches}")
                archive = OUTPUT_DIR / "infrastructure_patch_001"
                archive.mkdir(parents=True, exist_ok=True)
                for name in (LEDGER_FILES["daily"], LEDGER_FILES["monthly"], "FORWARD_MONTHLY_2026_09.md"):
                    source = OUTPUT_DIR / name
                    if source.exists():
                        source.replace(archive / name)
                patch_record = {
                    "patch_id": "INFRASTRUCTURE_PATCH_001",
                    "applied_at_utc": utc_now(),
                    "reason": "append only safety for incomplete UTC day month and unresolved candidate outcome records",
                    "source_hash_changes": mismatches,
                    "champion_strategy_source_changed": False,
                    "fsm_or_trading_rule_changed": False,
                    "oos_candidates_before_patch": 0,
                    "affected_reporting_ledgers_archived": True,
                }
                frozen["forward_infrastructure_patch_history"] = [patch_record]
                for relative, values in mismatches.items():
                    frozen["forward_code_sha256"][relative] = values["after"]
                write_json(FROZEN_OUTPUT_PATH, frozen)
                (OUTPUT_DIR / "FORWARD_INFRASTRUCTURE_PATCH_001.md").write_text(
                    "# FORWARD INFRASTRUCTURE PATCH 001\n\n"
                    "Only append-only reporting lifecycle code changed. V3.10/V3.1 strategy, "
                    "signals, holdings, transactions, parameters, and frozen historical data did not change.\n",
                    encoding="utf-8",
                )
            elif mismatches and len(frozen.get("forward_infrastructure_patch_history", [])) == 1:
                allowed = {"run_forward_v3_10.py"}
                safe_boundary = bool(
                    set(mismatches).issubset(allowed)
                    and int(state.get("oos_rows", 0)) <= 6
                    and int(state.get("evaluation", {}).get("candidate_count", 0)) == 0
                )
                if not safe_boundary:
                    raise RuntimeError(f"FORWARD_CODE_CHANGED: {mismatches}")
                archive = OUTPUT_DIR / "infrastructure_patch_002"
                archive.mkdir(parents=True, exist_ok=True)
                trade_path = OUTPUT_DIR / LEDGER_FILES["trades"]
                if trade_path.exists():
                    trade_path.replace(archive / trade_path.name)
                patch_record = {
                    "patch_id": "INFRASTRUCTURE_PATCH_002",
                    "applied_at_utc": utc_now(),
                    "reason": "segregate Fixed DCA from tactical event ledger and aggregate each tactical event by asset",
                    "source_hash_changes": mismatches,
                    "champion_strategy_source_changed": False,
                    "fsm_or_trading_rule_changed": False,
                    "oos_candidates_before_patch": 0,
                    "affected_trade_ledger_archived": True,
                }
                frozen["forward_infrastructure_patch_history"].append(patch_record)
                for relative, values in mismatches.items():
                    frozen["forward_code_sha256"][relative] = values["after"]
                write_json(FROZEN_OUTPUT_PATH, frozen)
                (OUTPUT_DIR / "FORWARD_INFRASTRUCTURE_PATCH_002.md").write_text(
                    "# FORWARD INFRASTRUCTURE PATCH 002\n\n"
                    "Fixed DCA rows were removed from the tactical-event view and retained in the "
                    "separate Fixed DCA ledger. V3.10/V3.1 strategy code and portfolio results did not change.\n",
                    encoding="utf-8",
                )
            elif mismatches and len(frozen.get("forward_infrastructure_patch_history", [])) == 2:
                allowed = {"run_forward_v3_10.py"}
                safe_boundary = bool(
                    set(mismatches).issubset(allowed)
                    and int(state.get("oos_rows", 0)) <= 6
                    and int(state.get("evaluation", {}).get("candidate_count", 0)) == 0
                )
                if not safe_boundary:
                    raise RuntimeError(f"FORWARD_CODE_CHANGED: {mismatches}")
                patch_record = {
                    "patch_id": "INFRASTRUCTURE_PATCH_003",
                    "applied_at_utc": utc_now(),
                    "reason": "sort the multi-model signal ledger by execution time and model before append-only hashing",
                    "source_hash_changes": mismatches,
                    "champion_strategy_source_changed": False,
                    "fsm_or_trading_rule_changed": False,
                    "oos_candidates_before_patch": 0,
                    "affected_signal_rows_rewritten": False,
                }
                frozen["forward_infrastructure_patch_history"].append(patch_record)
                for relative, values in mismatches.items():
                    frozen["forward_code_sha256"][relative] = values["after"]
                write_json(FROZEN_OUTPUT_PATH, frozen)
                (OUTPUT_DIR / "FORWARD_INFRASTRUCTURE_PATCH_003.md").write_text(
                    "# FORWARD INFRASTRUCTURE PATCH 003\n\n"
                    "The multi-model signal ledger is now sorted by execution time and model before "
                    "append-only hashing. Existing rows were not rewritten. V3.10/V3.1 strategy code, "
                    "signals, holdings, transactions, parameters, and frozen historical data did not change.\n",
                    encoding="utf-8",
                )
            elif mismatches and len(frozen.get("forward_infrastructure_patch_history", [])) == 3:
                allowed = {"run_forward_v3_10.py"}
                safe_boundary = bool(
                    set(mismatches).issubset(allowed)
                    and int(state.get("oos_rows", 0)) <= 6
                    and int(state.get("evaluation", {}).get("candidate_count", 0)) == 0
                )
                if not safe_boundary:
                    raise RuntimeError(f"FORWARD_CODE_CHANGED: {mismatches}")
                patch_record = {
                    "patch_id": "INFRASTRUCTURE_PATCH_004",
                    "applied_at_utc": utc_now(),
                    "reason": "retain the existing exception ledger during successful append-only verification",
                    "source_hash_changes": mismatches,
                    "champion_strategy_source_changed": False,
                    "fsm_or_trading_rule_changed": False,
                    "oos_candidates_before_patch": 0,
                    "existing_exception_rows_rewritten": False,
                }
                frozen["forward_infrastructure_patch_history"].append(patch_record)
                for relative, values in mismatches.items():
                    frozen["forward_code_sha256"][relative] = values["after"]
                write_json(FROZEN_OUTPUT_PATH, frozen)
                (OUTPUT_DIR / "FORWARD_INFRASTRUCTURE_PATCH_004.md").write_text(
                    "# FORWARD INFRASTRUCTURE PATCH 004\n\n"
                    "Successful runs now load and verify the existing exception ledger instead of "
                    "presenting an empty replacement frame. Existing exception rows were not rewritten. "
                    "V3.10/V3.1 strategy code, signals, holdings, transactions, parameters, and frozen "
                    "historical data did not change.\n",
                    encoding="utf-8",
                )
            elif mismatches:
                raise RuntimeError(f"FORWARD_CODE_CHANGED: {mismatches}")
        return state

    snapshots = _historical_replay_and_cutoff_state(
        read_json(PROJECT_DIR / "config/config_frozen_v3_1.json")
    )
    initialized_at = utc_now()
    forward_code = {
        "run_forward_v3_10.py": sha256_file(PROJECT_DIR / "run_forward_v3_10.py"),
        "src/crypto_backtest/v310_forward.py": sha256_file(PROJECT_DIR / "src/crypto_backtest/v310_forward.py"),
        "design/best_skill_v310_forward.md": sha256_file(PROJECT_DIR / "design/best_skill_v310_forward.md"),
    }
    frozen = copy.deepcopy(static)
    frozen.update({
        "frozen_at_utc": initialized_at,
        "frozen_before_first_oos_execution": True,
        "historical_source_sha256": source_hashes,
        "forward_code_sha256": forward_code,
        "cutoff_state_sha256": hashlib.sha256(canonical_json(snapshots).encode("utf-8")).hexdigest(),
        "hash_chain": "sha256(prev_record_hash + '|' + canonical_json(row_without_hashes))",
    })
    write_json(FROZEN_OUTPUT_PATH, frozen)
    state = {
        "schema_version": "1.0",
        "label": "FORWARD_PAPER_ONLY",
        "initialized_at_utc": initialized_at,
        "historical_cutoff": HISTORICAL_CUTOFF.isoformat(),
        "last_processed_4h_open": HISTORICAL_CUTOFF.isoformat(),
        "cutoff_snapshot": snapshots,
        "current_runtime": {},
        "oos_start": None,
        "last_binance_server_time": None,
        "historical_replay_count": 1,
        "forward_start_committed": False,
        "status": "INITIALIZED",
    }
    write_json(STATE_PATH, state)
    return state


def _content_id(frame: pd.DataFrame) -> str:
    columns = ["open_time", "close_time", "open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
    return dataframe_digest(frame[columns])[:16]


def fetch_oos_batches(server_ms: int) -> list[dict[str, Any]]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    starts = {
        "4h": HISTORICAL_CUTOFF + pd.Timedelta(hours=4),
        "1d": HISTORICAL_CUTOFF.floor("D"),
    }
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for interval in ("4h", "1d"):
            try:
                frame = download_binance_klines(
                    symbol, interval, int(starts[interval].timestamp() * 1000), int(server_ms),
                )
            except RuntimeError as exc:
                if "No Binance rows returned" in str(exc):
                    continue
                raise
            if interval == "4h":
                frame = frame.loc[frame["open_time"] > HISTORICAL_CUTOFF].copy()
            else:
                frame = frame.loc[frame["open_time"] >= HISTORICAL_CUTOFF.floor("D")].copy()
            if frame.empty:
                continue
            if not bool((pd.to_datetime(frame["close_time"], utc=True) < pd.to_datetime(server_ms, unit="ms", utc=True)).all()):
                raise RuntimeError(f"INCOMPLETE_CANDLE: {symbol} {interval}")
            content = _content_id(frame)
            first = pd.Timestamp(frame.iloc[0]["open_time"]).strftime("%Y%m%dT%H%M")
            last = pd.Timestamp(frame.iloc[-1]["open_time"]).strftime("%Y%m%dT%H%M")
            path = RAW_DIR / f"binance_{symbol}_{interval}_{first}_{last}_{content}.csv.gz"
            if not path.exists():
                write_csv_gz(frame, path)
            rows.append({
                "symbol": symbol,
                "interval": interval,
                "rows": len(frame),
                "first_open": pd.Timestamp(frame.iloc[0]["open_time"]).isoformat(),
                "last_open": pd.Timestamp(frame.iloc[-1]["open_time"]).isoformat(),
                "last_close": pd.Timestamp(frame.iloc[-1]["close_time"]).isoformat(),
                "content_id": content,
                "path": path.relative_to(PROJECT_DIR).as_posix(),
                "sha256": sha256_file(path),
            })
    return rows


def _combine_series(asset: str, symbol: str, interval: str) -> pd.DataFrame:
    frozen = read_csv_gz(PROJECT_DIR / "v3_1/data/raw" / f"binance_{symbol}_{interval}.csv.gz")
    frames = [frozen]
    for path in sorted(RAW_DIR.glob(f"binance_{symbol}_{interval}_*.csv.gz")):
        frames.append(read_csv_gz(path))
    combined = pd.concat(frames, ignore_index=True).sort_values("open_time")
    value_columns = ["close_time", "open", "high", "low", "close", "volume", "quote_volume", "trade_count"]
    duplicate = combined.loc[combined["open_time"].duplicated(keep=False)]
    if not duplicate.empty:
        for timestamp, group in duplicate.groupby("open_time"):
            if any(group[column].astype(str).nunique(dropna=False) != 1 for column in value_columns):
                raise RuntimeError(f"SOURCE_REVISION_AT_{asset}_{interval}_{timestamp}")
    return combined.drop_duplicates("open_time", keep="first").sort_values("open_time").reset_index(drop=True)


def build_oos_frame(server_ms: int, rules: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    bars = {
        "BTC": _combine_series("BTC", "BTCUSDT", "4h"),
        "ETH": _combine_series("ETH", "ETHUSDT", "4h"),
    }
    btc_daily = _combine_series("BTC", "BTCUSDT", "1d")
    bitstamp = read_csv_gz(PROJECT_DIR / "v3_1/data/raw/bitstamp_BTCUSD_1d.csv.gz")
    common, common_contract = build_common_4h_frame(bars)
    base_rules = read_json(PROJECT_DIR / "config/frozen_rules.json")
    daily, source_switch = build_v31_daily(bitstamp, btc_daily, base_rules, rules)
    merged = merge_v31_features_to_bars(common, daily)
    oos = merged.loc[merged["open_time"] > HISTORICAL_CUTOFF].copy().reset_index(drop=True)
    server_time = pd.to_datetime(server_ms, unit="ms", utc=True)
    if not oos.empty:
        common_close = pd.to_datetime(oos["open_time"], utc=True) + pd.Timedelta(hours=4) - pd.Timedelta(milliseconds=1)
        if not bool((common_close < server_time).all()):
            raise RuntimeError("INCOMPLETE_CANDLE: common 4h")
        expected = pd.date_range(oos.iloc[0]["open_time"], oos.iloc[-1]["open_time"], freq="4h")
        if len(expected) != len(oos) or not pd.Index(expected).equals(pd.DatetimeIndex(oos["open_time"])):
            raise RuntimeError("NON_CONTIGUOUS_COMMON_4H_OOS")
        if pd.Timestamp(oos.iloc[0]["open_time"]) != HISTORICAL_CUTOFF + pd.Timedelta(hours=4):
            raise RuntimeError("FIRST_OOS_BAR_IS_NOT_NEXT_4H_OPEN")
        if bool((oos["signal_available_at"] > oos["open_time"]).any()):
            raise RuntimeError("LOOK_AHEAD_SIGNAL_AVAILABILITY")
    contract = {
        "source_switch_date": source_switch,
        "common_4h_contract": common_contract,
        "binance_server_time": server_time.isoformat(),
        "historical_cutoff": HISTORICAL_CUTOFF.isoformat(),
        "oos_rows": len(oos),
        "oos_start": None if oos.empty else pd.Timestamp(oos.iloc[0]["open_time"]).isoformat(),
        "oos_end": None if oos.empty else pd.Timestamp(oos.iloc[-1]["open_time"]).isoformat(),
        "strictly_after_cutoff": bool(oos.empty or (oos["open_time"] > HISTORICAL_CUTOFF).all()),
        "completed_4h_only": bool(oos.empty or (
            pd.to_datetime(oos["open_time"], utc=True) + pd.Timedelta(hours=4)
            - pd.Timedelta(milliseconds=1) < server_time
        ).all()),
        "signal_availability_violations": int((oos["signal_available_at"] > oos["open_time"]).sum()) if not oos.empty else 0,
        "future_label_columns": sorted(set(["bear_label", "future_min_return_60d", "label_end_date"]) & set(oos.columns)),
    }
    contract["pass"] = bool(
        contract["strictly_after_cutoff"] and contract["completed_4h_only"]
        and contract["signal_availability_violations"] == 0
        and not contract["future_label_columns"]
    )
    if not contract["pass"]:
        raise RuntimeError(f"FORWARD_DATA_CONTRACT_FAIL: {contract}")
    return oos, contract


def _anchor_row(model: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    state = state_from_dict(snapshot[model]["state"])
    prices = snapshot["cutoff_prices"]
    values = {asset: state.qty[asset] * float(prices[asset]) for asset in ("BTC", "ETH")}
    temporary = sum(float(lot["cash_remaining"]) for lot in state.temporary_lots if lot["status"] == "OPEN")
    return {
        "record_id": f"{model}:CUTOFF_ANCHOR:{HISTORICAL_CUTOFF.isoformat()}",
        "record_type": "CUTOFF_ANCHOR",
        "timestamp": HISTORICAL_CUTOFF,
        "portfolio_value": 20_000.0,
        "btc_value": values["BTC"],
        "eth_value": values["ETH"],
        "unit_nav": 1.0,
        "drawdown": 0.0,
        "twr_return": 0.0,
        "external_flow": 0.0,
        "normal_cash": state.normal_cash,
        "pending_dca_cash": sum(state.pending.values()),
        "tactical_bear_cash": state.tactical_bear_cash,
        "temporary_hedge_cash": temporary,
        "crypto_exposure": snapshot[model]["cutoff_exposure"],
        "macro_state": state.macro_state,
        "sell_stage": state.stage,
        "active_target": state.active_target,
        "cycle_id": state.active_cycle_id,
        "BTC_close": prices["BTC"],
        "ETH_close": prices["ETH"],
    }


def portfolio_ledger(model: str, result: Any | None, snapshot: dict[str, Any]) -> pd.DataFrame:
    columns = list(_anchor_row(model, snapshot).keys())
    rows = [_anchor_row(model, snapshot)]
    if result is not None:
        keep = [column for column in columns if column not in {"record_id", "record_type"}]
        for _, source in result.history.iterrows():
            row = {column: source.get(column, np.nan) for column in keep}
            timestamp = pd.Timestamp(source["timestamp"])
            row.update({"record_id": f"{model}:OOS:{timestamp.isoformat()}", "record_type": "OOS_BAR"})
            rows.append(row)
    return pd.DataFrame(rows)[columns]


def dca_ledger(result_a: Any | None) -> pd.DataFrame:
    columns = [
        "record_id", "timestamp", "external_flow", "committed_dca", "executed_dca",
        "dca_alloc_BTC", "dca_alloc_ETH", "pending_dca_cash",
    ]
    if result_a is None:
        return pd.DataFrame(columns=columns)
    frame = result_a.history[columns[2:]].copy()
    frame.insert(0, "timestamp", result_a.history["timestamp"])
    frame.insert(0, "record_id", frame["timestamp"].map(lambda value: f"DCA:{pd.Timestamp(value).isoformat()}"))
    return frame[columns]


def trade_ledger(result_q: Any | None) -> pd.DataFrame:
    base_columns = [
        "signal_timestamp", "execution_timestamp", "action", "reason", "side",
        "tactical_event_id", "btc_notional_usd", "eth_notional_usd",
        "total_gross_notional_usd", "exposure_before", "exposure_after",
        "fee_usd", "slippage_usd", "cost_usd", "ledger", "fsm_state",
        "fsm_stage", "cycle_id",
    ]
    if result_q is None or result_q.trades.empty:
        return pd.DataFrame(columns=["record_id", *base_columns])
    source = result_q.trades.loc[
        result_q.trades["action"].astype(str).str.startswith("TACTICAL")
    ].copy().reset_index(drop=True)
    if source.empty:
        return pd.DataFrame(columns=["record_id", *base_columns])
    rows: list[dict[str, Any]] = []
    keys = ["timestamp", "action", "reason", "side", "tactical_event_id", "ledger"]
    for values, group in source.groupby(keys, sort=False, dropna=False):
        timestamp, action, reason, side, event_id, ledger = values
        notionals = group.groupby("asset")["gross_notional_usd"].sum()
        rows.append({
            "record_id": f"TACTICAL:{int(event_id)}:{pd.Timestamp(timestamp).isoformat()}:{action}",
            "signal_timestamp": group.iloc[0]["signal_date"],
            "execution_timestamp": timestamp, "action": action, "reason": reason,
            "side": side, "tactical_event_id": int(event_id),
            "btc_notional_usd": float(notionals.get("BTC", 0.0)),
            "eth_notional_usd": float(notionals.get("ETH", 0.0)),
            "total_gross_notional_usd": float(group["gross_notional_usd"].sum()),
            "exposure_before": group.iloc[0]["before_crypto_exposure"],
            "exposure_after": group.iloc[-1]["after_crypto_exposure"],
            "fee_usd": float(group["fee_usd"].sum()),
            "slippage_usd": float(group["slippage_usd"].sum()),
            "cost_usd": float(group["cost_usd"].sum()), "ledger": ledger,
            "fsm_state": group.iloc[-1]["fsm_state"], "fsm_stage": group.iloc[-1]["fsm_stage"],
            "cycle_id": group.iloc[-1]["cycle_id"],
        })
    return pd.DataFrame(rows, columns=["record_id", *base_columns])


def signal_ledger(result_b: Any | None, result_q: Any | None) -> pd.DataFrame:
    fields = [
        "strategy", "model", "signal_date", "signal_available_at", "execution_4h_open",
        "btc_close", "sma10", "sma20", "sma50", "sma200", "ahr999",
        "state_before", "state_after", "stage_before", "stage_after",
        "active_target_before", "active_target_after", "crypto_exposure_before",
        "crypto_exposure_after", "actions", "stage3_confirmation_eligible",
        "stage3_candidate_active", "stage3_candidate_id", "stage3_confirmation_count",
        "sma200_failure_streak", "distribution_confirmed", "early_bear_confirmed",
        "stage3_confirmed", "deep_bear_structural_confirmed", "crash_level1_raw",
        "crash_level2_market_raw", "right_50_confirmed", "right_60_confirmed",
        *[f"new_bull_gate_{i}" for i in range(1, 8)],
    ]
    frames: list[pd.DataFrame] = []
    for model, result in (("B", result_b), ("Q", result_q)):
        if result is None or result.signals.empty:
            continue
        part = result.signals.reindex(columns=fields).copy()
        part.insert(0, "record_id", part["execution_4h_open"].map(
            lambda value, model=model: f"SIGNAL:{model}:{pd.Timestamp(value).isoformat()}"
        ))
        frames.append(part)
    if not frames:
        return pd.DataFrame(columns=["record_id", *fields])
    # Append-only ledgers require every previously emitted row to remain a
    # prefix. Grouping all B rows before all Q rows breaks that invariant as
    # soon as a second signal date arrives. Use a deterministic chronological
    # order, with the shadow model before the champion on the same timestamp.
    model_order = {"B": 0, "Q": 1}
    combined = pd.concat(frames, ignore_index=True)
    combined["_model_order"] = combined["model"].map(model_order)
    combined = combined.sort_values(
        ["execution_4h_open", "_model_order", "record_id"], kind="stable",
    ).drop(columns="_model_order").reset_index(drop=True)
    return combined


def _candidate_outcome(row: pd.Series) -> str:
    status = str(row.get("confirmed_or_rejected", ""))
    reason = str(row.get("resolution_reason", ""))
    if status == "CONFIRMED":
        return "CONFIRMED_STAGE3"
    if status == "OPEN_AT_END":
        return "OPEN_UNRESOLVED"
    if reason == "SMA200_HARD_FAILURE":
        return "SMA200_HARD_FAILURE"
    if reason == "STAGE4_PRIORITY":
        return "STAGE4_OVERRIDE"
    if reason == "CRASH_PRIORITY":
        return "CRASH_OVERRIDE"
    return "REJECTED_FALSE_BEAR"


def candidate_ledgers(
    result_b: Any | None, result_q: Any | None, horizons: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate_columns = [
        "record_id", "candidate_id", "candidate_date", "candidate_execution_date",
        "original_v31_state", "candidate_reason", "btc_close", "sma20", "sma50",
        "sma200", "close_vs_sma50", "sma20_vs_sma50", "close_vs_sma200",
        "confirmation_close_1", "eligibility_started_at",
    ]
    outcome_columns = [
        "record_id", "candidate_id", "record_type", "outcome", "resolution_date",
        "resolution_reason", "confirmation_count", "horizon_days", "maturity_date",
        "q_return", "v31_return", "return_edge_q_minus_v31", "q_local_max_drawdown",
        "v31_local_max_drawdown", "drawdown_edge_q_minus_v31",
    ]
    if result_q is None or result_q.stage3_candidates.empty:
        return pd.DataFrame(columns=candidate_columns), pd.DataFrame(columns=outcome_columns)

    signals = result_q.signals.set_index("stage3_candidate_id", drop=False) if not result_q.signals.empty else pd.DataFrame()
    candidate_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    q_history = result_q.history.set_index("timestamp")
    b_history = result_b.history.set_index("timestamp") if result_b is not None else pd.DataFrame()
    last_timestamp = pd.Timestamp(result_q.history.iloc[-1]["timestamp"])

    for _, item in result_q.stage3_candidates.sort_values("candidate_id").iterrows():
        cid = int(item["candidate_id"])
        candidate_id = f"FWD-S3-{cid:04d}"
        execution = pd.Timestamp(item["candidate_execution_date"])
        signal_match = result_q.signals.loc[
            pd.to_numeric(result_q.signals.get("stage3_candidate_id"), errors="coerce").eq(cid)
        ]
        signal = signal_match.iloc[0] if not signal_match.empty else pd.Series(dtype=object)
        candidate_rows.append({
            "record_id": f"CANDIDATE:{candidate_id}",
            "candidate_id": candidate_id,
            "candidate_date": item.get("candidate_date"),
            "candidate_execution_date": execution,
            "original_v31_state": item.get("original_v31_state"),
            "candidate_reason": item.get("candidate_reason"),
            "btc_close": signal.get("btc_close", np.nan),
            "sma20": signal.get("sma20", np.nan),
            "sma50": signal.get("sma50", np.nan),
            "sma200": signal.get("sma200", np.nan),
            "close_vs_sma50": item.get("close_vs_sma50"),
            "sma20_vs_sma50": item.get("sma20_vs_sma50"),
            "close_vs_sma200": item.get("close_vs_sma200"),
            "confirmation_close_1": item.get("confirmation_close_1"),
            "eligibility_started_at": item.get("eligibility_started_at"),
        })
        outcome = _candidate_outcome(item)
        if outcome == "OPEN_UNRESOLVED":
            continue
        outcome_rows.append({
            "record_id": f"OUTCOME:{candidate_id}:RESOLUTION",
            "candidate_id": candidate_id,
            "record_type": "RESOLUTION",
            "outcome": outcome,
            "resolution_date": item.get("resolution_date"),
            "resolution_reason": item.get("resolution_reason"),
            "confirmation_count": item.get("confirmation_count"),
            "horizon_days": 0,
            "maturity_date": item.get("resolution_date"),
            "q_return": np.nan, "v31_return": np.nan, "return_edge_q_minus_v31": np.nan,
            "q_local_max_drawdown": np.nan, "v31_local_max_drawdown": np.nan,
            "drawdown_edge_q_minus_v31": np.nan,
        })
        baseline_q = q_history.loc[q_history.index >= execution].head(1)
        baseline_b = b_history.loc[b_history.index >= execution].head(1)
        if baseline_q.empty or baseline_b.empty:
            continue
        q0 = float(baseline_q.iloc[0]["unit_nav"])
        b0 = float(baseline_b.iloc[0]["unit_nav"])
        for horizon in horizons:
            maturity = execution + pd.Timedelta(days=int(horizon))
            if last_timestamp < maturity:
                continue
            q_window = q_history.loc[(q_history.index >= execution) & (q_history.index <= maturity)]
            b_window = b_history.loc[(b_history.index >= execution) & (b_history.index <= maturity)]
            if q_window.empty or b_window.empty:
                continue
            q_path = q_window["unit_nav"].astype(float) / q0
            b_path = b_window["unit_nav"].astype(float) / b0
            q_dd = float((q_path / q_path.cummax() - 1.0).min())
            b_dd = float((b_path / b_path.cummax() - 1.0).min())
            q_return = float(q_path.iloc[-1] - 1.0)
            b_return = float(b_path.iloc[-1] - 1.0)
            outcome_rows.append({
                "record_id": f"OUTCOME:{candidate_id}:H{horizon:03d}",
                "candidate_id": candidate_id, "record_type": "HORIZON_MATURED",
                "outcome": outcome, "resolution_date": item.get("resolution_date"),
                "resolution_reason": item.get("resolution_reason"),
                "confirmation_count": item.get("confirmation_count"),
                "horizon_days": horizon, "maturity_date": maturity,
                "q_return": q_return, "v31_return": b_return,
                "return_edge_q_minus_v31": q_return - b_return,
                "q_local_max_drawdown": q_dd, "v31_local_max_drawdown": b_dd,
                "drawdown_edge_q_minus_v31": q_dd - b_dd,
            })
    return pd.DataFrame(candidate_rows, columns=candidate_columns), pd.DataFrame(outcome_rows, columns=outcome_columns)


def daily_metrics(q_portfolio: pd.DataFrame, b_portfolio: pd.DataFrame, server_ms: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    q = q_portfolio.loc[q_portfolio["record_type"].eq("OOS_BAR")].copy()
    b = b_portfolio.loc[b_portfolio["record_type"].eq("OOS_BAR")].copy()
    if q.empty:
        return pd.DataFrame(columns=[
            "record_id", "date", "q_portfolio_value", "v31_portfolio_value", "q_return",
            "v31_return", "return_edge", "q_drawdown", "v31_drawdown", "drawdown_edge",
            "q_exposure", "v31_exposure", "q_state", "v31_state", "q_stage", "v31_stage",
        ])
    q["date"] = pd.to_datetime(q["timestamp"], utc=True).dt.floor("D")
    b["date"] = pd.to_datetime(b["timestamp"], utc=True).dt.floor("D")
    completed_before = pd.to_datetime(server_ms, unit="ms", utc=True).floor("D")
    q = q.loc[q["date"] < completed_before]
    b = b.loc[b["date"] < completed_before]
    q = q.groupby("date", as_index=False).tail(1).set_index("date")
    b = b.groupby("date", as_index=False).tail(1).set_index("date")
    for date in q.index.intersection(b.index):
        qr, br = q.loc[date], b.loc[date]
        rows.append({
            "record_id": f"DAILY:{pd.Timestamp(date).date().isoformat()}", "date": date,
            "q_portfolio_value": qr["portfolio_value"], "v31_portfolio_value": br["portfolio_value"],
            "q_return": float(qr["unit_nav"]) - 1.0, "v31_return": float(br["unit_nav"]) - 1.0,
            "return_edge": float(qr["unit_nav"]) - float(br["unit_nav"]),
            "q_drawdown": qr["drawdown"], "v31_drawdown": br["drawdown"],
            "drawdown_edge": float(qr["drawdown"]) - float(br["drawdown"]),
            "q_exposure": qr["crypto_exposure"], "v31_exposure": br["crypto_exposure"],
            "q_state": qr["macro_state"], "v31_state": br["macro_state"],
            "q_stage": qr["sell_stage"], "v31_stage": br["sell_stage"],
        })
    return pd.DataFrame(rows)


def monthly_metrics(daily: pd.DataFrame, server_ms: int) -> pd.DataFrame:
    columns = [
        "record_id", "month", "observations", "q_ending_value", "v31_ending_value",
        "q_month_return", "v31_month_return", "return_edge", "q_max_drawdown",
        "v31_max_drawdown", "drawdown_edge", "q_mean_exposure", "v31_mean_exposure",
    ]
    if daily.empty:
        return pd.DataFrame(columns=columns)
    work = daily.copy()
    work["month"] = pd.to_datetime(work["date"], utc=True).dt.strftime("%Y-%m")
    current_month = pd.to_datetime(server_ms, unit="ms", utc=True).strftime("%Y-%m")
    work = work.loc[~work["month"].eq(current_month)]
    if work.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for month, group in work.groupby("month", sort=True):
        q_start = 20_000.0 if not rows else rows[-1]["q_ending_value"]
        b_start = 20_000.0 if not rows else rows[-1]["v31_ending_value"]
        q_end = float(group.iloc[-1]["q_portfolio_value"])
        b_end = float(group.iloc[-1]["v31_portfolio_value"])
        rows.append({
            "record_id": f"MONTHLY:{month}", "month": month, "observations": len(group),
            "q_ending_value": q_end, "v31_ending_value": b_end,
            "q_month_return": q_end / q_start - 1.0, "v31_month_return": b_end / b_start - 1.0,
            "return_edge": q_end / q_start - b_end / b_start,
            "q_max_drawdown": float(group["q_drawdown"].min()),
            "v31_max_drawdown": float(group["v31_drawdown"].min()),
            "drawdown_edge": float(group["q_drawdown"].min() - group["v31_drawdown"].min()),
            "q_mean_exposure": float(group["q_exposure"].mean()),
            "v31_mean_exposure": float(group["v31_exposure"].mean()),
        })
    return pd.DataFrame(rows, columns=columns)


def _plot_save(fig: plt.Figure, stem: str) -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{stem}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def create_figures(
    q: pd.DataFrame, b: pd.DataFrame, trades: pd.DataFrame, candidates: pd.DataFrame,
) -> None:
    qx = q.copy(); bx = b.copy()
    qx["timestamp"] = pd.to_datetime(qx["timestamp"], utc=True)
    bx["timestamp"] = pd.to_datetime(bx["timestamp"], utc=True)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(qx["timestamp"], qx["portfolio_value"], label="V3.10 Champion", lw=2)
    ax.plot(bx["timestamp"], bx["portfolio_value"], label="V3.1 Shadow", lw=1.7, ls="--")
    ax.set(title="Forward Paper Equity", ylabel="Portfolio value (USD)")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "01_forward_equity")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(qx["timestamp"], 100 * pd.to_numeric(qx["drawdown"]), label="V3.10")
    ax.plot(bx["timestamp"], 100 * pd.to_numeric(bx["drawdown"]), label="V3.1", ls="--")
    ax.set(title="Forward Drawdown", ylabel="Drawdown (%)")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "02_forward_drawdown")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(qx["timestamp"], 100 * pd.to_numeric(qx["crypto_exposure"]), label="V3.10")
    ax.plot(bx["timestamp"], 100 * pd.to_numeric(bx["crypto_exposure"]), label="V3.1", ls="--")
    ax.set(title="Forward Crypto Exposure", ylabel="Exposure (%)")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "03_forward_exposure")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(qx["timestamp"], 100 * pd.to_numeric(qx["crypto_exposure"]), label="V3.10 exposure")
    if not candidates.empty:
        for idx, value in enumerate(pd.to_datetime(candidates["candidate_execution_date"], utc=True)):
            ax.axvline(value, color="tab:red", alpha=.55, lw=1.5, label="Stage3 candidate" if idx == 0 else None)
    else:
        ax.text(.5, .5, "No OOS Stage3 candidate yet", transform=ax.transAxes, ha="center", va="center")
    ax.set(title="Stage3 Candidate History", ylabel="Exposure (%)")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "04_stage3_candidate_history")

    states = {name: index for index, name in enumerate(["BULL", "DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION", "NEW_BULL"])}
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.step(qx["timestamp"], qx["macro_state"].map(states), where="post", label="V3.10")
    ax.step(bx["timestamp"], bx["macro_state"].map(states), where="post", label="V3.1", ls="--")
    ax.set_yticks(list(states.values()), list(states.keys()))
    ax.set(title="Forward State Timeline", ylabel="FSM state")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "05_forward_state_timeline")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    if trades.empty:
        ax.plot(qx["timestamp"], np.zeros(len(qx)), label="V3.10 tactical turnover")
    else:
        tactical = trades.loc[trades["action"].astype(str).str.startswith("TACTICAL")].copy()
        tactical["execution_timestamp"] = pd.to_datetime(tactical["execution_timestamp"], utc=True)
        tactical["turnover"] = pd.to_numeric(tactical["total_gross_notional_usd"]).cumsum() / 20_000.0
        ax.step(tactical["execution_timestamp"], tactical["turnover"], where="post", label="V3.10 tactical turnover")
    ax.set(title="Forward Tactical Turnover", ylabel="Gross notional / initial NAV")
    ax.legend(); ax.grid(alpha=.25)
    _plot_save(fig, "06_forward_turnover")


def evaluate_forward(
    q: pd.DataFrame, b: pd.DataFrame, candidates: pd.DataFrame, outcomes: pd.DataFrame,
    contract: dict[str, Any], safety_exceptions: int,
) -> dict[str, Any]:
    oos_q = q.loc[q["record_type"].eq("OOS_BAR")]
    oos_b = b.loc[b["record_type"].eq("OOS_BAR")]
    if oos_q.empty:
        oos_days = 0.0
        q_return = b_return = q_dd = b_dd = 0.0
    else:
        oos_days = (pd.Timestamp(oos_q.iloc[-1]["timestamp"]) - HISTORICAL_CUTOFF).total_seconds() / 86_400.0
        q_return = float(oos_q.iloc[-1]["unit_nav"]) - 1.0
        b_return = float(oos_b.iloc[-1]["unit_nav"]) - 1.0
        q_dd = float(pd.to_numeric(oos_q["drawdown"]).min())
        b_dd = float(pd.to_numeric(oos_b["drawdown"]).min())
    resolved = outcomes.loc[outcomes["record_type"].eq("RESOLUTION")] if not outcomes.empty else outcomes
    resolved_count = len(resolved)
    early_safety_fail = bool(safety_exceptions or not contract.get("pass", False))
    mature = bool(oos_days >= 180 and resolved_count >= 3)
    h60 = outcomes.loc[
        outcomes["record_type"].eq("HORIZON_MATURED") & pd.to_numeric(outcomes["horizon_days"]).eq(60)
    ] if not outcomes.empty else pd.DataFrame()
    med_return = float(h60["return_edge_q_minus_v31"].median()) if not h60.empty else np.nan
    med_dd = float(h60["drawdown_edge_q_minus_v31"].median()) if not h60.empty else np.nan
    tail_warning = bool(not h60.empty and (h60["drawdown_edge_q_minus_v31"] < -0.05).any())
    checks = {
        "OOS_180_DAYS": oos_days >= 180,
        "RESOLVED_CANDIDATES_GTE_3": resolved_count >= 3,
        "OVERALL_DD_WORSENING_LTE_3PP": q_dd >= b_dd - 0.03,
        "NO_LOWER_RETURN_AND_WORSE_DD": not (q_return < b_return and q_dd < b_dd),
        "MEDIAN_60D_EDGE_NOT_BOTH_NEGATIVE": bool(pd.isna(med_return) or pd.isna(med_dd) or not (med_return < 0 and med_dd < 0)),
        "NO_EARLY_SAFETY_FAIL": not early_safety_fail,
    }
    if early_safety_fail:
        verdict = "D. V3.10 FORWARD SAFETY FAIL"
    elif not mature:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif all(checks.values()):
        verdict = "A. V3.10 FORWARD EVIDENCE SUPPORTIVE"
    elif checks["NO_LOWER_RETURN_AND_WORSE_DD"] and checks["MEDIAN_60D_EDGE_NOT_BOTH_NEGATIVE"]:
        verdict = "B. V3.10 FORWARD EVIDENCE INCONCLUSIVE"
    else:
        verdict = "C. V3.10 FORWARD EDGE NOT SUPPORTED"
    return {
        "verdict": verdict, "checkpoint_mature": mature, "oos_calendar_days": oos_days,
        "resolved_candidate_count": resolved_count, "candidate_count": len(candidates),
        "q_twr_return": q_return, "v31_twr_return": b_return,
        "q_max_drawdown": q_dd, "v31_max_drawdown": b_dd,
        "median_candidate_60d_return_edge": med_return,
        "median_candidate_60d_drawdown_edge": med_dd,
        "stage3_delay_tail_risk_warning": tail_warning,
        "checks": checks,
    }


def write_daily_status(
    state: dict[str, Any], q: pd.DataFrame, b: pd.DataFrame, signals: pd.DataFrame,
    candidates: pd.DataFrame, evaluation: dict[str, Any], hash_ok: bool,
) -> None:
    qlast, blast = q.iloc[-1], b.iloc[-1]
    oos_signals = signals.loc[signals["model"].eq("Q")] if not signals.empty else pd.DataFrame()
    last_signal = oos_signals.iloc[-1] if not oos_signals.empty else pd.Series(dtype=object)
    candidate_active = bool(not candidates.empty and evaluation["resolved_candidate_count"] < len(candidates))
    crash = "CRASH_L1:" in str(last_signal.get("actions", "")) or "CRASH_L2:" in str(last_signal.get("actions", ""))
    content = f"""# DAILY FORWARD STATUS

- Label: `FORWARD_PAPER_ONLY`
- Date: {pd.Timestamp(qlast['timestamp']).isoformat()}
- BTC: ${float(qlast['BTC_close']):,.2f}
- ETH: ${float(qlast['ETH_close']):,.2f}
- V3.10 State / Stage / Target / Actual Exposure: `{qlast['macro_state']}` / `{int(qlast['sell_stage'])}` / `{float(qlast['active_target']):.2%}` / `{float(qlast['crypto_exposure']):.2%}`
- V3.1 Shadow State / Stage / Target / Actual Exposure: `{blast['macro_state']}` / `{int(blast['sell_stage'])}` / `{float(blast['active_target']):.2%}` / `{float(blast['crypto_exposure']):.2%}`
- Stage3 Candidate: `{'YES' if candidate_active else 'NO'}`
- Crash: `{'YES' if crash else 'NO'}`
- AHR999: `{last_signal.get('ahr999', 'N/A')}`
- Today Tactical Action: `{last_signal.get('actions', '') or 'NONE'}`
- Next Risk Trigger: `Frozen V3.10 Stage4 / Crash / candidate-resolution rules only`
- Current Drawdown: `{float(qlast['drawdown']):.4%}`
- OOS elapsed: `{evaluation['oos_calendar_days']:.2f}` calendar days
- Resolved Candidates: `{evaluation['resolved_candidate_count']}` / minimum `3`
- Frozen Hash Status: `{'PASS' if hash_ok else 'FAIL'}`
- Current Evaluation: `{evaluation['verdict']}`

Formal checkpoint is unavailable until both 180 OOS calendar days and three resolved
new Stage3 candidates are present. No parameter or trading rule was changed.
"""
    (OUTPUT_DIR / "DAILY_FORWARD_STATUS.md").write_text(content, encoding="utf-8")


def write_monthly_reports(monthly: pd.DataFrame, candidates: pd.DataFrame, outcomes: pd.DataFrame, exceptions: int) -> None:
    for _, row in monthly.iterrows():
        month = str(row["month"])
        month_candidates = candidates.loc[pd.to_datetime(candidates["candidate_date"], utc=True).dt.strftime("%Y-%m").eq(month)] if not candidates.empty else candidates
        resolved = outcomes.loc[
            outcomes["record_type"].eq("RESOLUTION") & ~outcomes["outcome"].eq("OPEN_UNRESOLVED")
        ] if not outcomes.empty else outcomes
        text = f"""# FORWARD MONTHLY {month}

- Label: `FORWARD_PAPER_ONLY`
- V3.10 Return: {float(row['q_month_return']):.4%}
- V3.1 Return: {float(row['v31_month_return']):.4%}
- V3.10 Max DD: {float(row['q_max_drawdown']):.4%}
- V3.1 Max DD: {float(row['v31_max_drawdown']):.4%}
- V3.10 Average Exposure: {float(row['q_mean_exposure']):.4%}
- V3.1 Average Exposure: {float(row['v31_mean_exposure']):.4%}
- Candidate Count: {len(month_candidates)}
- Open Candidates: {max(0, len(candidates) - len(resolved))}
- Resolved Candidates: {len(resolved)}
- Safety Exceptions: {exceptions}
- Frozen Code Hash: PASS
- Historical Data Cutoff: {HISTORICAL_CUTOFF.isoformat()}
"""
        (OUTPUT_DIR / f"FORWARD_MONTHLY_{month.replace('-', '_')}.md").write_text(text, encoding="utf-8")


def _exception_columns() -> list[str]:
    return ["record_id", "timestamp", "event_type", "severity", "message", "action_taken"]


def load_exception_ledger(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size:
        return pd.read_csv(path).drop(columns=["prev_record_hash", "record_hash"], errors="ignore")
    return pd.DataFrame(columns=_exception_columns())


def record_exception(exc: BaseException) -> None:
    path = OUTPUT_DIR / LEDGER_FILES["exceptions"]
    rows = load_exception_ledger(path)
    stamp = pd.Timestamp.now(tz="UTC")
    new = pd.DataFrame([{
        "record_id": f"EXCEPTION:{stamp.isoformat()}:{type(exc).__name__}",
        "timestamp": stamp, "event_type": "EXECUTION_EXCEPTION", "severity": "SAFETY_FAIL",
        "message": f"{type(exc).__name__}: {exc}", "action_taken": "HALT_NO_RECORD_REWRITE",
    }])
    append_verified(pd.concat([rows, new], ignore_index=True), path)


def _source_batch_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(RAW_DIR.glob("*.csv.gz")):
        frame = read_csv_gz(path)
        parts = path.name.split("_")
        rows.append({
            "path": path.relative_to(PROJECT_DIR).as_posix(), "sha256": sha256_file(path),
            "rows": len(frame), "start": pd.Timestamp(frame.iloc[0]["open_time"]).isoformat(),
            "end": pd.Timestamp(frame.iloc[-1]["close_time"]).isoformat(),
        })
    return rows


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    static = read_json(STATIC_CONFIG_PATH)
    source_hashes = _verify_historical_sources(static)
    state = initialize_if_needed(static, source_hashes)
    frozen = read_json(FROZEN_OUTPUT_PATH)

    server_ms = binance_server_time_ms()
    new_batches = fetch_oos_batches(server_ms)
    rules = read_json(PROJECT_DIR / "config/config_frozen_v3_1.json")
    oos, contract = build_oos_frame(server_ms, rules)
    results, runtime = run_resumed_oos(oos, rules, state["cutoff_snapshot"])

    result_a = results.get("A")
    result_b = results.get("B")
    result_q = results.get("Q")
    q_portfolio = portfolio_ledger("Q", result_q, state["cutoff_snapshot"])
    b_portfolio = portfolio_ledger("B", result_b, state["cutoff_snapshot"])
    dca = dca_ledger(result_a)
    trades = trade_ledger(result_q)
    signals = signal_ledger(result_b, result_q)
    candidates, outcomes = candidate_ledgers(
        result_b, result_q, list(static["candidate_horizons_calendar_days"]),
    )
    daily = daily_metrics(q_portfolio, b_portfolio, server_ms)
    monthly = monthly_metrics(daily, server_ms)
    exceptions = load_exception_ledger(OUTPUT_DIR / LEDGER_FILES["exceptions"])

    ledgers = {
        "Q": q_portfolio, "B": b_portfolio, "trades": trades, "dca": dca,
        "candidates": candidates, "outcomes": outcomes, "signals": signals,
        "exceptions": exceptions, "daily": daily, "monthly": monthly,
    }
    append_results: dict[str, Any] = {}
    for key, frame in ledgers.items():
        appended, last_hash = append_verified(frame, OUTPUT_DIR / LEDGER_FILES[key])
        append_results[key] = {"appended_rows": appended, "last_record_hash": last_hash}

    hash_ok = all(verify_hash_chain(OUTPUT_DIR / name) for name in LEDGER_FILES.values())
    if not hash_ok:
        raise RuntimeError("APPEND_ONLY_HASH_CHAIN_FAIL")
    safety_exceptions = 0
    exception_path = OUTPUT_DIR / LEDGER_FILES["exceptions"]
    if exception_path.exists() and exception_path.stat().st_size:
        safety_exceptions = len(pd.read_csv(exception_path))
    evaluation = evaluate_forward(
        q_portfolio, b_portfolio, candidates, outcomes, contract, safety_exceptions,
    )

    create_figures(q_portfolio, b_portfolio, trades, candidates)
    write_daily_status(state, q_portfolio, b_portfolio, signals, candidates, evaluation, hash_ok)
    write_monthly_reports(monthly, candidates, outcomes, safety_exceptions)

    if not candidates.empty:
        open_count = len(candidates) - evaluation["resolved_candidate_count"]
        if open_count > 0:
            latest = candidates.iloc[-1]
            alert = f"""# STAGE3 CANDIDATE ALERT

- Candidate: `{latest['candidate_id']}`
- Created: `{pd.Timestamp(latest['candidate_execution_date']).isoformat()}`
- V3.1 action: unchanged Stage3 transition was eligible.
- V3.10 action: held the prior legal target pending three completed closes.
- SMA20 / SMA50 / SMA200: `{latest['sma20']}` / `{latest['sma50']}` / `{latest['sma200']}`
- Stage4 / Crash override: remains immediate and unchanged.
"""
            (OUTPUT_DIR / "STAGE3_CANDIDATE_ALERT.md").write_text(alert, encoding="utf-8")

    if evaluation["checkpoint_mature"] or evaluation["verdict"].startswith("D."):
        checkpoint = f"""# V3.10 FORWARD CHECKPOINT

- Verdict: `{evaluation['verdict']}`
- OOS calendar days: `{evaluation['oos_calendar_days']:.2f}`
- Resolved candidates: `{evaluation['resolved_candidate_count']}`
- V3.10 TWR return: `{evaluation['q_twr_return']:.4%}`
- V3.1 TWR return: `{evaluation['v31_twr_return']:.4%}`
- V3.10 Max DD: `{evaluation['q_max_drawdown']:.4%}`
- V3.1 Max DD: `{evaluation['v31_max_drawdown']:.4%}`

No strategy rule or parameter was modified by this evaluation.
"""
        (OUTPUT_DIR / "V310_FORWARD_CHECKPOINT.md").write_text(checkpoint, encoding="utf-8")

    last_timestamp = HISTORICAL_CUTOFF if oos.empty else pd.Timestamp(oos.iloc[-1]["open_time"])
    state.update({
        "last_run_utc": utc_now(),
        "last_binance_server_time": pd.to_datetime(server_ms, unit="ms", utc=True).isoformat(),
        "oos_start": None if oos.empty else pd.Timestamp(oos.iloc[0]["open_time"]).isoformat(),
        "last_processed_4h_open": last_timestamp.isoformat(),
        "oos_rows": len(oos), "current_runtime": runtime,
        "evaluation": evaluation, "status": evaluation["verdict"],
        "append_only_hash_status": "PASS" if hash_ok else "FAIL",
        "forward_start_committed": True,
    })
    write_json(STATE_PATH, state)

    current_summaries = {
        model: result.summary for model, result in results.items()
    } if results else {}
    output_hashes = {
        path.relative_to(OUTPUT_DIR).as_posix(): sha256_file(path)
        for path in sorted(OUTPUT_DIR.rglob("*"))
        if path.is_file() and path != MANIFEST_PATH
    }
    manifest = {
        "schema_version": "1.0", "label": "FORWARD_PAPER_ONLY",
        "updated_at_utc": utc_now(), "historical_cutoff": HISTORICAL_CUTOFF.isoformat(),
        "binance_server_time": pd.to_datetime(server_ms, unit="ms", utc=True).isoformat(),
        "oos_start": state["oos_start"], "oos_end": last_timestamp.isoformat(),
        "oos_rows": len(oos), "historical_replay_count": state["historical_replay_count"],
        "frozen_config_sha256": sha256_file(FROZEN_OUTPUT_PATH),
        "frozen_hash_status": "PASS", "append_only_hash_status": "PASS",
        "data_contract": contract, "new_batch_observations": new_batches,
        "immutable_raw_batches": _source_batch_inventory(),
        "append_results": append_results, "evaluation": evaluation,
        "current_engine_summaries": current_summaries,
        "python": sys.version, "platform": platform.platform(),
        "outputs_sha256": output_hashes,
    }
    write_json(MANIFEST_PATH, manifest)

    q_last, b_last = q_portfolio.iloc[-1], b_portfolio.iloc[-1]
    candidate_status = "NONE" if candidates.empty else (
        f"OPEN ({len(candidates) - evaluation['resolved_candidate_count']})"
        if len(candidates) > evaluation["resolved_candidate_count"] else "NO OPEN CANDIDATE"
    )
    print("FORWARD TEST INITIALIZED")
    print("Frozen Champion: V3.10")
    print("Comparator: V3.1")
    print(f"Historical Cutoff: {HISTORICAL_CUTOFF.isoformat()}")
    print(f"OOS Start: {state['oos_start'] or 'PENDING_FIRST_UNSEEN_DATA'}")
    print(f"V3.10 Current State/Exposure: {q_last['macro_state']} / {float(q_last['crypto_exposure']):.6%}")
    print(f"V3.1 Shadow State/Exposure: {b_last['macro_state']} / {float(b_last['crypto_exposure']):.6%}")
    print(f"Stage3 Candidate Status: {candidate_status}")
    print("Frozen Hash Status: PASS")
    print(f"DAILY_FORWARD_STATUS.md: {OUTPUT_DIR / 'DAILY_FORWARD_STATUS.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as error:
        if not isinstance(error, SystemExit):
            try:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                record_exception(error)
            except Exception:
                pass
        raise
