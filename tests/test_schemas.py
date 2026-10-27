import copy
import json
from pathlib import Path

import pytest

from sim.schema import request_validator, validator

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
VALID = sorted((SCHEMAS / "examples" / "valid").glob("*.json"))
EVENT_TYPES = [
    "order.contracted",
    "block.process_started",
    "block.process_completed",
    "hull.process_started",
    "hull.process_completed",
    "hull.milestone_reached",
    "equipment.status_changed",
    "material.ordered",
    "material.received",
    "system.manifest_published",
]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


VALIDATOR = validator()


def _example(event_type: str) -> dict:
    return _load(SCHEMAS / "examples" / "valid" / f"{event_type}.json")


def test_every_event_type_has_payload_schema_and_example():
    assert sorted(p.stem for p in SCHEMAS.glob("payloads/*.json")) == sorted(EVENT_TYPES)
    assert sorted(p.stem for p in VALID) == sorted(EVENT_TYPES)
    assert _load(SCHEMAS / "envelope.json")["properties"]["event_type"]["enum"] == EVENT_TYPES


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_examples_pass(path):
    event = _load(path)
    assert event["event_type"] == path.stem
    errors = list(VALIDATOR.iter_errors(event))
    assert not errors, [e.message for e in errors]


def _broken(event_type: str, change) -> dict:
    event = copy.deepcopy(_example(event_type))
    change(event)
    return event


INVALID = {
    "missing_field": _broken("order.contracted", lambda e: e.pop("run_id")),
    "extra_field": _broken("order.contracted", lambda e: e.update(price=1)),
    "uuid_v4": _broken(
        "order.contracted", lambda e: e.update(event_id="0192f3a0-0001-4abc-8def-0123456789ab")
    ),
    "utc_time": _broken(
        "block.process_started", lambda e: e.update(occurred_at="2027-01-04T08:00:00Z")
    ),
    "seq_zero": _broken("block.process_started", lambda e: e.update(seq=0)),
    "bad_hull_no": _broken("hull.process_started", lambda e: e.update(hull_no="2601")),
    "bad_process": _broken("hull.process_started", lambda e: e.update(process="painting")),
    "wrong_source": _broken("order.contracted", lambda e: e.update(source="mes")),
    "block_event_without_block": _broken(
        "block.process_completed", lambda e: e.update(block_id=None)
    ),
    "hull_event_with_block": _broken(
        "hull.milestone_reached", lambda e: e.update(block_id="H-2601-B001")
    ),
    "equipment_with_hull": _broken(
        "equipment.status_changed", lambda e: e.update(hull_no="H-2601")
    ),
    "payload_missing": _broken("block.process_started", lambda e: e["payload"].pop("weight_t")),
    "payload_extra": _broken("hull.process_completed", lambda e: e["payload"].update(note="x")),
    "bad_milestone": _broken(
        "hull.milestone_reached", lambda e: e["payload"].update(milestone="naming")
    ),
    "bad_ship_type": _broken("order.contracted", lambda e: e["payload"].update(ship_type="bulk")),
    "bad_dock_position": _broken(
        "hull.process_started", lambda e: e["payload"].update(dock_position="middle")
    ),
    "bad_status": _broken(
        "equipment.status_changed", lambda e: e["payload"].update(status="broken")
    ),
    "manifest_with_hull": _broken(
        "system.manifest_published", lambda e: e.update(hull_no="H-2601")
    ),
    "manifest_empty": _broken(
        "system.manifest_published", lambda e: e["payload"].update(last_seq={})
    ),
    "unknown_event_type": _broken(
        "hull.process_completed", lambda e: e.update(event_type="hull.x")
    ),
}


@pytest.mark.parametrize("name", INVALID)
def test_invalid_examples_fail(name):
    assert not VALIDATOR.is_valid(INVALID[name])


def test_replay_request_schema():
    v = request_validator()
    assert v.is_valid({"entity_key": "H-2601-B006", "seq": 3})
    for bad in [
        {"entity_key": "H-2601"},
        {"seq": 1},
        {"entity_key": "H-2601", "seq": 0},
        {"entity_key": "", "seq": 1},
        {"entity_key": "H-2601", "seq": 1, "event_id": "x"},
    ]:
        assert not v.is_valid(bad), bad
