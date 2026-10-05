from __future__ import annotations

import copy
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "v3_8"
V31_DIR = PROJECT_DIR / "v3_1"
V37_DIR = PROJECT_DIR / "v3_7"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.v31_analysis import prefix_trade_identity  # noqa: E402
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v37_engine import run_v37_overlay  # noqa: E402
from crypto_backtest.v38_analysis import (  # noqa: E402
    bottom_summary,
    bottom_whipsaw_audit,
    daily_history_v38,
    enrich_opportunity_cost,
    event_drawdown_audit,
    fixed_dca_integrity,
    fsm_audit,
    no_lookahead_audit,
    overlay_scope_audit,
    promotion_evaluation,
    shadow_replay_integrity,
    shadow_state_parity_audit,
    short_whipsaw_pairs,
    summary_v38,
    tactical_statistics,
    v31_replay_integrity,
    v37_replay_integrity,
    whipsaw_pairs,
)
from crypto_backtest.v38_engine import run_v38_overlay  # noqa: E402
from crypto_backtest.v38_reporting import create_v38_figures, write_v38_report  # noqa: E402
from run_backtest_v3_7 import add_identity, load_formal_data, load_json, write_json  # noqa: E402


def output_hashes_v38(directory: Path) -> dict[str, str]:
    """Hash every deliverable except the self-referential V3.8 manifest."""
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_8.json"
    }


def make_scenario(model: str, base_rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "H0": "H0 - Initial allocation only",
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - V3.1 FSM-only Frozen Champion",
        "S": "SHADOW_V31_ENGINE - Independent unmodified V3.1",
        "J7": "MODEL J7 - V3.7 Frozen Seven-Day Overlay Replay",
        "K": "MODEL K - V3.8 Three-Completed-Close AHR Overlay",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "S", "J7", "K"}, use_ai=False,
        hard_floor=float(base_rules["hard_floor"]),
        initial_capital=float(base_rules["initial_capital"]),
        capital_test="v3_8_formal", variant="frozen", cost_case="v3_1_frozen",
        fee=float(base_rules["costs"]["fee"]), slippage=float(base_rules["costs"]["slippage"]),
    )


def run_initial_only(frame: pd.DataFrame, base_rules: dict[str, Any]) -> V31BacktestResult:
    zero_rules = copy.deepcopy(base_rules)
    zero_rules["external_contribution_per_4h"] = 0.0
    formal = make_scenario("H0", base_rules)
    engine_scenario = V31Scenario(
        name=formal.name, model="A", use_fsm=False, use_ai=False,
        hard_floor=formal.hard_floor, initial_capital=formal.initial_capital,
        capital_test=formal.capital_test, variant=formal.variant,
        cost_case=formal.cost_case, fee=formal.fee, slippage=formal.slippage,
    )
    result = run_v31_backtest(frame, zero_rules, engine_scenario)
    result.scenario = formal
    result.trades.loc[:, "model"] = "H0"
    result.trades.loc[:, "strategy"] = formal.name
    return result


def tactical_event_frame(results: list[V31BacktestResult]) -> pd.DataFrame:
    frames = []
    for result in results:
        if result.scenario.model not in {"B", "J7", "K"}:
            continue
        tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
        if tactical.empty:
            continue
        events = tactical.groupby(["model", "tactical_event_id"], as_index=False).agg(
            timestamp=("timestamp", "first"), side=("side", "first"), action=("action", "first"),
            target_crypto_exposure=("target_crypto_exposure", "first"),
            gross_notional_usd=("gross_notional_usd", "sum"),
        )
        frames.append(events)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> int:
    config_path = PROJECT_DIR / "config" / "config_frozen_v3_8.json"
    base_path = PROJECT_DIR / "config" / "config_frozen_v3_1.json"
    v37_config_path = PROJECT_DIR / "config" / "config_frozen_v3_7.json"
    v37_engine_path = PROJECT_DIR / "src" / "crypto_backtest" / "v37_engine.py"
    rules = load_json(config_path)
    base_rules = load_json(base_path)
    v37_rules = load_json(v37_config_path)
    if not rules.get("frozen_before_formal_run") or not rules.get("forbid_parameter_search"):
        raise RuntimeError("V3.8 was not frozen before formal execution")
    expected_hashes = {
        base_path: rules["base_config_sha256"],
        v37_config_path: rules["v3_7_config_sha256"],
        v37_engine_path: rules["v3_7_engine_sha256"],
    }
    for path, expected in expected_hashes.items():
        if sha256_file(path) != expected:
            raise RuntimeError(f"Frozen dependency changed; V3.8 stopped: {path}")

    source_manifest = pd.read_csv(V31_DIR / "artifacts" / "source_manifest_v3_1.csv")
    frame, daily_features, data_contract = load_formal_data(base_rules, source_manifest)

    model_h0 = run_initial_only(frame, base_rules)
    model_a = run_v31_backtest(frame, base_rules, make_scenario("A", base_rules))
    model_b = run_v31_backtest(frame, base_rules, make_scenario("B", base_rules), model_a=model_a)
    replay_b = v31_replay_integrity(model_b, V31_DIR, rules["reference_v31_b"])
    if not replay_b["pass"]:
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL; challenger not run: {replay_b}")

    shadow = run_v31_backtest(frame, base_rules, make_scenario("S", base_rules), model_a=model_a)
    shadow_replay = shadow_replay_integrity(model_b, shadow)
    if not shadow_replay["pass"]:
        raise RuntimeError(f"SHADOW_V31_ENGINE_REPLAY=FAIL; challenger not run: {shadow_replay}")

    model_j7, j7_overlay = run_v37_overlay(
        frame, base_rules, v37_rules, make_scenario("J7", base_rules),
        model_a=model_a, shadow=shadow,
    )
    replay_j7 = v37_replay_integrity(
        model_j7, V37_DIR, rules["reference_v37_j7"], base_rules,
    )
    if not replay_j7["pass"]:
        raise RuntimeError(f"V3_7_J7_REPLAY_INTEGRITY=FAIL; challenger not run: {replay_j7}")

    model_k, k_overlay, raw_opportunity = run_v38_overlay(
        frame, base_rules, rules, make_scenario("K", base_rules),
        model_a=model_a, shadow=shadow,
    )
    results = [model_h0, model_a, model_b, model_j7, model_k]
    daily_by_model = {result.scenario.model: daily_history_v38(result.history) for result in results}
    parity_audit, parity_summary = shadow_state_parity_audit(
        daily_by_model["B"], daily_by_model["K"],
    )

    result_dir, artifact_dir = OUTPUT_DIR / "results", OUTPUT_DIR / "artifacts"
    for directory in (result_dir, artifact_dir, OUTPUT_DIR / "report", OUTPUT_DIR / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    parity_audit.to_csv(
        result_dir / "shadow_state_parity_audit_v3_8.csv", index=False,
        date_format="%Y-%m-%dT%H:%M:%S%z",
    )
    write_json(artifact_dir / "shadow_state_parity_summary_v3_8.json", parity_summary)
    if not parity_summary["pass"]:
        raise RuntimeError(f"V3_8_ISOLATION_AUDIT=FAIL; performance evaluation forbidden: {parity_summary}")

    # Prefix invariance is a held-out no-look-ahead check, not a performance search.
    prefix_n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:prefix_n].copy()
    prefix_h0 = run_initial_only(prefix_frame, base_rules)
    prefix_a = run_v31_backtest(prefix_frame, base_rules, make_scenario("A", base_rules))
    prefix_b = run_v31_backtest(prefix_frame, base_rules, make_scenario("B", base_rules), model_a=prefix_a)
    prefix_shadow = run_v31_backtest(prefix_frame, base_rules, make_scenario("S", base_rules), model_a=prefix_a)
    prefix_j7, _ = run_v37_overlay(
        prefix_frame, base_rules, v37_rules, make_scenario("J7", base_rules),
        model_a=prefix_a, shadow=prefix_shadow,
    )
    prefix_k, _, _ = run_v38_overlay(
        prefix_frame, base_rules, rules, make_scenario("K", base_rules),
        model_a=prefix_a, shadow=prefix_shadow,
    )
    cutoff = pd.Timestamp(prefix_frame.iloc[-1]["open_time"])
    prefix_checks = {
        "model_h0_trade_prefix_identical": prefix_trade_identity(model_h0, prefix_h0, cutoff),
        "model_a_trade_prefix_identical": prefix_trade_identity(model_a, prefix_a, cutoff),
        "model_b_trade_prefix_identical": prefix_trade_identity(model_b, prefix_b, cutoff),
        "shadow_trade_prefix_identical": prefix_trade_identity(shadow, prefix_shadow, cutoff),
        "model_j7_trade_prefix_identical": prefix_trade_identity(model_j7, prefix_j7, cutoff),
        "model_k_trade_prefix_identical": prefix_trade_identity(model_k, prefix_k, cutoff),
    }

    opportunity, opportunity_stats = enrich_opportunity_cost(raw_opportunity, frame)
    original_ahr_requests = k_overlay.loc[
        k_overlay["shadow_action"].eq("TACTICAL_BUYBACK_AHR999_TO_35")
    ]
    opportunity_stats.update({
        "ahr_requested_shadow_events": int(len(original_ahr_requests)),
        "ahr_delayed_shadow_requests": int(opportunity_stats["delayed_record_count"]),
        "ahr_executed_after_delay": int(opportunity_stats["executed_record_count"]),
        "ahr_cancelled_pending_requests": int(opportunity_stats["cancelled_record_count"]),
        "ahr_executed_without_delay": int(
            len(original_ahr_requests) - opportunity_stats["delayed_record_count"]
        ),
    })
    summary = pd.DataFrame([summary_v38(result, base_rules) for result in results])
    for key, value in opportunity_stats.items():
        summary.loc[summary["model"].eq("K"), key] = value
    fixed_dca = fixed_dca_integrity(results)
    fsm = fsm_audit(model_b, base_rules)
    scope = overlay_scope_audit(k_overlay, shadow)
    signal_times = pd.to_datetime(shadow.signals["execution_4h_open"], utc=True)
    signal_index = {timestamp: index for index, timestamp in enumerate(signal_times)}
    comparison_results = [model_b, model_j7, model_k]
    short_pairs = {
        result.scenario.model: short_whipsaw_pairs(result, signal_index)
        for result in comparison_results
    }
    seven_pairs = {
        result.scenario.model: whipsaw_pairs(result)
        for result in comparison_results
    }
    bottom_audit = bottom_whipsaw_audit(
        comparison_results, j7_overlay, k_overlay, signal_index,
    )
    bottom = bottom_summary(
        comparison_results, daily_by_model, rules["audit_windows"], short_pairs,
        seven_pairs, {"J7": j7_overlay, "K": k_overlay},
    )
    tactical = tactical_statistics(comparison_results, short_pairs, seven_pairs)
    event_audit = event_drawdown_audit(daily_by_model, comparison_results, rules["audit_windows"])
    engine_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v38_engine.py").read_text(encoding="utf-8")
    integrity = no_lookahead_audit(
        frame, daily_features, results, data_contract, fixed_dca, fsm,
        replay_b, replay_j7, shadow_replay, parity_summary, scope,
        opportunity_stats, prefix_checks, engine_source,
    )
    all_integrity = bool(
        integrity["no_lookahead_pass"] and integrity["execution_integrity_pass"]
        and replay_b["pass"] and replay_j7["pass"] and shadow_replay["pass"]
        and parity_summary["pass"] and scope["pass"]
        and fixed_dca["all_match"].all() and fsm["legal_transition"].all()
    )
    comparison, verdict, j_law = promotion_evaluation(
        summary, tactical, event_audit, rules, parity_summary, scope,
        integrity_pass=all_integrity,
    )

    shutil.copy2(config_path, OUTPUT_DIR / "config_frozen_v3_8.json")
    source_manifest.to_csv(artifact_dir / "source_manifest_v3_8.csv", index=False)
    daily_all = pd.concat([
        add_identity(daily_by_model[result.scenario.model], result) for result in results
    ], ignore_index=True, sort=False)
    trades = pd.concat([result.trades for result in results], ignore_index=True, sort=False)
    regimes = pd.concat([
        add_identity(model_b.signals, model_b), add_identity(model_j7.signals, model_j7),
        add_identity(model_k.signals, model_k),
    ], ignore_index=True, sort=False)
    tactical_events = tactical_event_frame(comparison_results)
    short_pair_audit = pd.concat(short_pairs.values(), ignore_index=True, sort=False)
    seven_pair_audit = pd.concat(seven_pairs.values(), ignore_index=True, sort=False)

    summary.to_csv(result_dir / "summary_v3_8.csv", index=False)
    daily_all.to_csv(result_dir / "daily_portfolio_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    regimes.to_csv(result_dir / "regime_log_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    k_overlay.to_csv(result_dir / "execution_overlay_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    j7_overlay.to_csv(result_dir / "j7_execution_overlay_replay_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    opportunity.to_csv(result_dir / "ahr_delay_opportunity_cost_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom_audit.to_csv(result_dir / "bottom_whipsaw_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom.to_csv(result_dir / "bottom_whipsaw_summary_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    event_audit.to_csv(result_dir / "event_drawdown_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    tactical.to_csv(result_dir / "tactical_statistics_v3_8.csv", index=False)
    tactical_events.to_csv(result_dir / "tactical_event_log_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    short_pair_audit.to_csv(result_dir / "short_whipsaw_pair_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    seven_pair_audit.to_csv(result_dir / "seven_day_whipsaw_pair_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fixed_dca.to_csv(result_dir / "fixed_dca_row_integrity_v3_8.csv", index=False)
    fsm.to_csv(result_dir / "fsm_audit_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    model_b.transitions.to_csv(result_dir / "fsm_transition_log_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    model_b.cycles.to_csv(result_dir / "cycle_log_v3_8.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    comparison.to_csv(result_dir / "model_comparison_v3_8.csv", index=False)

    write_json(artifact_dir / "data_contract_v3_8.json", data_contract)
    write_json(artifact_dir / "v3_1_replay_integrity_v3_8.json", replay_b)
    write_json(artifact_dir / "v3_7_j7_replay_integrity_v3_8.json", replay_j7)
    write_json(artifact_dir / "shadow_engine_replay_v3_8.json", shadow_replay)
    write_json(artifact_dir / "overlay_scope_audit_v3_8.json", scope)
    write_json(artifact_dir / "opportunity_cost_summary_v3_8.json", opportunity_stats)
    write_json(artifact_dir / "no_lookahead_audit_v3_8.json", integrity)
    write_json(artifact_dir / "execution_integrity_v3_8.json", {
        "pass": all_integrity, "prefix_invariance": prefix_checks,
        "fixed_dca_row_integrity": bool(fixed_dca["all_match"].all()),
        "fsm_audit": bool(fsm["legal_transition"].all()),
        "v3_1_replay": replay_b["pass"], "v3_7_j7_replay": replay_j7["pass"],
        "independent_shadow_replay": shadow_replay["pass"],
        "shadow_state_parity": parity_summary["pass"], "overlay_scope": scope["pass"],
        "original_order_violations": integrity["original_order_violations"],
        "same_timestamp_opposite_action_violations": integrity["same_timestamp_opposite_tactical_action_violations"],
    })
    write_json(artifact_dir / "promotion_verdict_v3_8.json", verdict)
    write_json(artifact_dir / "j_law_verdict_v3_8.json", j_law)
    (artifact_dir / "analysis_log_v3_8.md").write_text(
        "# V3.8 analysis log\n\nThe three-completed-close rule and all gates were frozen before formal execution. "
        "V3.1 B, the independent V3.1 shadow and V3.7 J7 were replayed before K. "
        "Forward returns were added only after K execution ended. A preliminary attempt was invalidated because its "
        "cooldown boundary allowed the third subsequent close instead of blocking it; the implementation and unit test "
        "were corrected to the already frozen three-close specification before this formal rerun. See "
        "`invalid_attempt_1_off_by_one.md`. No search, strategy-parameter change, or post-result gate change was performed.\n",
        encoding="utf-8",
    )

    result_map = {result.scenario.model: result for result in comparison_results}
    create_v38_figures(OUTPUT_DIR, daily_by_model, result_map, k_overlay, parity_audit)
    write_v38_report(
        OUTPUT_DIR, summary, tactical, comparison, verdict, j_law, bottom,
        event_audit, opportunity_stats, integrity, replay_b, replay_j7,
        shadow_replay, parity_summary, scope,
    )
    (OUTPUT_DIR / "README_V3_8.md").write_text(
        "# BTC+ETH Macro Hedge V3.8\n\nRun with `.venv\\Scripts\\python.exe run_backtest_v3_8.py`. "
        "Model K uses an independent original V3.1 shadow and delays only AHR buys for three newly completed daily closes.\n",
        encoding="utf-8",
    )
    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": ".venv\\Scripts\\python.exe run_backtest_v3_8.py",
        "python": sys.version, "platform": platform.platform(),
        "package_versions": {
            "numpy": np.__version__, "pandas": pd.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "config_sha256": sha256_file(config_path),
        "base_v31_config_sha256": sha256_file(base_path),
        "v3_7_config_sha256": sha256_file(v37_config_path),
        "v3_7_engine_sha256": sha256_file(v37_engine_path),
        "v3_8_engine_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v38_engine.py"),
        "v3_8_analysis_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v38_analysis.py"),
        "v3_8_reporting_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v38_reporting.py"),
        "v3_8_runner_sha256": sha256_file(PROJECT_DIR / "run_backtest_v3_8.py"),
        "formal_start": data_contract["formal_start_actual"],
        "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "v3_1_replay_integrity_pass": replay_b["pass"],
        "v3_7_j7_replay_integrity_pass": replay_j7["pass"],
        "shadow_engine_replay_pass": shadow_replay["pass"],
        "shadow_state_parity_pass": parity_summary["pass"],
        "overlay_scope_pass": scope["pass"],
        "fixed_dca_row_integrity_pass": bool(fixed_dca["all_match"].all()),
        "no_lookahead_pass": integrity["no_lookahead_pass"],
        "execution_integrity_pass": integrity["execution_integrity_pass"],
        "verdict": verdict,
        "output_sha256": output_hashes_v38(OUTPUT_DIR),
    }
    write_json(artifact_dir / "run_manifest_v3_8.json", manifest)
    print(summary[[
        "model", "final_portfolio_value", "twr_cagr", "maximum_drawdown",
        "calmar", "tactical_turnover", "tactical_event_count",
    ]].to_string(index=False))
    print(json.dumps(parity_summary, indent=2))
    print(json.dumps(opportunity_stats, indent=2))
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    print(
        f"NO_LOOK_AHEAD={integrity['no_lookahead_pass']} "
        f"EXECUTION_INTEGRITY={integrity['execution_integrity_pass']} "
        f"B_REPLAY={replay_b['pass']} J7_REPLAY={replay_j7['pass']} "
        f"SHADOW_PARITY={parity_summary['pass']}"
    )
    return 0 if all_integrity else 2


if __name__ == "__main__":
    raise SystemExit(main())
