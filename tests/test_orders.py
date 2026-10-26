import random
from statistics import mean

import pytest

from sim import params
from sim.clock import Clock, days
from sim.engine import Shipyard, simulate
from sim.orders import HullNumbers, hulls, next_contract
from tests.helpers import fixed

CLOCK = Clock("2026-11-02T08:00:00+09:00")
ORDERS = {"start_lag_days": 760, "delivery_buffer_days": 30}


def test_contract_expands_to_hulls():
    c = {"ship_type": "vlcc", "owner": "가", "count": 3}
    hs = hulls(ORDERS, c, 0, HullNumbers(CLOCK))
    assert [h["hull_no"] for h in hs] == ["H-2601", "H-2602", "H-2603"]
    assert {h["ship_type"] for h in hs} == {"vlcc"}
    assert hs[0]["min_start_lag"] == days(760)


def test_hull_numbers_restart_each_contract_year():
    numbers = HullNumbers(CLOCK)
    assert [numbers.next(days(d)) for d in (0, 30, 70, 80)] == [
        "H-2601",
        "H-2602",
        "H-2701",  # 2027-01-11
        "H-2702",
    ]


def test_poisson_arrivals_follow_params():
    p = params.load()
    arrivals, mix = p["orders"]["arrivals"], p["yard"]["annual_plan"]["mix"]
    rng = random.Random(0)
    draws = [next_contract(rng, arrivals, mix) for _ in range(5000)]
    gaps = [g for g, _ in draws]
    assert mean(gaps) == pytest.approx(365 / arrivals["contracts_per_year"], rel=0.05)
    counts = [c["count"] for _, c in draws]
    assert set(counts) == {1, 2, 3, 4} and mean(counts) == pytest.approx(2.5, rel=0.05)
    ships = {}
    for _, c in draws:
        ships[c["ship_type"]] = ships.get(c["ship_type"], 0) + 1
        assert c["owner"] in arrivals["owners"][c["ship_type"]]
    total = sum(mix.values())
    for k, n in mix.items():
        assert ships[k] / len(draws) == pytest.approx(n / total, abs=0.03)


def _contracts(p, seed, until="2029-11-02"):
    out = []
    yard = Shipyard(p, seed, out.append)
    yard.run(yard.clock.minute_of(until))
    return [
        (e["occurred_at"], e["hull_no"], e["payload"]["ship_type"], e["payload"]["owner"])
        for e in out
        if e["event_type"] == "order.contracted"
    ]


def test_orders_keep_coming_after_fixed_list():
    p = params.load()
    got = _contracts(p, 0)
    fixed = sum(c["count"] for c in p["orders"]["contracts"])
    assert len(got) > fixed + 2 * 20  # 첫해 고정 목록 + 2년 넘게 연 20척 이상
    assert got[fixed][0] > got[fixed - 1][0]


def test_orders_reproducible_and_independent_of_durations():
    """수주는 수주 전용 난수 흐름이라, 공정 시간 분포를 바꿔도 그대로다."""
    a = _contracts(params.load(), 1)
    assert a == _contracts(params.load(), 1)
    assert a != _contracts(params.load(), 2)
    assert a == _contracts(fixed(params.load()), 1)


def test_endless_orders_need_until():
    with pytest.raises(ValueError):
        simulate(params.load(), seed=0, sink=lambda e: None)
