from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.image as mpimg
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "v3_10"
ARTIFACTS = OUT / "artifacts"
ZIP_PATH = ROOT / "crypto_v3_10_complete.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )


def main() -> int:
    required = [
        OUT / "report" / "FINAL_REPORT_V3_10.md",
        *[OUT / "results" / name for name in [
            "summary_v3_10.csv", "daily_portfolio_v3_10.csv", "trade_log_v3_10.csv",
            "regime_log_v3_10.csv", "stage3_candidate_audit_v3_10.csv",
            "stage3_scope_integrity_v3_10.csv", "causal_lineage_audit_v3_10.csv",
            "bearish_rebreak_scope_audit_v3_10.csv", "event_drawdown_audit_v3_10.csv",
            "rolling_start_v3_10.csv", "v39_uplift_attribution_v3_10.csv",
            "stage4_integrity_v3_10.csv", "crash_integrity_v3_10.csv",
        ]],
        OUT / "artifacts" / "no_lookahead_audit_v3_10.json",
        OUT / "artifacts" / "run_manifest_v3_10.json",
        OUT / "config_frozen_v3_10.json",
        *[OUT / "figures" / f"{name}.png" for name in [
            "01_equity_curve_v3_10", "02_normalized_growth_v3_10",
            "03_drawdown_v3_10", "04_2023_stage3_isolation_v3_10",
            "05_2021_2022_safety_v3_10", "06_2025_2026_safety_v3_10",
            "07_rolling_start_v3_10",
        ]],
    ]
    missing = [
        str(path.relative_to(ROOT)) for path in required
        if not path.is_file() or path.stat().st_size == 0
    ]
    if missing:
        raise RuntimeError(f"Missing required V3.10 outputs: {missing}")

    junit_root = ElementTree.parse(ARTIFACTS / "pytest_v3_10.xml").getroot()
    tests = sum(int(node.attrib.get("tests", 0)) for node in junit_root.iter("testsuite"))
    failures = sum(
        int(node.attrib.get("failures", 0)) + int(node.attrib.get("errors", 0))
        for node in junit_root.iter("testsuite")
    )
    summary = pd.read_csv(OUT / "results" / "summary_v3_10.csv").set_index("model")
    verdict = json.loads((ARTIFACTS / "promotion_verdict_v3_10.json").read_text(encoding="utf-8"))
    no_look = json.loads((ARTIFACTS / "no_lookahead_audit_v3_10.json").read_text(encoding="utf-8"))
    manifest = json.loads((ARTIFACTS / "run_manifest_v3_10.json").read_text(encoding="utf-8"))
    candidates = pd.read_csv(OUT / "results" / "stage3_candidate_audit_v3_10.csv")
    scope = pd.read_csv(OUT / "results" / "stage3_scope_integrity_v3_10.csv")
    lineage = pd.read_csv(OUT / "results" / "causal_lineage_audit_v3_10.csv")
    rolling = pd.read_csv(OUT / "results" / "rolling_start_v3_10.csv")
    stage4 = pd.read_csv(OUT / "results" / "stage4_integrity_v3_10.csv")
    crash = pd.read_csv(OUT / "results" / "crash_integrity_v3_10.csv")
    dca = pd.read_csv(OUT / "results" / "fixed_dca_integrity_v3_10.csv")
    image_shapes = {
        path.name: list(mpimg.imread(path).shape)
        for path in required if path.suffix.lower() == ".png"
    }
    checks = {
        "required_outputs_nonempty": not missing,
        "pytest_105_passed": tests == 105 and failures == 0,
        "v31_replay_exact": abs(float(summary.loc["B", "final_portfolio_value"]) - 348746.8528777533) <= 1e-8,
        "v39_replay_exact": abs(float(summary.loc["P39", "final_portfolio_value"]) - 367407.5071839701) <= 1e-8,
        "q_final_exact": abs(float(summary.loc["Q", "final_portfolio_value"]) - 367407.5071839701) <= 1e-8,
        "p39_q_key_metrics_identical": all(
            np.isclose(summary.loc["P39", metric], summary.loc["Q", metric], atol=1e-12)
            for metric in ["final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]
        ),
        "all_integrity_pass": bool(all(manifest["integrity"].values())),
        "no_lookahead_pass": no_look["status"] == "PASS",
        "frozen_verdict_promoted": verdict["verdict"] == "A. V3.10 STAGE3 CONFIRMATION PROMOTED" and verdict["all_gates_pass"],
        "uplift_capture_100pct": np.isclose(verdict["uplift_capture_ratio"], 1.0, atol=1e-12),
        "candidate_counts_exact": len(candidates) == 2 and candidates["confirmed_or_rejected"].eq("REJECTED").all() and int(candidates["resolution_reason"].eq("SMA200_HARD_FAILURE").sum()) == 1,
        "stage3_scope_zero_unexpected": not scope["classification"].eq("UNEXPECTED_DIFFERENCE").any(),
        "causal_lineage_zero_unexplained": not lineage["classification"].eq("UNEXPLAINED_PATH_DIFFERENCE").any(),
        "all_fixed_dca_rows_match": bool(dca["all_match"].all()),
        "rolling_q_above_b_four_of_four": int((rolling["Q_final_portfolio_value"] > rolling["B_final_portfolio_value"]).sum()) == 4,
        "stage4_integrity": set(stage4["model"]) >= {"B", "P39", "Q"},
        "crash_integrity": bool(len(crash) and crash["q_not_suppressed"].all()),
        "seven_figures_rendered": len(image_shapes) == 7 and all(
            shape[0] >= 800 and shape[1] >= 1200 for shape in image_shapes.values()
        ),
    }
    checks = {name: bool(value) for name, value in checks.items()}
    qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "pytest_tests": tests,
        "pytest_failures_or_errors": failures,
        "figure_shapes": image_shapes,
    }
    write_json(ARTIFACTS / "qa_summary_v3_10.json", qa)
    if qa["status"] != "PASS":
        raise RuntimeError(f"V3.10 final QA failed: {checks}")

    manifest_path = ARTIFACTS / "run_manifest_v3_10.json"
    manifest["finalized_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["qa_status"] = qa["status"]
    manifest["pytest_tests"] = tests
    manifest["runner_sha256"] = sha256(ROOT / "run_backtest_v3_10.py")
    manifest["qa_finalize_sha256"] = sha256(ROOT / "qa_finalize_v3_10.py")
    manifest["v310_engine_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v310_engine.py")
    manifest["v310_analysis_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v310_analysis.py")
    manifest["v310_reporting_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v310_reporting.py")
    manifest["outputs_sha256"] = {
        path.relative_to(OUT).as_posix(): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    write_json(manifest_path, manifest)

    include = [
        ROOT / "run_backtest_v3_10.py", ROOT / "qa_finalize_v3_10.py",
        ROOT / "run_backtest_v3_9.py", ROOT / "run_backtest_v3_1.py",
        ROOT / "requirements.txt",
        ROOT / "config" / "config_frozen_v3_10.json",
        ROOT / "config" / "config_frozen_v3_9.json",
        ROOT / "config" / "config_frozen_v3_1.json",
        ROOT / "config" / "frozen_rules.json",
        ROOT / "design" / "V310_ASSUMPTIONS.md",
        ROOT / "design" / "best_skill_v3_10.md",
        ROOT / "tests" / "test_v310.py",
        ROOT / "tests" / "test_v310_outputs.py",
        ROOT / "v3_1" / "artifacts" / "source_manifest_v3_1.csv",
        ROOT / "v3_9" / "artifacts" / "run_manifest_v3_9.json",
        ROOT / "v3_9" / "results" / "summary_v3_9.csv",
        *sorted((ROOT / "v3_1" / "data" / "raw").glob("*.csv.gz")),
        *sorted((ROOT / "src" / "crypto_backtest").glob("*.py")),
        *sorted(path for path in OUT.rglob("*") if path.is_file()),
    ]
    seen: set[str] = set()
    with zipfile.ZipFile(
        ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
    ) as archive:
        for path in include:
            relative = path.relative_to(ROOT).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            archive.write(path, relative)
    digest = sha256(ZIP_PATH)
    (ROOT / "crypto_v3_10_complete.zip.sha256").write_text(
        f"{digest}  {ZIP_PATH.name}\n", encoding="utf-8",
    )
    print(json.dumps({
        "status": "PASS", "pytest_tests": tests,
        "zip": str(ZIP_PATH), "zip_sha256": digest, "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
