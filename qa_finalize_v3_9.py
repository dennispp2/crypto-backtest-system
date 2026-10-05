from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import matplotlib.image as mpimg
import pandas as pd


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "v3_9"
ARTIFACTS = OUT / "artifacts"
ZIP_PATH = ROOT / "crypto_v3_9_complete.zip"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    required = [
        OUT / "report" / "FINAL_REPORT_V3_9.md",
        OUT / "results" / "summary_v3_9.csv",
        OUT / "results" / "daily_portfolio_v3_9.csv",
        OUT / "results" / "trade_log_v3_9.csv",
        OUT / "results" / "regime_log_v3_9.csv",
        OUT / "results" / "bull_persistence_blocked_sells_v3_9.csv",
        OUT / "results" / "bear_reentry_audit_v3_9.csv",
        OUT / "results" / "2021_peak_guard_audit_v3_9.csv",
        OUT / "results" / "event_drawdown_audit_v3_9.csv",
        OUT / "results" / "rolling_start_v3_9.csv",
        OUT / "artifacts" / "no_lookahead_audit_v3_9.json",
        OUT / "artifacts" / "run_manifest_v3_9.json",
        OUT / "config_frozen_v3_9.json",
        *[OUT / "figures" / f"{idx:02d}_{name}_v3_9.png" for idx, name in enumerate([
            "equity_curve", "normalized_growth", "drawdown", "bull_participation",
            "2021_2022_safety", "2025_2026_safety",
        ], start=1)],
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        raise RuntimeError(f"Missing required V3.9 outputs: {missing}")

    junit_root = ElementTree.parse(ARTIFACTS / "pytest_v3_9.xml").getroot()
    tests = sum(int(node.attrib.get("tests", 0)) for node in junit_root.iter("testsuite"))
    failures = sum(int(node.attrib.get("failures", 0)) + int(node.attrib.get("errors", 0)) for node in junit_root.iter("testsuite"))
    summary = pd.read_csv(OUT / "results" / "summary_v3_9.csv").set_index("model")
    verdict = json.loads((ARTIFACTS / "promotion_verdict_v3_9.json").read_text(encoding="utf-8"))
    no_look = json.loads((ARTIFACTS / "no_lookahead_audit_v3_9.json").read_text(encoding="utf-8"))
    drift = pd.read_csv(OUT / "results" / "bull_persistence_blocked_sells_v3_9.csv")
    stage4 = pd.read_csv(OUT / "results" / "stage4_integrity_v3_9.csv")
    crash = pd.read_csv(OUT / "results" / "crash_integrity_v3_9.csv")
    image_shapes = {
        path.name: list(mpimg.imread(path).shape)
        for path in required if path.suffix.lower() == ".png"
    }
    checks = {
        "required_outputs_nonempty": not missing,
        "pytest_95_passed": tests == 95 and failures == 0,
        "v31_replay_exact": abs(float(summary.loc["B", "final_portfolio_value"]) - 348746.8528777533) <= 1e-8,
        "no_lookahead_pass": no_look["status"] == "PASS",
        "verdict_is_frozen_option_d": verdict["verdict"] == "D. V3.9 REJECTED - NO MATERIAL BULL EDGE",
        "only_bull_edge_gates_failed": {key for key, value in verdict["checks"].items() if not value} == {
            "G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP",
            "G2_BULL_TIME_GTE85_DELTA_GTE_15PP",
        },
        "drift_audit_has_three_unblocked_shadow_events": len(drift) == 3 and not drift["blocked_or_executed"].eq("BLOCKED").any(),
        "stage4_integrity": set(stage4["model"]) >= {"B", "P"},
        "crash_integrity": bool(len(crash) and crash["not_suppressed"].all()),
        "six_figures_rendered": len(image_shapes) == 6 and all(shape[0] >= 800 and shape[1] >= 1200 for shape in image_shapes.values()),
    }
    qa = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "pytest_tests": tests,
        "pytest_failures_or_errors": failures,
        "figure_shapes": image_shapes,
    }
    write_json(ARTIFACTS / "qa_summary_v3_9.json", qa)
    if qa["status"] != "PASS":
        raise RuntimeError(f"V3.9 final QA failed: {checks}")

    manifest_path = ARTIFACTS / "run_manifest_v3_9.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["finalized_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["qa_status"] = qa["status"]
    manifest["pytest_tests"] = tests
    manifest["runner_sha256"] = sha256(ROOT / "run_backtest_v3_9.py")
    manifest["qa_finalize_sha256"] = sha256(ROOT / "qa_finalize_v3_9.py")
    manifest["v39_engine_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v39_engine.py")
    manifest["v39_analysis_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v39_analysis.py")
    manifest["v39_reporting_sha256"] = sha256(ROOT / "src" / "crypto_backtest" / "v39_reporting.py")
    manifest["outputs_sha256"] = {
        path.relative_to(OUT).as_posix(): sha256(path)
        for path in sorted(OUT.rglob("*"))
        if path.is_file() and path != manifest_path
    }
    write_json(manifest_path, manifest)

    include = [
        ROOT / "run_backtest_v3_9.py", ROOT / "qa_finalize_v3_9.py",
        ROOT / "run_backtest_v3_1.py",
        ROOT / "config" / "config_frozen_v3_9.json",
        ROOT / "config" / "config_frozen_v3_1.json",
        ROOT / "config" / "frozen_rules.json",
        ROOT / "design" / "V39_ASSUMPTIONS.md",
        ROOT / "design" / "best_skill_v3_9.md",
        ROOT / "tests" / "test_v39.py",
        ROOT / "tests" / "test_v39_outputs.py",
        ROOT / "v3_1" / "artifacts" / "source_manifest_v3_1.csv",
        *sorted((ROOT / "v3_1" / "data" / "raw").glob("*.csv.gz")),
        *sorted((ROOT / "src" / "crypto_backtest").glob("*.py")),
        *sorted(path for path in OUT.rglob("*") if path.is_file()),
    ]
    seen: set[str] = set()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in include:
            relative = path.relative_to(ROOT).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            archive.write(path, relative)
    digest = sha256(ZIP_PATH)
    (ROOT / "crypto_v3_9_complete.zip.sha256").write_text(
        f"{digest}  {ZIP_PATH.name}\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": "PASS", "pytest_tests": tests, "zip": str(ZIP_PATH),
        "zip_sha256": digest, "checks": checks,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
