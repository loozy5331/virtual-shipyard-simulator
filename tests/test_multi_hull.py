"""2단계 완료 기준: 여러 척이 작업장을 다툰다. 도크 대기가 생기고, 작업장 용량은 넘지 않는다."""

from datetime import datetime

import pytest

from sim import params
from sim.engine import simulate
from sim.schema import validator

P = params.load()


@pytest.fixture(scope="module")
def events():
    out = []
    simulate(P, seed=0, sink=out.append)
    return out


def _t(e):
    return datetime.fromisoformat(e["occurred_at"])


def _hulls(events, event_type, process=None, milestone=None):
    return {
        e["hull_no"]: e
        for e in events
        if e["event_type"] == event_type
        and (process is None or e["process"] == process)
        and (milestone is None or e["payload"].get("milestone") == milestone)
    }


def test_every_order_is_delivered(events):
    contracted = _hulls(events, "order.contracted")
    delivered = _hulls(events, "hull.milestone_reached", milestone="delivery")
    assert len(contracted) == sum(c["count"] for c in P["orders"]["contracts"])
    assert delivered.keys() == contracted.keys()


def test_order_mix_matches_annual_plan(events):
    mix = {}
    for e in _hulls(events, "order.contracted").values():
        mix[e["payload"]["ship_type"]] = mix.get(e["payload"]["ship_type"], 0) + 1
    assert mix == P["yard"]["annual_plan"]["mix"]


def test_every_event_matches_schema(events):
    v = validator()
    assert all(v.is_valid(e) for e in events)


def test_seq_is_gapless_per_entity(events):
    last = {}
    for e in events:
        assert e["seq"] == last.get(e["entity_key"], 0) + 1, e["entity_key"]
        last[e["entity_key"]] = e["seq"]


def test_capacity_never_exceeded(events):
    slots = {r["prefix"]: r["slots"] for r in P["yard"]["resources"].values()}
    busy = {}
    for e in events:
        if not e["event_type"].endswith(("process_started", "process_completed")):
            continue
        rid = e["resource_id"]
        busy[rid] = busy.get(rid, 0) + (1 if e["event_type"].endswith("started") else -1)
        assert 0 <= busy[rid] <= slots[rid.split("-")[0]], rid
    assert all(n == 0 for n in busy.values())


def _dock_ready(events):
    """배마다 마지막 블록이 조립을 마친 시각 = 도크를 기다리기 시작한 시각."""
    ready = {}
    for e in events:
        if e["event_type"] == "block.process_completed" and e["process"] == "block_assembly":
            ready[e["hull_no"]] = max(ready.get(e["hull_no"], _t(e)), _t(e))
    return ready


def test_dock_wait_happens(events):
    ready = _dock_ready(events)
    erection = _hulls(events, "hull.process_started", process="erection")
    waits = [(_t(erection[h]) - ready[h]).days for h in ready]
    assert sum(w > 0 for w in waits) >= 2
    assert max(waits) >= 14


def test_dock_is_first_come_first_served(events):
    ready = _dock_ready(events)
    erection = _hulls(events, "hull.process_started", process="erection")
    by_ready = sorted(ready, key=lambda h: (ready[h], h))
    starts = [_t(erection[h]) for h in by_ready]
    assert starts == sorted(starts)
