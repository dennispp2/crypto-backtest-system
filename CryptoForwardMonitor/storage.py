from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from parser import ForwardStatus, status_to_history_row


HISTORY_FIELDS = [
    "run_local_time", "status_date", "label", "btc", "eth",
    "v310_state", "v310_stage", "v310_target_exposure", "v310_actual_exposure",
    "v310_exposure_gap", "v31_state", "v31_stage", "v31_target_exposure",
    "v31_actual_exposure", "shadow_actual_exposure_diff", "stage3_candidate", "crash",
    "ahr999", "today_tactical_action", "next_risk_trigger", "current_drawdown",
    "oos_elapsed", "resolved_candidates", "frozen_hash_status", "hash_warning",
    "current_evaluation", "model_return_code", "force_run",
]

CANDIDATE_FIELDS = [
    "candidate_id", "candidate_detected_time", "status_date", "btc", "eth", "state",
    "stage", "target_exposure", "actual_exposure", "ahr999", "drawdown",
    "tactical_action", "candidate_status", "resolution_status", "resolution_date",
]

DEFAULT_RUNNER_STATE = {
    "last_successful_local_date": None,
    "last_status_date": None,
    "last_run_time": None,
    "last_return_code": None,
    "last_refresh_time": None,
}


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class WriteResult:
    status: str
    path: Path


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except PermissionError as exc:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise StorageError(f"FILE LOCKED OR ACCESS DENIED: {path}") from exc
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _atomic_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except PermissionError as exc:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise StorageError(f"FILE LOCKED BY EXCEL OR ACCESS DENIED: {path}") from exc
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class MonitorStorage:
    """Deep module for all durable monitor data and audit artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.data_dir = self.root / "data"
        self.archive_dir = self.root / "archive"
        self.logs_dir = self.root / "logs"
        self.history_path = self.data_dir / "history_forward.csv"
        self.candidates_path = self.data_dir / "stage3_candidates.csv"
        self.state_path = self.data_dir / "runner_state.json"
        for directory in (self.data_dir, self.archive_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        if not self.history_path.exists():
            _atomic_csv(self.history_path, [], HISTORY_FIELDS)
        if not self.candidates_path.exists():
            _atomic_csv(self.candidates_path, [], CANDIDATE_FIELDS)
        if not self.state_path.exists():
            self.save_runner_state(DEFAULT_RUNNER_STATE)

    def load_history(self) -> list[dict[str, str]]:
        return _read_csv(self.history_path)

    def load_execution_summary(self) -> str:
        path = self.data_dir / "latest_execution_summary.txt"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def save_execution_summary(self, text: str, timestamp: datetime) -> None:
        path = self.archive_dir / "execution_summaries" / f"{timestamp.strftime('%Y%m%d_%H%M%S_%f')}.txt"
        _atomic_text(path, text)
        _atomic_text(self.data_dir / "latest_execution_summary.txt", text)

    def load_candidates(self) -> list[dict[str, str]]:
        return _read_csv(self.candidates_path)

    def load_runner_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return dict(DEFAULT_RUNNER_STATE)
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"RUNNER STATE ERROR: {exc}") from exc
        return {**DEFAULT_RUNNER_STATE, **payload}

    def save_runner_state(self, state: dict[str, Any]) -> None:
        _atomic_text(self.state_path, json.dumps({**DEFAULT_RUNNER_STATE, **state}, ensure_ascii=False, indent=2) + "\n")

    def write_history(
        self, status: ForwardStatus, *, run_local_time: datetime,
        model_return_code: int, force_run: bool,
    ) -> WriteResult:
        rows = self.load_history()
        if any(row.get("status_date") == status.status_utc_iso for row in rows):
            return WriteResult("ALREADY_EXISTS", self.history_path)
        rows.append(status_to_history_row(
            status, run_local_time=run_local_time,
            model_return_code=model_return_code, force_run=force_run,
        ))
        _atomic_csv(self.history_path, rows, HISTORY_FIELDS)
        return WriteResult("APPENDED", self.history_path)

    def record_candidate(self, status: ForwardStatus, detected_at: datetime) -> WriteResult:
        if status.stage3_candidate.strip().upper() == "NO":
            return WriteResult("NOT_APPLICABLE", self.candidates_path)
        seed = f"{status.status_utc_iso}|{status.v310_state}|{status.v310_stage}|{status.today_tactical_action}"
        candidate_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        rows = self.load_candidates()
        existing = next((row for row in rows if row.get("candidate_id") == candidate_id), None)
        if existing is not None:
            return WriteResult("ALREADY_EXISTS", self.candidates_path)
        rows.append({
            "candidate_id": candidate_id,
            "candidate_detected_time": detected_at.astimezone().isoformat(),
            "status_date": status.status_utc_iso,
            "btc": status.btc, "eth": status.eth,
            "state": status.v310_state, "stage": status.v310_stage,
            "target_exposure": status.v310_target_exposure,
            "actual_exposure": status.v310_actual_exposure,
            "ahr999": status.ahr999, "drawdown": status.current_drawdown,
            "tactical_action": status.today_tactical_action,
            "candidate_status": status.stage3_candidate,
            "resolution_status": "UNRESOLVED", "resolution_date": "",
        })
        _atomic_csv(self.candidates_path, rows, CANDIDATE_FIELDS)
        return WriteResult("APPENDED", self.candidates_path)

    def archive_status(self, source: Path, local_time: datetime) -> WriteResult:
        day_dir = self.archive_dir / local_time.astimezone().date().isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        target = day_dir / "DAILY_FORWARD_STATUS.md"
        if target.exists():
            stamp = local_time.astimezone().strftime("%H%M%S_%f")
            target = day_dir / f"DAILY_FORWARD_STATUS_{stamp}.md"
        try:
            shutil.copyfile(source, target)
        except PermissionError as exc:
            raise StorageError(f"ARCHIVE ACCESS DENIED: {target}") from exc
        if source.read_bytes() != target.read_bytes():
            raise StorageError(f"ARCHIVE VERIFICATION FAILED: {target}")
        return WriteResult("ARCHIVED", target)

    def write_log(self, local_time: datetime, content: str) -> Path:
        path = self.logs_dir / f"{local_time.astimezone().date().isoformat()}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(content.rstrip() + "\n\n")
        return path
