"""Validated cost-cache reading and optional post-run offline reconstruction."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess


def read_costs(path: Path, *, model: str, portfolio_hash: str, timestamp: str,
               units: tuple[float, float]) -> tuple[float | None, float | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema_version"] != 1 or data["method"] != "inherited_moving_average_including_buy_costs":
            raise ValueError("成本口徑無法辨識")
        saved = data["models"][model]
        if saved["portfolio_sha256"] != portfolio_hash or saved["timestamp"] != timestamp:
            raise ValueError("成本資料尚未同步最新持倉")
        averages = []
        for asset, actual_units in zip(("BTC", "ETH"), units):
            item = saved["assets"][asset]
            quantity, cost = float(item["units"]), float(item["cost_usd"])
            if not all(math.isfinite(n) and n >= 0 for n in (quantity, cost)):
                raise ValueError("成本數值無效")
            if not math.isclose(quantity, actual_units, rel_tol=1e-10, abs_tol=1e-9):
                raise ValueError("成本數量與持倉不符")
            if quantity <= 1e-12:
                if cost > 1e-8 or item["average_cost"] is not None:
                    raise ValueError("空倉仍有成本")
                averages.append(None)
            else:
                average = float(item["average_cost"])
                if not math.isfinite(average) or average <= 0 or not math.isclose(average, cost / quantity, rel_tol=1e-10):
                    raise ValueError("成本均價驗證失敗")
                averages.append(average)
        return *averages, "已核對｜含買入費用及歷史承接成本"
    except FileNotFoundError:
        return None, None, "均價尚無資料；每日模型完成後會核對更新"
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        return None, None, f"均價暫不可用：{exc}"


def update_cost_view(config) -> str:
    """Called only after explicit model execution, never by price refresh."""
    project = getattr(config, "model_workdir", None)
    if project is None:
        return "均價未更新：缺少專案位置"
    python = project / ".venv/Scripts/python.exe"
    script = project / "CryptoForwardMonitor/cost_basis_replay.py"
    if not python.is_file() or not script.is_file():
        return "均價未更新：缺少本機成本核對工具"
    output = config.app_data_dir / "data/average_cost.json"
    try:
        result = subprocess.run(
            [str(python), str(script), "--project", str(project), "--output", str(output)],
            cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            return "均價核對失敗，未採用新均價：" + (result.stderr or result.stdout)[-800:]
        return "持倉成本均價已核對更新（含歷史承接成本）。"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"均價核對未完成（不影響原模型結果）：{exc}"
