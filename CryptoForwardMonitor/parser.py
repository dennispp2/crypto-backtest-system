from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class StatusValidationError(ValueError):
    def __init__(self, missing_fields: list[str], message: str | None = None) -> None:
        self.missing_fields = missing_fields
        detail = message or f"Missing core fields: {', '.join(missing_fields)}"
        super().__init__(f"VALIDATION FAILED: {detail}")


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _number(value: str) -> float:
    cleaned = _clean(value).replace("$", "").replace(",", "").replace("%", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", cleaned)
    if not match:
        raise ValueError(f"Not a number: {value}")
    return float(match.group(0))


def _integer(value: str) -> int:
    return int(round(_number(value)))


@dataclass(frozen=True)
class ForwardStatus:
    label: str
    status_date: datetime
    btc: float | None
    eth: float | None
    v310_state: str
    v310_stage: int
    v310_target_exposure: float
    v310_actual_exposure: float
    v31_state: str
    v31_stage: int | None
    v31_target_exposure: float | None
    v31_actual_exposure: float | None
    stage3_candidate: str
    crash: str
    ahr999: float | None
    today_tactical_action: str
    next_risk_trigger: str
    current_drawdown: float | None
    oos_elapsed: float | None
    resolved_candidates: int | None
    frozen_hash_status: str
    current_evaluation: str
    raw_text: str

    @property
    def v310_exposure_gap(self) -> float:
        return self.v310_target_exposure - self.v310_actual_exposure

    @property
    def shadow_actual_exposure_diff(self) -> float | None:
        if self.v31_actual_exposure is None:
            return None
        return self.v310_actual_exposure - self.v31_actual_exposure

    @property
    def evaluation_eligible(self) -> bool:
        return bool(
            self.oos_elapsed is not None and self.oos_elapsed >= 180
            and self.resolved_candidates is not None and self.resolved_candidates >= 3
        )

    @property
    def status_utc_iso(self) -> str:
        return self.status_date.isoformat()

    @property
    def status_local(self) -> datetime:
        return self.status_date.astimezone()


_ALIASES = {
    "label": "label",
    "date": "date",
    "btc": "btc",
    "eth": "eth",
    "stage3 candidate": "stage3_candidate",
    "crash": "crash",
    "ahr999": "ahr999",
    "today tactical action": "today_tactical_action",
    "next risk trigger": "next_risk_trigger",
    "current drawdown": "current_drawdown",
    "oos elapsed": "oos_elapsed",
    "resolved candidates": "resolved_candidates",
    "frozen hash status": "frozen_hash_status",
    "current evaluation": "current_evaluation",
}


def _field_map(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = re.sub(r"^\s*[-*+]\s*", "", raw.strip())
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = re.sub(r"\s+", " ", key.strip().lower())
        if normalized.startswith("v3.10 state / stage / target / actual exposure"):
            values["v310_combined"] = value.strip()
        elif normalized.startswith("v3.1 shadow state / stage / target / actual exposure"):
            values["v31_combined"] = value.strip()
        elif normalized in _ALIASES:
            values[_ALIASES[normalized]] = value.strip()
    return values


def _combined(value: str, expected: int) -> list[str]:
    parts = [_clean(item) for item in re.split(r"\s*/\s*", value)]
    if len(parts) < expected:
        raise ValueError(f"Expected {expected} combined fields, got {len(parts)}")
    return parts[:expected]


def parse_status(text: str, expected_label: str = "FORWARD_PAPER_ONLY") -> ForwardStatus:
    values = _field_map(text)
    required = ["label", "date", "v310_combined", "frozen_hash_status", "current_evaluation"]
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise StatusValidationError(missing)
    label = _clean(values["label"])
    if label != expected_label:
        raise StatusValidationError(["label"], f"Label must be {expected_label}, got {label}")
    try:
        status_date = datetime.fromisoformat(_clean(values["date"]).replace("Z", "+00:00"))
        if status_date.tzinfo is None:
            raise ValueError("Status Date must include timezone")
        q = _combined(values["v310_combined"], 4)
        b = _combined(values["v31_combined"], 4) if values.get("v31_combined") else ["", "", "", ""]
        status = ForwardStatus(
            label=label,
            status_date=status_date,
            btc=_number(values["btc"]) if values.get("btc") else None,
            eth=_number(values["eth"]) if values.get("eth") else None,
            v310_state=q[0], v310_stage=_integer(q[1]),
            v310_target_exposure=_number(q[2]), v310_actual_exposure=_number(q[3]),
            v31_state=b[0], v31_stage=_integer(b[1]) if b[1] else None,
            v31_target_exposure=_number(b[2]) if b[2] else None,
            v31_actual_exposure=_number(b[3]) if b[3] else None,
            stage3_candidate=_clean(values.get("stage3_candidate", "NO")),
            crash=_clean(values.get("crash", "NO")),
            ahr999=_number(values["ahr999"]) if values.get("ahr999") else None,
            today_tactical_action=_clean(values.get("today_tactical_action", "")),
            next_risk_trigger=_clean(values.get("next_risk_trigger", "")),
            current_drawdown=_number(values["current_drawdown"]) if values.get("current_drawdown") else None,
            oos_elapsed=_number(values["oos_elapsed"]) if values.get("oos_elapsed") else None,
            resolved_candidates=_integer(values["resolved_candidates"]) if values.get("resolved_candidates") else None,
            frozen_hash_status=_clean(values["frozen_hash_status"]).upper(),
            current_evaluation=_clean(values["current_evaluation"]), raw_text=text,
        )
    except (TypeError, ValueError) as exc:
        raise StatusValidationError(["malformed_core_field"], str(exc)) from exc
    if not status.v310_state:
        raise StatusValidationError(["v310_state"])
    return status


def parse_status_file(path: Path, expected_label: str = "FORWARD_PAPER_ONLY") -> ForwardStatus:
    if not path.exists():
        raise FileNotFoundError(f"STATUS FILE NOT FOUND: {path}")
    return parse_status(path.read_text(encoding="utf-8-sig"), expected_label=expected_label)


def status_to_history_row(
    status: ForwardStatus, *, run_local_time: datetime, model_return_code: int, force_run: bool,
) -> dict[str, Any]:
    return {
        "run_local_time": run_local_time.astimezone().isoformat(),
        "status_date": status.status_utc_iso,
        "label": status.label,
        "btc": status.btc,
        "eth": status.eth,
        "v310_state": status.v310_state,
        "v310_stage": status.v310_stage,
        "v310_target_exposure": status.v310_target_exposure,
        "v310_actual_exposure": status.v310_actual_exposure,
        "v310_exposure_gap": status.v310_exposure_gap,
        "v31_state": status.v31_state,
        "v31_stage": status.v31_stage,
        "v31_target_exposure": status.v31_target_exposure,
        "v31_actual_exposure": status.v31_actual_exposure,
        "shadow_actual_exposure_diff": status.shadow_actual_exposure_diff,
        "stage3_candidate": status.stage3_candidate,
        "crash": status.crash,
        "ahr999": status.ahr999,
        "today_tactical_action": status.today_tactical_action,
        "next_risk_trigger": status.next_risk_trigger,
        "current_drawdown": status.current_drawdown,
        "oos_elapsed": status.oos_elapsed,
        "resolved_candidates": status.resolved_candidates,
        "frozen_hash_status": status.frozen_hash_status,
        "hash_warning": status.frozen_hash_status != "PASS",
        "current_evaluation": status.current_evaluation,
        "model_return_code": model_return_code,
        "force_run": force_run,
    }

