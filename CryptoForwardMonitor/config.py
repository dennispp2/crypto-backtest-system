from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AppConfig:
    model_command: str
    model_workdir: Path
    status_file: Path
    app_data_dir: Path
    v310_portfolio_file: Path = Path()
    v31_portfolio_file: Path = Path()
    market_refresh_seconds: int = 30
    auto_refresh: bool = True
    one_normal_model_run_per_day: bool = True
    market_timeout_seconds: float = 5.0
    model_timeout_seconds: int = 1800

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], config_path: Path) -> "AppConfig":
        base = config_path.resolve().parent

        def path_value(key: str, default: str = "") -> Path:
            raw = str(payload.get(key, default)).strip()
            if not raw:
                return Path()
            expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
            return expanded if expanded.is_absolute() else (base / expanded).resolve()

        seconds = int(payload.get("market_refresh_seconds", 30))
        if seconds not in {10, 30, 60, 300}:
            raise ConfigError("market_refresh_seconds must be 10, 30, 60, or 300")
        timeout = float(payload.get("market_timeout_seconds", 5.0))
        if timeout <= 0 or timeout > 30:
            raise ConfigError("market_timeout_seconds must be in (0, 30]")
        model_workdir = path_value("model_workdir")
        v310_portfolio_file = path_value("v310_portfolio_file")
        if not str(payload.get("v310_portfolio_file", "")).strip() and model_workdir:
            v310_portfolio_file = model_workdir / "v3_10_forward" / "forward_v310_portfolio.csv"
        v31_portfolio_file = path_value("v31_portfolio_file")
        if not str(payload.get("v31_portfolio_file", "")).strip() and model_workdir:
            v31_portfolio_file = model_workdir / "v3_10_forward" / "forward_v31_shadow_portfolio.csv"
        return cls(
            model_command=str(payload.get("model_command", "")).strip(),
            model_workdir=model_workdir,
            status_file=path_value("status_file"),
            app_data_dir=path_value("app_data_dir", "data"),
            v310_portfolio_file=v310_portfolio_file,
            v31_portfolio_file=v31_portfolio_file,
            market_refresh_seconds=seconds,
            auto_refresh=bool(payload.get("auto_refresh", True)),
            one_normal_model_run_per_day=bool(payload.get("one_normal_model_run_per_day", True)),
            market_timeout_seconds=timeout,
            model_timeout_seconds=int(payload.get("model_timeout_seconds", 1800)),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("model_workdir", "status_file", "app_data_dir", "v310_portfolio_file", "v31_portfolio_file"):
            payload[key] = str(payload[key])
        return payload


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ConfigError(f"CONFIG FILE NOT FOUND: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"CONFIG ERROR: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("CONFIG ERROR: root must be an object")
    return AppConfig.from_mapping(payload, path)


def save_config(path: Path, config: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config.to_mapping(), ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
