"""schemas/의 이벤트 스키마로 검증기를 만든다."""

import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def validator() -> Draft202012Validator:
    envelope = _load(SCHEMAS_DIR / "envelope.json")
    payloads = [_load(p) for p in SCHEMAS_DIR.glob("payloads/*.json")]
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in [envelope, *payloads]
    )
    Draft202012Validator.check_schema(envelope)
    return Draft202012Validator(envelope, registry=registry)


@cache
def request_validator() -> Draft202012Validator:
    """재발행 요청 한 줄의 검증기(ADR-008)."""
    schema = _load(SCHEMAS_DIR / "replay_request.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)
