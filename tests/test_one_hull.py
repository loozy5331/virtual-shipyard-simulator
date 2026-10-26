import hashlib
from datetime import datetime

import pytest

from sim import params
from sim.cli import main
from sim.clock import days
from sim.engine import simulate
from sim.schema import validator

MILESTONES = ["steel_cutting", "keel_laying", "launching", "delivery"]


@pytest.fixture(scope="module")
def events():
    out = []
    simulate(params.load(), seed=0, sink=out.append)
    return out


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_input_same_file(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    main(["--seed", "0", "--out", str(a)])
    main(["--seed", "0", "--out", str(b)])
    assert _sha256(a) == _sha256(b)


def test_every_event_matches_schema(events):
    v = validator()
    for e in events:
        errors = [err.message for err in v.iter_errors(e)]
        assert not errors, (e["event_type"], errors)


def test_milestones_in_order(events):
    reached = [
        (e["payload"]["milestone"], e["occurred_at"])
        for e in events
        if e["event_type"] == "hull.milestone_reached"
    ]
    assert [m for m, _ in reached] == MILESTONES
    times = [t for _, t in reached]
    assert times == sorted(times) and len(set(times)) == len(times)


def test_steel_cutting_is_first_fabrication_start(events):
    first_fab = next(e for e in events if e["event_type"] == "block.process_started")
    cut = next(e for e in events if e["event_type"] == "hull.milestone_reached")
    assert first_fab["process"] == "steel_fabrication"
    assert cut["payload"]["milestone"] == "steel_cutting"
    assert cut["occurred_at"] == first_fab["occurred_at"]


def test_seq_is_gapless_per_entity(events):
    seqs = {}
    for e in events:
        seqs.setdefault(e["entity_key"], []).append(e["seq"])
    for key, s in seqs.items():
        assert s == list(range(1, len(s) + 1)), key


def test_event_ids_unique(events):
    assert len({e["event_id"] for e in events}) == len(events)


def test_occurred_at_never_goes_back(events):
    times = [e["occurred_at"] for e in events]
    assert times == sorted(times)


def test_every_block_passes_block_processes(events):
    done = {}
    for e in events:
        if e["event_type"] == "block.process_completed":
            done.setdefault(e["block_id"], []).append(e["process"])
    assert len(done) == params.load()["ship_types"]["ship_types"]["lng_carrier"]["block_count"]
    assert all(p == ["steel_fabrication", "block_assembly"] for p in done.values())


def test_erection_waits_for_all_blocks(events):
    last_block = max(
        e["occurred_at"] for e in events if e["event_type"] == "block.process_completed"
    )
    erection = next(e for e in events if e["event_type"] == "hull.process_started")
    assert erection["process"] == "erection"
    assert erection["occurred_at"] >= last_block


def test_launch_to_delivery_matches_fixed_durations(events):
    d = params.load()["ship_types"]["ship_types"]["lng_carrier"]["durations_days"]
    at = {
        e["payload"]["milestone"]: e for e in events if e["event_type"] == "hull.milestone_reached"
    }
    gap = datetime.fromisoformat(at["delivery"]["occurred_at"]) - datetime.fromisoformat(
        at["launching"]["occurred_at"]
    )
    assert gap.total_seconds() / 60 == days(d["quay_outfitting"] + d["sea_trial"])


def test_delivered_before_contract_date(events):
    order = events[0]
    assert order["event_type"] == "order.contracted"
    delivery = [e for e in events if e["event_type"] == "hull.milestone_reached"][-1]
    assert delivery["occurred_at"][:10] <= order["payload"]["contract_delivery_date"]


SHIP_TYPES = ["lng_carrier", "vlcc", "container"]
# 마일스톤 기간표(도메인 모델 문서): 강재절단 → 착공, 착공 → 진수, 진수 → 인도 (개월)
PERIOD_MONTHS = {
    "lng_carrier": (4, 4, 7),
    "vlcc": (4, 3, 4),
    "container": (4, 4, 4),
}


def _run(ship_type):
    p = params.load()
    p["orders"]["orders"][0]["ship_type"] = ship_type
    out = []
    simulate(p, seed=0, sink=out.append)
    return p["ship_types"]["ship_types"][ship_type], out


@pytest.mark.parametrize("ship_type", SHIP_TYPES)
def test_block_count_and_weight_follow_ship_type(ship_type):
    ship, events = _run(ship_type)
    fab = [
        e
        for e in events
        if e["event_type"] == "block.process_started" and e["process"] == "steel_fabrication"
    ]
    assert len(fab) == ship["block_count"]
    weights = [e["payload"]["weight_t"] for e in fab]
    assert sum(weights) == pytest.approx(ship["steel_weight_t"], rel=0.001)
    mean = ship["steel_weight_t"] / ship["block_count"]
    assert min(weights) >= 0.6 * mean - 0.1 and max(weights) <= 1.4 * mean + 0.1


def test_bigger_ship_has_more_blocks():
    ships = params.load()["ship_types"]["ship_types"]
    assert ships["lng_carrier"]["block_count"] < ships["vlcc"]["block_count"]
    assert ships["vlcc"]["block_count"] < ships["container"]["block_count"]


@pytest.mark.parametrize("ship_type", SHIP_TYPES)
def test_milestone_periods_near_table(ship_type):
    _, events = _run(ship_type)
    at = {
        e["payload"]["milestone"]: datetime.fromisoformat(e["occurred_at"])
        for e in events
        if e["event_type"] == "hull.milestone_reached"
    }
    order = ["steel_cutting", "keel_laying", "launching", "delivery"]
    months = [(at[b] - at[a]).days / 30.4 for a, b in zip(order, order[1:], strict=False)]
    assert months == pytest.approx(PERIOD_MONTHS[ship_type], abs=0.5)
    delivery_date = at["delivery"].date().isoformat()
    assert delivery_date <= events[0]["payload"]["contract_delivery_date"]


@pytest.mark.parametrize("ship_type", SHIP_TYPES)
def test_assembly_slots_never_exceeded(ship_type):
    _, events = _run(ship_type)
    slots = params.load()["yard"]["resources"]["assembly"]["slots"]
    busy = {}
    for e in events:
        if e["process"] != "block_assembly":
            continue
        busy[e["resource_id"]] = busy.get(e["resource_id"], 0) + (
            1 if e["event_type"] == "block.process_started" else -1
        )
        assert busy[e["resource_id"]] <= slots
