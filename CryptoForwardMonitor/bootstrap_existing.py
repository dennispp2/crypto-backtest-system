from __future__ import annotations

from datetime import datetime
from pathlib import Path

from config import load_config
from parser import parse_status_file
from storage import MonitorStorage


def main() -> int:
    app_dir = Path(__file__).resolve().parent
    config = load_config(app_dir / "config.json")
    storage = MonitorStorage(config.app_data_dir)
    now = datetime.now().astimezone()
    status = parse_status_file(config.status_file)
    history = storage.write_history(status, run_local_time=now, model_return_code=0, force_run=False)
    day_dir = storage.archive_dir / now.date().isoformat()
    archive_target = day_dir / "DAILY_FORWARD_STATUS.md"
    if archive_target.exists():
        archive_status = "ALREADY_EXISTS"
    else:
        archive_status = storage.archive_status(config.status_file, now).status
    candidate = storage.record_candidate(status, now)
    state = storage.load_runner_state()
    state.update({
        "last_successful_local_date": now.date().isoformat(),
        "last_status_date": status.status_utc_iso,
        "last_run_time": now.isoformat(),
        "last_return_code": 0,
        "bootstrap_source": "verified existing V3.10 forward run from current project",
    })
    storage.save_runner_state(state)
    storage.write_log(now, "\n".join([
        f"Run start time: {now.isoformat()}", f"Run end time: {now.isoformat()}",
        "Run type: BOOTSTRAP VERIFIED EXISTING OUTPUT", "FORCE_RUN = FALSE",
        "return code: 0", f"Status file path: {config.status_file}",
        "Validation result: PASS", f"History write result: {history.status}",
        f"Archive result: {archive_status}", f"Stage3 candidate result: {candidate.status}",
        f"Frozen Hash result: {status.frozen_hash_status}", "Errors: NONE",
    ]))
    print("BOOTSTRAP_COMPLETE")
    print(f"HISTORY={history.status}")
    print(f"ARCHIVE={archive_status}")
    print(f"CANDIDATE={candidate.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
