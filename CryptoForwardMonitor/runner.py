from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from config import AppConfig
from parser import ForwardStatus, StatusValidationError, parse_status_file
from storage import MonitorStorage, StorageError


class ModelRunInProgress(RuntimeError):
    pass


class CommandExecutor(Protocol):
    def __call__(self, command: str, workdir: Path, timeout: int) -> subprocess.CompletedProcess[str]: ...


def default_executor(command: str, workdir: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=workdir, shell=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def redact_secrets(text: str) -> str:
    patterns = [
        r"(?i)(api[_-]?key\s*[=:]\s*)\S+",
        r"(?i)(password\s*[=:]\s*)\S+",
        r"(?i)(secret\s*[=:]\s*)\S+",
        r"(?i)(token\s*[=:]\s*)\S+",
    ]
    result = text
    for pattern in patterns:
        result = re.sub(pattern, r"\1[REDACTED]", result)
    return result


@dataclass(frozen=True)
class RunResult:
    outcome: str
    completed: bool
    return_code: int | None
    force_run: bool
    message: str
    status: ForwardStatus | None = None
    history_result: str = "NOT_ATTEMPTED"
    archive_path: Path | None = None
    candidate_result: str = "NOT_ATTEMPTED"
    execution_summary: str = ""


class ModelExecutionLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self) -> "ModelExecutionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ModelRunInProgress("MODEL RUN ALREADY IN PROGRESS") from exc
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(f"pid={os.getpid()}\n")
        self.acquired = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class DailyModelRunner:
    """The only interface allowed to launch the frozen model command."""

    def __init__(
        self, config: AppConfig, storage: MonitorStorage,
        *, executor: CommandExecutor = default_executor,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.executor = executor
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.lock_path = storage.data_dir / "model_execution.lock"

    def run(self, *, force: bool = False) -> RunResult:
        start = self.clock().astimezone()
        with ModelExecutionLock(self.lock_path):
            state = self.storage.load_runner_state()
            today = start.date().isoformat()
            if (
                not force and self.config.one_normal_model_run_per_day
                and state.get("last_successful_local_date") == today
            ):
                return RunResult(
                    "TODAY_ALREADY_COMPLETED", False, state.get("last_return_code"), False,
                    "TODAY ALREADY COMPLETED",
                )
            if not self.config.model_command:
                return RunResult("CONFIG_ERROR", False, None, force, "MODEL COMMAND NOT CONFIGURED")
            if not self.config.model_workdir.is_dir():
                return RunResult("CONFIG_ERROR", False, None, force, "MODEL WORKDIR NOT FOUND")

            process: subprocess.CompletedProcess[str] | None = None
            status: ForwardStatus | None = None
            validation = "NOT_ATTEMPTED"
            history_result = "NOT_ATTEMPTED"
            archive_result = "NOT_ATTEMPTED"
            archive_path: Path | None = None
            candidate_result = "NOT_ATTEMPTED"
            error_text = ""
            try:
                process = self.executor(
                    self.config.model_command, self.config.model_workdir,
                    self.config.model_timeout_seconds,
                )
                if process.returncode != 0:
                    error_text = "MODEL EXECUTION FAILED"
                else:
                    status = parse_status_file(self.config.status_file)
                    validation = "PASS"
                    history = self.storage.write_history(
                        status, run_local_time=start, model_return_code=process.returncode,
                        force_run=force,
                    )
                    history_result = history.status
                    archive = self.storage.archive_status(self.config.status_file, self.clock())
                    archive_result = archive.status
                    archive_path = archive.path
                    candidate_result = self.storage.record_candidate(status, self.clock()).status
            except (FileNotFoundError, StatusValidationError, StorageError, subprocess.TimeoutExpired, OSError) as exc:
                error_text = str(exc)

            end = self.clock().astimezone()
            return_code = process.returncode if process is not None else None
            completed = bool(
                process is not None and return_code == 0 and validation == "PASS"
                and history_result in {"APPENDED", "ALREADY_EXISTS"}
                and archive_result == "ARCHIVED"
                and candidate_result in {"APPENDED", "ALREADY_EXISTS", "NOT_APPLICABLE"}
            )
            new_state = {
                **state,
                "last_status_date": status.status_utc_iso if status else state.get("last_status_date"),
                "last_run_time": end.isoformat(),
                "last_return_code": return_code,
            }
            if completed:
                new_state["last_successful_local_date"] = today
            self.storage.save_runner_state(new_state)

            modified = (
                datetime.fromtimestamp(self.config.status_file.stat().st_mtime).astimezone().isoformat()
                if self.config.status_file.exists() else "NOT_FOUND"
            )
            log = "\n".join([
                f"Run start time: {start.isoformat()}",
                f"Run end time: {end.isoformat()}",
                f"Run type: {'FORCE RUN' if force else 'NORMAL RUN'}",
                f"FORCE_RUN = {str(force).upper()}",
                f"model_command: {redact_secrets(self.config.model_command)}",
                f"model_workdir: {self.config.model_workdir}",
                f"return code: {return_code}",
                f"stdout:\n{redact_secrets(process.stdout if process else '')}",
                f"stderr:\n{redact_secrets(process.stderr if process else '')}",
                f"Status file path: {self.config.status_file}",
                f"Status modified time: {modified}",
                f"Validation result: {validation}",
                f"History write result: {history_result}",
                f"Archive result: {archive_result} {archive_path or ''}",
                f"Stage3 candidate result: {candidate_result}",
                f"Frozen Hash result: {status.frozen_hash_status if status else 'UNKNOWN'}",
                f"Errors: {error_text or 'NONE'}",
            ])
            self.storage.write_log(start, log)

            if completed:
                return RunResult(
                    "COMPLETED", True, return_code, force, "MODEL RUN COMPLETED",
                    status, history_result, archive_path, candidate_result,
                )
            return RunResult(
                "FAILED", False, return_code, force,
                error_text or "MODEL EXECUTION FAILED", status,
                history_result, archive_path, candidate_result,
            )
