"""7단계 완료 기준: 자재 발주·입고(ADR-011).
자재별 지연은 설정대로이고, 자재가 없으면 작업이 기다린다."""

import math
from collections import defaultdict
from datetime import datetime, timedelta

import pytest

from sim import params
from sim.engine import Shipyard, simulate
from sim.params import ParamsError, check_materials
from sim.schema import validator
from tests.helpers import fixed, single_hull_params

YEARS = 5
ORDERED, RECEIVED = "material.ordered", "material.received"


def _at(e) -> datetime:
    return datetime.fromisoformat(e["occurred_at"])


@pytest.fixture(scope="module")
def p():
    return params.load()


@pytest.fixture(scope="module")
def events(p):
    """시드 0으로 5년(포아송 수주)."""
    yard = Shipyard(p, seed=0, sink=None)
    out = []
    yard.sink = out.append
    start = yard.clock.at(0)
    yard.run(yard.clock.minute_of(start.replace(year=start.year + YEARS).date().isoformat()))
    return out


@pytest.fixture(scope="module")
def orders(events):
    """발주 번호 → {"ordered": 이벤트, "received": 이벤트 | 없음}."""
    out = defaultdict(dict)
    for e in events:
        if e["event_type"] == ORDERED:
            out[e["entity_key"]]["ordered"] = e
        elif e["event_type"] == RECEIVED:
            out[e["entity_key"]]["received"] = e
    return out


def test_order_then_receive_on_same_po(orders):
    v = validator()
    received = 0
    for po, o in orders.items():
        ordered = o["ordered"]
        assert v.is_valid(ordered) and ordered["seq"] == 1, ordered
        assert po.startswith(f"PO-{ordered['hull_no'][2:]}-")
        if "received" not in o:  # 5년 끝에 아직 오는 중
            continue
        r = o["received"]
        assert v.is_valid(r) and r["seq"] == 2, r
        assert _at(r) > _at(ordered)
        same = ("material", "quantity", "unit", "supplier")
        assert {k: r["payload"][k] for k in same} == {k: ordered["payload"][k] for k in same}
        assert r["process"] == ordered["process"] and r["hull_no"] == ordered["hull_no"]
        received += 1
    assert received > 300


def test_every_hull_orders_each_material(p, events, orders):
    """인도한 호선은 자재별 몫 수만큼 발주했고, 강재 몫을 합치면 선종의 강재 중량이다.
    짓는 중인 배는 아직 발주하지 않은 자재가 있다(필요일에 맞춰 발주하므로)."""
    materials = p["variability"]["materials"]
    ship_types = p["ship_types"]["ship_types"]
    by_hull = defaultdict(list)
    for o in orders.values():
        by_hull[o["ordered"]["hull_no"]].append(o["ordered"]["payload"])
    contracted = {e["hull_no"]: e for e in events if e["event_type"] == "order.contracted"}
    assert by_hull.keys() <= contracted.keys()
    delivered = {
        e["hull_no"]
        for e in events
        if e["event_type"] == "hull.milestone_reached" and e["payload"]["milestone"] == "delivery"
    }
    assert len(delivered) > 20
    for hull_no in delivered:
        payloads = by_hull[hull_no]
        counts = defaultdict(int)
        for x in payloads:
            counts[x["material"]] += 1
        assert counts == {name: m["lots"] for name, m in materials.items()}, hull_no
        steel = sum(x["quantity"] for x in payloads if x["material"] == "steel_plate")
        ship = ship_types[contracted[hull_no]["payload"]["ship_type"]]
        assert steel == pytest.approx(ship["steel_weight_t"], rel=0.01)


def test_ordered_with_promised_lead_time_before_need(p, orders, events):
    """발주는 계약 뒤, 약속일 = 발주일 + 약속 리드타임, 약속일 ≤ 필요일(여유가 있으면)."""
    materials = p["variability"]["materials"]
    contracted = {e["hull_no"]: _at(e) for e in events if e["event_type"] == "order.contracted"}
    for o in orders.values():
        e = o["ordered"]
        m = materials[e["payload"]["material"]]
        assert _at(e) >= contracted[e["hull_no"]]
        promised = (_at(e) + timedelta(days=m["lead_days"])).date().isoformat()
        assert e["payload"]["promised_date"] == promised
        assert e["payload"]["promised_date"] <= e["payload"]["need_date"]


def test_late_rate_and_delay_match_settings(p, orders):
    """자재별로 약속보다 늦은 비율 ≈ late_rate(±3σ). 늦음은 상한 안,
    제때는 약속에서 early_max_days 안."""
    materials = p["variability"]["materials"]
    late, total = defaultdict(int), defaultdict(int)
    for o in orders.values():
        if "received" not in o:
            continue
        name = o["ordered"]["payload"]["material"]
        m = materials[name]
        promised = _at(o["ordered"]) + timedelta(days=m["lead_days"])
        diff = (_at(o["received"]) - promised).total_seconds() / 86400
        total[name] += 1
        if diff > 0:
            late[name] += 1
            assert diff <= m["late_max_days"] + 1e-6, (name, diff)
        else:
            assert -diff <= m["early_max_days"] + 1e-6, (name, diff)
    for name, m in materials.items():
        n, rate = total[name], m["late_rate"]
        assert n > 50, name
        sigma = math.sqrt(n * rate * (1 - rate))
        assert abs(late[name] - n * rate) < 3 * sigma, (name, late[name], n * rate)


def test_work_waits_for_materials(p, events, orders):
    """강재 몫이 들어오기 전에 그 몫의 블록 가공이 시작되지 않고, 주기관 전에 진수하지 않고,
    배관·전선 전에 안벽 의장이 시작되지 않는다. 자재를 기다린 작업도 있다."""
    materials = p["variability"]["materials"]
    lots = materials["steel_plate"]["lots"]
    received = defaultdict(dict)  # 호선 → (자재, 몫) → 입고 시각
    for po in sorted(orders):
        o = orders[po]
        if "received" not in o:
            continue
        payload = o["ordered"]["payload"]
        hull = received[o["ordered"]["hull_no"]]
        lot = sum(1 for material, _ in hull if material == payload["material"])
        hull[(payload["material"], lot)] = _at(o["received"])
    blocks = {
        e["hull_no"]: e["payload"]["block_count"]
        for e in events
        if e["event_type"] == "order.contracted"
    }

    waited, checked = 0, 0
    for e in events:
        hull = received.get(e["hull_no"], {})
        if e["event_type"] == "block.process_started" and e["process"] == "steel_fabrication":
            i = int(e["block_id"][-3:]) - 1
            got = hull[("steel_plate", i * lots // blocks[e["hull_no"]])]
        elif (
            e["event_type"] == "hull.milestone_reached" and e["payload"]["milestone"] == "launching"
        ):
            got = hull[("main_engine", 0)]
        elif e["event_type"] == "hull.process_started" and e["process"] == "quay_outfitting":
            got = max(hull[("outfitting_pipe", 0)], hull[("electrical_cable", 0)])
        else:
            continue
        assert _at(e) >= got, (e["event_type"], e["entity_key"])
        waited += _at(e) == got
        checked += 1
    assert checked > 1000 and waited > 0


def test_on_time_materials_never_hold_work():
    """자재가 모두 약속일에 오면 여유 덕에 필요일 전에 들어와,
    고정 시간 일정이 자재 없이 돈 것과 같다."""

    def times(p):
        out = []
        simulate(p, seed=0, sink=out.append)
        return [
            (e["entity_key"], e["event_type"], e["occurred_at"])
            for e in out
            if not e["event_type"].startswith("material.")
        ]

    without = fixed(single_hull_params())
    without["variability"]["materials"] = {}
    assert times(fixed(single_hull_params())) == times(without)


def test_same_seed_same_orders(p):
    def run(seed):
        out = []
        Shipyard(p, seed=seed, sink=out.append).run(60 * 24 * 365 * 3)
        return [
            (e["entity_key"], e["occurred_at"], e["payload"])
            for e in out
            if e["event_type"].startswith("material.")
        ]

    a = run(1)
    assert a and a == run(1) and a != run(2)


@pytest.mark.parametrize(
    "change",
    [
        {"need": {"process": "painting", "at": "start"}},
        {"need": {"process": "steel_fabrication", "at": "middle"}},
        {"need": {"process": "steel_fabrication", "at": "end"}},  # 블록 공정은 착수 전에만
        {"need": {"process": "sea_trial", "at": "start"}, "lots": 2},  # 배 공정은 한 번에
        {"lots": 0},
        {"unit": "kg"},
        {"lead_days": 0},
        {"margin_days": -1},
        {"late_rate": 1},
        {"late_max_days": 1},  # 중앙값보다 작다
        {"suppliers": []},
    ],
)
def test_bad_material_params_rejected(p, change):
    m = {**p["variability"]["materials"]["steel_plate"], **change}
    with pytest.raises(ParamsError):
        check_materials({"steel_plate": m}, p["processes"]["processes"])
