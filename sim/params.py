"""params/*.yaml 읽기. 숫자는 모두 {value, grade} 꼴이어야 하고, 읽을 때 값만 남긴다."""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
PARAMS_DIR = ROOT / "params"
GRADES = {"출처", "맞춤", "가정"}
FILES = ("yard", "processes", "ship_types", "orders")


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


def load(params_dir: Path = PARAMS_DIR) -> dict[str, Any]:
    params = {}
    for name in FILES:
        raw = yaml.safe_load((params_dir / f"{name}.yaml").read_text(encoding="utf-8"))
        params[name] = unwrap(raw, name)
    return params
