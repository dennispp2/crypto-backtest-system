from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from run_backtest_v3_7 import load_formal_data
from run_v31_necessity_audit import (
    OUTPUT_DIR,
    PROJECT_DIR,
    _counterfactual,
    _curve,
    _diagnostic_verdict,
    _direct_answers,
    _environment_summary,
    _shadow_history,
    _window_summary,
    load_json,
    output_hashes,
    scenario,
    snapshot_reproduction_code,
    write_json,
)
from crypto_backtest.data import sha256_file
from crypto_backtest.v31_engine import run_v31_backtest
from crypto_backtest.v31_necessity_reporting import create_necessity_figures, write_necessity_report


def _timestamps(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    return frame


def main() -> int:
    result_dir = OUTPUT_DIR / "results"
    artifact_dir = OUTPUT_DIR / "artifacts"
    snapshot_reproduction_code()
    audit_rules = load_json(PROJECT_DIR / "config" / "config_frozen_v31_necessity_audit.json")
    rules = load_json(PROJECT_DIR / audit_rules["baseline"]["config_path"])
    source_manifest = pd.read_csv(PROJECT_DIR / audit_rules["data"]["source_manifest"])
    frame, _, _ = load_formal_data(rules, source_manifest)
    model_a = run_v31_backtest(frame, rules, scenario("A", rules))
    baseline = run_v31_backtest(frame, rules, scenario("B", rules), model_a=model_a)

    events = _timestamps(pd.read_csv(result_dir / "leave_one_event_out_results.csv"), [
        "timestamp", "signal_date", "next_major_transition_date", "first_resync_date",
    ])
    clusters = _timestamps(pd.read_csv(result_dir / "leave_one_cluster_out_results.csv"), [
        "start_date", "end_date", "next_major_transition_date", "first_resync_date",
    ])
    signal_summary = pd.read_csv(result_dir / "signal_type_contribution_summary.csv")
    whipsaw = pd.read_csv(result_dir / "whipsaw_contribution_summary.csv")
    interaction = pd.read_csv(result_dir / "interaction_audit.csv")
    redundant_basket = pd.read_csv(result_dir / "robust_redundant_basket_cf.csv")
    harmful_basket = pd.read_csv(result_dir / "robust_harmful_basket_cf.csv")
    baseline_replay = pd.read_csv(result_dir / "baseline_v31_replay.csv")
    integrity = load_json(artifact_dir / "baseline_and_counterfactual_integrity.json")

    event_cache: dict[int, pd.DataFrame] = {}
    chosen_events = pd.concat([
        events.loc[events["classification"].eq("RETURN_ESSENTIAL")].nlargest(5, "final_wealth_contribution"),
        events.loc[events["classification"].eq("HARMFUL")].nsmallest(5, "final_wealth_contribution"),
    ]).drop_duplicates("tactical_event_id")
    for event_id in chosen_events["tactical_event_id"].astype(int):
        cf, _ = _counterfactual(frame, rules, model_a, baseline, [event_id])
        event_cache[event_id] = _curve(cf)

    redundant_clusters = clusters.loc[clusters["classification"].eq("REDUNDANT")].copy()
    if len(redundant_clusters) < 5:
        redundant_clusters = clusters.assign(
            _distance=clusters["final_wealth_contribution"].abs()
        ).nsmallest(5, "_distance")
    else:
        redundant_clusters = redundant_clusters.nlargest(5, "turnover_saved")
    cluster_cache: dict[int, pd.DataFrame] = {}
    for row in redundant_clusters.itertuples(index=False):
        cluster_id = int(row.cluster_id)
        deleted = [int(value) for value in str(row.events_inside).split("|")]
        cf, _ = _counterfactual(frame, rules, model_a, baseline, deleted)
        cluster_cache[cluster_id] = _curve(cf)

    create_necessity_figures(
        OUTPUT_DIR, baseline.history, events, clusters, signal_summary, event_cache, cluster_cache,
    )
    event_master = _timestamps(pd.read_csv(result_dir / "v31_tactical_events_master.csv"), ["timestamp", "signal_date"])
    _shadow_history(baseline, event_master).to_csv(
        result_dir / "v31_frozen_shadow_history.csv", index=False
    )

    environment = _environment_summary(events)
    environment.to_csv(result_dir / "ahr_environment_summary.csv", index=False)
    cross_year = events[[
        "timestamp", "signal_type", "tactical_event_id", "final_wealth_contribution",
        "dd_protection_contribution_pp",
    ]].copy()
    cross_year["year"] = cross_year["timestamp"].dt.year
    cross_year.groupby(
        ["year", "signal_type"], as_index=False
    ).agg(
        event_count=("tactical_event_id", "size"),
        positive_raw_fraction=("final_wealth_contribution", lambda x: float((x > 0).mean())),
        median_final_contribution=("final_wealth_contribution", "median"),
        mean_final_contribution=("final_wealth_contribution", "mean"),
        median_dd_protection_pp=("dd_protection_contribution_pp", "median"),
    ).to_csv(result_dir / "cross_year_signal_contribution_summary.csv", index=False)
    ahr = events.loc[events["signal_type"].eq("AHR_VALUE_BUY")]
    pd.DataFrame([{
        "event_count": len(ahr),
        "positive_raw_contribution_count": int(ahr["final_wealth_contribution"].gt(0).sum()),
        "negative_raw_contribution_count": int(ahr["final_wealth_contribution"].lt(0).sum()),
        "median_final_contribution": float(ahr["final_wealth_contribution"].median()),
        "mean_final_contribution": float(ahr["final_wealth_contribution"].mean()),
        "median_btc_forward_return_30d": float(ahr["ex_post_btc_forward_return_30d"].median()),
        "median_btc_forward_return_60d": float(ahr["ex_post_btc_forward_return_60d"].median()),
        "median_dd_protection_pp": float(ahr["dd_protection_contribution_pp"].median()),
        "forward_outcome_usage": "EX_POST_DIAGNOSTIC_ONLY",
    }]).to_csv(result_dir / "ahr_value_buy_overall_summary.csv", index=False)
    window_rows = []
    for name, (start, end) in audit_rules["audit_windows"].items():
        subset, counts = _window_summary(events, start, end)
        window_rows.append({
            "window": name, "start": start, "end": end, "event_count": len(subset),
            "positive_raw_contribution": int(subset["final_wealth_contribution"].gt(0).sum()),
            "negative_raw_contribution": int(subset["final_wealth_contribution"].lt(0).sum()),
            **counts,
        })
    pd.DataFrame(window_rows).to_csv(result_dir / "audit_window_classification_summary.csv", index=False)

    verdict = _diagnostic_verdict(
        events, baseline_replay.iloc[0].to_dict(), redundant_basket, harmful_basket,
        interaction, audit_rules,
    )
    answers = _direct_answers(
        True, events, clusters, environment, whipsaw, redundant_basket, verdict, audit_rules,
    )
    write_json(artifact_dir / "j_law_diagnostic_verdict.json", verdict)
    write_json(artifact_dir / "direct_answers_1_to_30.json", {
        str(index): value for index, value in enumerate(answers, 1)
    })
    interaction_summary = {
        "candidate_clusters": len(set(interaction["cluster_a"]) | set(interaction["cluster_b"])),
        "pair_count": len(interaction),
        "maximum_absolute_interaction_usd": float(interaction["interaction_final_contribution"].abs().max()),
        "maximum_absolute_interaction_fraction": float(interaction["interaction_fraction_of_baseline"].abs().max()),
    }
    write_necessity_report(
        OUTPUT_DIR, baseline_replay, events, clusters, signal_summary, whipsaw,
        interaction_summary, redundant_basket, harmful_basket, answers, verdict, integrity,
    )

    required_csv = [
        "baseline_v31_replay.csv", "v31_tactical_events_master.csv",
        "leave_one_event_out_results.csv", "leave_one_cluster_out_results.csv",
        "round_trip_clusters.csv", "interaction_audit.csv",
        "signal_type_contribution_summary.csv", "ahr_value_buy_contribution.csv",
        "risk_sell_contribution.csv", "right_side_contribution.csv",
        "new_bull_contribution.csv", "whipsaw_contribution_summary.csv",
        "top_return_contributing_events.csv", "most_harmful_events.csv",
        "most_redundant_events.csv", "risk_essential_events.csv",
        "round_trip_necessity_ranking.csv", "robust_redundant_basket_cf.csv",
        "robust_harmful_basket_cf.csv",
    ]
    required_png = [f"{index:02d}_{name}.png" for index, name in [
        (1, "2022_trade_necessity_map"), (2, "2026_trade_necessity_map"),
        (3, "full_trade_necessity_map"), (4, "event_contribution_distribution"),
        (5, "turnover_vs_contribution"), (6, "risk_return_contribution"),
        (7, "signal_type_contribution"),
    ]]
    qa = {
        "required_csv_present_and_nonempty": all((result_dir / name).stat().st_size > 0 for name in required_csv),
        "required_png_present_and_nonempty": all((OUTPUT_DIR / "figures" / name).stat().st_size > 0 for name in required_png),
        "direct_answer_count": len(answers),
        "loeo_rows": len(events),
        "loco_rows": len(clusters),
        "interaction_rows": len(interaction),
        "classification_partition_rows": int(events["classification"].notna().sum()),
        "reporting_selection_fixed": True,
    }
    qa["pass"] = bool(
        qa["required_csv_present_and_nonempty"] and qa["required_png_present_and_nonempty"]
        and qa["direct_answer_count"] == 30 and qa["loeo_rows"] == 106
        and qa["interaction_rows"] <= 45 and qa["classification_partition_rows"] == 106
    )
    write_json(artifact_dir / "final_output_qa.json", qa)
    if not qa["pass"]:
        raise RuntimeError(f"Final output QA failed: {qa}")

    manifest_path = artifact_dir / "run_manifest_v31_necessity_audit.json"
    manifest = load_json(manifest_path)
    manifest.update({
        "qa_finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        "runner_sha256": sha256_file(PROJECT_DIR / "run_v31_necessity_audit.py"),
        "qa_finalizer_sha256": sha256_file(PROJECT_DIR / "qa_finalize_v31_necessity_audit.py"),
        "audit_test_sha256": sha256_file(PROJECT_DIR / "tests" / "test_v31_necessity_audit.py"),
        "reporting_code_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v31_necessity_reporting.py"),
        "final_output_qa": qa,
        "output_sha256": output_hashes(OUTPUT_DIR),
    })
    write_json(manifest_path, manifest)
    archive = shutil.make_archive(
        str(PROJECT_DIR / "crypto_v31_necessity_audit_complete"), "zip",
        root_dir=OUTPUT_DIR.parent, base_dir=OUTPUT_DIR.name,
    )
    Path(archive + ".sha256").write_text(
        f"{sha256_file(Path(archive))}  {Path(archive).name}\n", encoding="utf-8"
    )
    print(f"FINAL QA PASS: {verdict['Final Verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
