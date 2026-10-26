"""params/*.yaml 읽기. 숫자는 모두 {value, grade} 꼴이어야 하고, 읽을 때 값만 남긴다.

소요 시간 분포는 params_version 이름의 파일(params/v0.yaml)에서 읽어 variability에 둔다."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
GRADES = {"출처", "맞춤", "가정"}
FILES = ("yard", "processes", "ship_types", "orders")
DISTS = {"lognormal"}


class ParamsError(ValueError):
    pass


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _has_number(value: Any) -> bool:
    if _is_number(value):
        return True
    if isinstance(value, list):
        return any(_has_number(v) for v in value)
    return False


def unwrap(node: Any, path: str = "") -> Any:
    """근거 등급이 붙은 숫자를 값으로 바꾼다. 등급 없는 숫자는 거절한다."""
    if isinstance(node, dict):
        if "grade" in node:
            if node["grade"] not in GRADES:
                raise ParamsError(f"{path}: 근거 등급은 {sorted(GRADES)} 중 하나")
            if "value" not in node:
                raise ParamsError(f"{path}: grade가 있으면 value도 있어야 한다")
            return node["value"]
        return {k: unwrap(v, f"{path}.{k}") for k, v in node.items()}
    if isinstance(node, list):
        if _has_number(node):
            raise ParamsError(f"{path}: 숫자 목록에 근거 등급이 없다")
        return [unwrap(v, f"{path}[{i}]") for i, v in enumerate(node)]
    if _is_number(node):
        raise ParamsError(f"{path}: 숫자 {node}에 근거 등급이 없다")
    return node


def _read(params_dir: Path, name: str) -> Any:
    raw = yaml.safe_load((params_dir / f"{name}.yaml").read_text(encoding="utf-8"))
    return unwrap(raw, name)


def check_variability(variability: dict[str, Any], processes: list[dict[str, Any]]) -> None:
    """공정마다 분포가 하나씩 있고, 아는 분포에 cv ≥ 0인지."""
    duration = variability["duration"]
    ids = [p["id"] for p in processes]
    if sorted(duration) != sorted(ids):
        raise ParamsError(f"variability.duration: 공정 {ids}마다 하나씩 있어야 한다")
    for pid, d in duration.items():
        if d["dist"] not in DISTS:
            raise ParamsError(f"variability.duration.{pid}: 분포는 {sorted(DISTS)} 중 하나")
        if not d["cv"] >= 0:
            raise ParamsError(f"variability.duration.{pid}: cv는 0 이상")


def check_noise(noise: dict[str, Any]) -> None:
    """비율은 0 이상 1 미만, 시간은 0보다 크다. 늦음의 중앙값은 상한보다 작다."""
    delay = noise["delay"]
    for name, rate in [
        ("drop_rate", noise["drop_rate"]),
        ("duplicate_rate", noise["duplicate_rate"]),
        ("delay.late_rate", delay["late_rate"]),
    ]:
        if not 0 <= rate < 1:
            raise ParamsError(f"noise.{name}: 0 이상 1 미만")
    for name in ["median_seconds", "sigma", "late_median_minutes", "late_sigma", "max_hours"]:
        if not delay[name] > 0:
            raise ParamsError(f"noise.delay.{name}: 0보다 커야 한다")
    if not noise["retry_median_seconds"] > 0:
        raise ParamsError("noise.retry_median_seconds: 0보다 커야 한다")
    if delay["late_median_minutes"] >= delay["max_hours"] * 60:
        raise ParamsError("noise.delay: 늦음의 중앙값이 상한보다 크다")


def load(params_dir: Path = PARAMS_DIR) -> dict[str, Any]:
    params = {name: _read(params_dir, name) for name in FILES}
    version = params["yard"]["params_version"]
    variability = _read(params_dir, version)
    if variability["params_version"] != version:
        raise ParamsError(f"{version}.yaml: params_version이 {version}이 아니다")
    check_variability(variability, params["processes"]["processes"])
    check_noise(variability["noise"])
    if not variability["manifest"]["lookback_days"] >= 1:
        raise ParamsError("manifest.lookback_days: 1 이상")
    params["variability"] = variability
    return params
