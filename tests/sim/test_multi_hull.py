"""2단계 완료 기준: 여러 척이 작업장을 다툰다. 도크 대기가 생기고, 작업장 용량은 넘지 않는다."""

from datetime import datetime

import pytest

from sim import params
from sim.engine import simulate
from sim.io.schema import validator
from tests.helpers import fixed_orders

P = fixed_orders(params.load())


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


def test_events_match_schema(events):
    """배·수주 이벤트는 모두, 블록 이벤트는 종류·공정마다 첫 이벤트와 20개에 하나씩 검사한다.
    모두 검사하면 2만 개에 9초쯤 걸린다. 한 척 테스트는 모두 검사한다."""
    v = validator()
    seen = set()
    for i, e in enumerate(events):
        kind = (e["event_type"], e["process"])
        if not e["event_type"].startswith("block.") or kind not in seen or i % 20 == 0:
            seen.add(kind)
            assert v.is_valid(e), e


def test_seq_is_gapless_per_entity(events):
    last = {}
    for e in events:
        assert e["seq"] == last.get(e["entity_key"], 0) + 1, e["entity_key"]
        last[e["entity_key"]] = e["seq"]


def test_capacity_never_exceeded(events):
    # 도크는 전체 자리 + 반쪽 자리(ADR-003)
    slots = {r["prefix"]: r.get("slots", 2) for r in P["yard"]["resources"].values()}
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
    """배는 계약 때 예약한 도크에 들어가고(ADR-004), 도크마다 먼저 온 배가 먼저 들어간다."""
    ready = _dock_ready(events)
    erection = _hulls(events, "hull.process_started", process="erection")
    for dock in {e["resource_id"] for e in erection.values()}:
        hulls = [h for h in ready if erection[h]["resource_id"] == dock]
        starts = [_t(erection[h]) for h in sorted(hulls, key=lambda h: (ready[h], h))]
        assert starts == sorted(starts), dock


def test_semi_tandem_docks_use_both_positions(events):
    positions = [
        e["payload"]["dock_position"]
        for e in events
        if e["event_type"] == "hull.process_started" and e["process"] == "erection"
    ]
    assert positions.count("half") >= 5 and positions.count("full") >= 1


def test_half_ship_moves_up_when_ship_ahead_launches(events):
    """반쪽 자리 배의 앞 배(같은 도크)는 반쪽 배가 들어온 뒤에 진수한다."""
    started = [
        e
        for e in events
        if e["event_type"] == "hull.process_started" and e["process"] == "erection"
    ]
    launched = _hulls(events, "hull.milestone_reached", milestone="launching")
    for e in started:
        if e["payload"]["dock_position"] != "half":
            continue
        ahead = [
            s
            for s in started
            if s["resource_id"] == e["resource_id"] and _t(s) <= _t(e) and s is not e
        ][-1]
        assert _t(launched[ahead["hull_no"]]) > _t(e)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_most_ships_meet_contract_date(seed):
    """납기는 도크 계획으로 잡는다(ADR-004). 흩어짐과 계획에 없는 대기로 몇 척은 늦는다."""
    out = []
    simulate(P, seed=seed, sink=out.append)
    promised = {
        e["hull_no"]: e["payload"]["contract_delivery_date"]
        for e in out
        if e["event_type"] == "order.contracted"
    }
    delivered = _hulls(out, "hull.milestone_reached", milestone="delivery")
    late = [h for h, e in delivered.items() if e["occurred_at"][:10] > promised[h]]
    assert len(late) <= len(promised) // 4


def test_ships_enter_planned_dock(events):
    """같은 도크의 배는 계약 순서대로 들어간다(도크 계획을 따른다)."""
    erection = _hulls(events, "hull.process_started", process="erection")
    order = [e["hull_no"] for e in events if e["event_type"] == "order.contracted"]
    for dock in {e["resource_id"] for e in erection.values()}:
        hulls = [h for h in order if erection[h]["resource_id"] == dock]
        assert [_t(erection[h]) for h in hulls] == sorted(_t(erection[h]) for h in hulls)
