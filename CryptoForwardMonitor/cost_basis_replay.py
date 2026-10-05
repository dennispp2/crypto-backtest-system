"""Offline cost view. Reads frozen sources; never calls the forward runner's main.

Reconstructs trades in memory using the frozen engine and verifies the complete
portfolio history against the committed ledger before exporting display data.
Only the monitor-side output argument may be written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from cost_basis import account_trades


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_cost_view(project: Path) -> dict:
    import pandas as pd
    sys.path.insert(0, str(project))
    import run_forward_v3_10 as forward

    if forward.PROJECT_DIR.resolve() != project.resolve():
        raise ValueError("Unexpected frozen project path")
    forward._verify_historical_sources(forward.read_json(forward.STATIC_CONFIG_PATH))
    directory = project / "v3_10_forward"
    state_path = directory / "forward_v310_state.json"
    history_path = project / "v3_10/results/trade_log_v3_10.csv"
    manifest_path = directory / "forward_manifest.json"
    ledger_paths = {"Q": directory / "forward_v310_portfolio.csv",
                    "B": directory / "forward_v31_shadow_portfolio.csv"}
    guarded = [state_path, history_path, manifest_path, *ledger_paths.values()]
    before = {str(p): digest(p) for p in guarded}
    state = forward.read_json(state_path)
    manifest = forward.read_json(manifest_path)
    if manifest["frozen_hash_status"] != "PASS":
        raise ValueError("Frozen integrity is not PASS")
    rules = forward.read_json(project / "config/config_frozen_v3_1.json")
    server_ms = int(pd.Timestamp(manifest["binance_server_time"]).timestamp() * 1000)
    frame, _ = forward.build_oos_frame(server_ms, rules)  # Local CSVs only; no network fetch.
    results, _ = forward.run_resumed_oos(frame, rules, state["cutoff_snapshot"])
    historical = pd.read_csv(history_path)
    historical["_time"] = pd.to_datetime(historical["timestamp"], utc=True)
    if historical["_time"].max() > forward.HISTORICAL_CUTOFF:
        raise ValueError("Historical cost source crosses the frozen cutoff")
    output = {"schema_version": 1, "method": "inherited_moving_average_including_buy_costs",
              "note": "含買入費用；承接歷史持倉成本，非前瞻起始日市價。賣出按比例扣除成本。",
              "models": {}, "source_hashes": before}
    for model, ledger_path in ledger_paths.items():
        if not forward.verify_hash_chain(ledger_path):
            raise ValueError(f"{model}: committed ledger hash chain failed")
        saved = pd.read_csv(ledger_path)
        replayed = forward.portfolio_ledger(model, results.get(model), state["cutoff_snapshot"])
        if len(saved) != len(replayed) or saved["record_id"].tolist() != replayed["record_id"].tolist():
            raise ValueError(f"{model}: replay timestamps differ from committed ledger")
        # Verify every bar, not only the last balance. No estimated fills allowed.
        for column in ("portfolio_value", "btc_value", "eth_value", "normal_cash", "pending_dca_cash",
                       "tactical_bear_cash", "temporary_hedge_cash", "BTC_close", "ETH_close"):
            for actual, expected in zip(saved[column], replayed[column]):
                if not math.isclose(float(actual), float(expected), rel_tol=1e-10, abs_tol=1e-7):
                    raise ValueError(f"{model}: replay mismatch in {column}")
        history = historical.loc[historical["model"] == model].sort_values("_time", kind="stable")
        if history.empty:
            raise ValueError(f"{model}: no historical fills")
        book = account_trades(history.to_dict("records"))
        cutoff = state["cutoff_snapshot"][model]
        for asset, position in book.items():
            position.units *= cutoff["scale_factor"]
            position.cost *= cutoff["scale_factor"]
            if not math.isclose(position.units, cutoff["state"]["qty"][asset], rel_tol=1e-10, abs_tol=1e-9):
                raise ValueError(f"{model}/{asset}: historical fill quantities do not reconcile")
        if model in results:
            account_trades(results[model].trades.to_dict("records"), book)
        last = saved.iloc[-1]
        assets = {}
        for asset, position in book.items():
            units = float(last[f"{asset.lower()}_value"]) / float(last[f"{asset}_close"])
            if not math.isclose(position.units, units, rel_tol=1e-10, abs_tol=1e-9):
                raise ValueError(f"{model}/{asset}: ending units do not reconcile")
            assets[asset] = {"units": position.units, "cost_usd": position.cost,
                             "average_cost": position.average}
        output["models"][model] = {"portfolio_sha256": before[str(ledger_path)],
                                    "timestamp": str(last["timestamp"]), "assets": assets}
    if before != {str(p): digest(p) for p in guarded}:
        raise ValueError("Inputs changed during cost reconstruction; retry after model completion")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Restrict this reporting helper to the monitor's data folder.
    allowed = (args.project / "CryptoForwardMonitor/data").resolve()
    if args.output.resolve().parent != allowed:
        raise ValueError("Cost output must be inside the monitor data directory")
    payload = build_cost_view(args.project.resolve())
    from storage import _atomic_text
    _atomic_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    print("COST_BASIS_RECONCILIATION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
