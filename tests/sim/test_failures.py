"""6단계 완료 기준: 설비 고장(ADR-010). 고장 중에는 작업이 멈추고, 고장 수는 설정대로다."""

import math
from collections import defaultdict
from datetime import datetime

import pytest

from sim import params
from sim.engine import Shipyard, simulate
from sim.io.schema import validator
from sim.params import ParamsError, check_failures
from tests.helpers import fixed, no_failures, single_hull_params

YEARS = 5
STATUS = "equipment.status_changed"


def _minutes(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp()) // 60


def _down_intervals(events) -> dict[str, list[tuple[int, int]]]:
    """설비별 (고장, 수리) 분. 끝까지 고치지 못했으면 수리는 무한대."""
    down, out = {}, defaultdict(list)
    for e in events:
        if e["event_type"] != STATUS:
            continue
        t = _minutes(e["occurred_at"])
        if e["payload"]["status"] == "down":
            down[e["resource_id"]] = t
        else:
            out[e["resource_id"]].append((down.pop(e["resource_id"]), t))
    for key, t in down.items():
        out[key].append((t, math.inf))
    return out


@pytest.fixture(scope="module")
def p():
    return params.load()


@pytest.fixture(scope="module")
def years(p):
    """시드 0으로 5년(포아송 수주)."""
    yard = Shipyard(p, seed=0, sink=None)
    events = []
    yard.sink = events.append
    start = yard.clock.at(0)
    yard.run(yard.clock.minute_of(start.replace(year=start.year + YEARS).date().isoformat()))
    return yard, events


def test_status_events_match_schema_and_alternate(p, years):
    yard, events = years
    v = validator()
    reasons = {
        f"{yard_r['prefix']}": set(p["variability"]["failures"][name]["reasons"])
        for name, yard_r in p["yard"]["resources"].items()
        if name in p["variability"]["failures"]
    }
    last = {}
    for e in (e for e in events if e["event_type"] == STATUS):
        assert v.is_valid(e), e
        assert e["source"] == "eam" and e["entity_key"] == e["resource_id"]
        status = e["payload"]["status"]
        assert status != last.get(e["resource_id"], "up"), "down과 up이 번갈아야 한다"
        last[e["resource_id"]] = status
        if status == "down":
            assert e["payload"]["reason"] in reasons[e["resource_id"].split("-")[0]]
        else:
            assert e["payload"]["reason"] is None


def test_only_configured_equipment_fails(p, years):
    yard, events = years
    failing = {e["resource_id"] for e in events if e["event_type"] == STATUS}
    assert failing == set(yard.equipment)
    assert not any(r.startswith("TRIAL-") for r in failing)  # 시운전 팀은 사람


def test_failure_count_matches_settings(p, years):
    """설비마다 고장 수 ≈ 기간 ÷ (평균 고장 간격 + 평균 수리 시간). 고장 수는 포아송에 가까우니
    종류별로 기댓값의 ±3σ(√기댓값의 3배) 안. 도크처럼 수가 적으면 ±10%로는 너무 빡빡하다."""
    _, events = years
    hours = YEARS * 365.25 * 24
    counts = defaultdict(int)
    for e in events:
        if e["event_type"] == STATUS and e["payload"]["status"] == "down":
            counts[e["resource_id"].split("-")[0]] += 1
    for name, f in p["variability"]["failures"].items():
        r = p["yard"]["resources"][name]
        mean_repair = f["repair_median_hours"] * math.exp(f["repair_sigma"] ** 2 / 2)
        expected = r["count"] * hours / (f["mtbf_hours"] + mean_repair)
        n = counts[r["prefix"]]
        assert abs(n - expected) < 3 * math.sqrt(expected), (name, n, expected)


def test_no_work_starts_or_ends_while_down(years):
    """탑재 완료(진수)는 뺀다. 짓기를 마친 뒤 주기관 대기(ADR-011)와 물 채우기를 거쳐
    나오는데, 둘 다 크레인 고장으로 멈추지 않는다(ADR-010 결정 4)."""
    _, events = years
    down = _down_intervals(events)
    checked = 0
    for e in events:
        if not e["event_type"].endswith(("process_started", "process_completed")):
            continue
        if e["event_type"] == "hull.process_completed" and e["process"] == "erection":
            continue
        t = _minutes(e["occurred_at"])
        for a, b in down.get(e["resource_id"], []):
            assert not a < t < b, (e["event_type"], e["resource_id"], e["occurred_at"])
        checked += 1
    assert checked > 10_000


def test_work_pauses_for_downtime():
    """같은 고정 시간 배 한 척: 고장이 있으면 작업 시간 = 고장 없는 작업 시간 + 겹친 고장 시간.
    도크 공정은 물 채우기 대기가 섞여 있어 뺀다."""

    def jobs(p):
        events = []
        simulate(p, seed=0, sink=events.append)
        start = {}
        out = {}
        for e in events:
            key = (e["entity_key"], e["process"])
            if e["event_type"].endswith("process_started"):
                start[key] = (_minutes(e["occurred_at"]), e["resource_id"])
            elif e["event_type"].endswith("process_completed") and e["process"] != "erection":
                out[key] = (*start[key], _minutes(e["occurred_at"]))
        return out, events

    p = single_hull_params()
    p["variability"]["failures"] = params.load()["variability"]["failures"]
    with_failures, events = jobs(p)
    without, _ = jobs(fixed(single_hull_params()))
    down = _down_intervals(events)
    paused = 0
    for key, (a, resource, b) in with_failures.items():
        overlap = sum(max(0, min(b, y) - max(a, x)) for x, y in down.get(resource, []))
        base_a, _, base_b = without[key]
        assert b - a - overlap == base_b - base_a, key
        paused += overlap > 0
    assert paused > 0, "고장과 겹친 작업이 하나는 있어야 시험이 된다"


def test_same_seed_same_failures(p):
    def failures(seed):
        events = []
        Shipyard(p, seed=seed, sink=events.append).run(60 * 24 * 365)
        return [e for e in events if e["event_type"] == STATUS]

    a = failures(1)
    assert a and a == failures(1)
    assert [e["occurred_at"] for e in a] != [e["occurred_at"] for e in failures(2)]


def test_no_failures_means_no_status_events():
    events = []
    simulate(no_failures(single_hull_params(vary=True)), seed=0, sink=events.append)
    assert events and not any(e["event_type"] == STATUS for e in events)


@pytest.mark.parametrize(
    "change",
    [
        {"mtbf_hours": 0},
        {"repair_sigma": 0},
        {"repair_max_hours": 1},  # 중앙값보다 작다
        {"reasons": []},
        {"reasons": [""]},
    ],
)
def test_bad_failure_params_rejected(p, change):
    f = {**p["variability"]["failures"]["dock"], **change}
    with pytest.raises(ParamsError):
        check_failures({"dock": f}, p["yard"]["resources"])


def test_failures_only_on_known_resources(p):
    with pytest.raises(ParamsError):
        check_failures({"crane": p["variability"]["failures"]["dock"]}, p["yard"]["resources"])
