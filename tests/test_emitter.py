"""5단계: 방출기는 정답 로그에 지연·중복·누락을 설정 비율대로 섞고, 도착 순서로 낸다(ADR-005)."""

from datetime import datetime

import pytest

from emitter.cli import main as emit_main
from emitter.noise import Emitter, fate
from sim import params
from sim.cli import main as sim_main
from sim.engine import simulate
from sim.reader import read_events
from sim.schema import validator
from tests.helpers import fixed_orders

NOISE = params.load()["variability"]["noise"]


@pytest.fixture(scope="module")
def truth():
    out = []
    simulate(fixed_orders(params.load()), seed=0, sink=out.append)
    return out


def _emit(events, seed=0, noise=NOISE):
    out = []
    emitter = Emitter(noise, seed, lambda e, date: out.append((e, date)))
    for e in events:
        emitter(e)
    emitter.close()
    return out


@pytest.fixture(scope="module")
def emitted(truth):
    return _emit(truth)


def _t(iso):
    return datetime.fromisoformat(iso)


def test_same_seed_same_output(truth, emitted):
    assert _emit(truth) == emitted
    assert _emit(truth, seed=1) != emitted


def test_noise_is_per_event(truth, emitted):
    """앞 절반만 방출해도 그 이벤트들의 노이즈는 같다(조각으로 나눠 읽어도 같다)."""
    half = truth[: len(truth) // 2]
    ids = {e["event_id"] for e in half}
    part = [(e["event_id"], e["emitted_at"]) for e, _ in _emit(half)]
    whole = [(e["event_id"], e["emitted_at"]) for e, _ in emitted if e["event_id"] in ids]
    assert sorted(part) == sorted(whole)


def test_only_emitted_at_changes(truth, emitted):
    by_id = {e["event_id"]: e for e in truth}
    v = validator()
    for i, (e, _) in enumerate(emitted):
        t = by_id[e["event_id"]]
        assert {k: x for k, x in e.items() if k != "emitted_at"} == {
            k: x for k, x in t.items() if k != "emitted_at"
        }
        delay = (_t(e["emitted_at"]) - _t(e["occurred_at"])).total_seconds()
        assert 0 <= delay <= NOISE["delay"]["max_hours"] * 3600
        if i % 50 == 0:
            assert v.is_valid(e)


def test_arrival_order_and_dates(emitted):
    """도착은 emitted_at 순서(중복 사본은 더 늦게), 날짜는 도착 날짜."""
    arrivals = [date for _, date in emitted]
    assert arrivals == sorted(arrivals)
    for e, date in emitted:
        assert date >= e["emitted_at"][:10]


def test_rates_match_config(truth, emitted):
    n = len(truth)
    ids = [e["event_id"] for e, _ in emitted]
    dropped = n - len(set(ids))
    duplicated = len(ids) - len(set(ids))
    late = sum(
        1 for e, _ in emitted if (_t(e["emitted_at"]) - _t(e["occurred_at"])).total_seconds() > 600
    )
    assert dropped / n == pytest.approx(NOISE["drop_rate"], rel=0.3)
    assert duplicated / n == pytest.approx(NOISE["duplicate_rate"], rel=0.3)
    assert late / (n + duplicated) == pytest.approx(NOISE["delay"]["late_rate"], rel=0.2)


def test_some_events_arrive_out_of_order(emitted):
    """같은 개체의 seq가 뒤바뀌어 도착하는 일이 있다(지연의 결과)."""
    last, swapped = {}, 0
    for e, _ in emitted:
        key = e["entity_key"]
        if e["seq"] < last.get(key, 0):
            swapped += 1
        last[key] = max(last.get(key, 0), e["seq"])
    assert swapped > 0


def test_fate_without_noise_is_clean():
    clean = {
        **NOISE,
        "drop_rate": 0,
        "duplicate_rate": 0,
        "delay": {**NOISE["delay"], "late_rate": 0, "median_seconds": 1e-9},
    }
    f = fate(clean, 0, "x")
    assert (f.dropped, f.delay, f.retry) == (False, 0, None)


def test_cli_truth_dir_to_emitted_dir(tmp_path):
    truth_dir, emitted_dir = tmp_path / "truth", tmp_path / "emitted"
    sim_main(["--seed", "0", "--until", "2029-06-01", "--out-dir", str(truth_dir)])
    emit_main(["--truth", str(truth_dir), "--seed", "0", "--out-dir", str(emitted_dir)])
    truth = list(read_events(truth_dir))
    emitted = list(read_events(emitted_dir))
    assert {e["event_id"] for e in emitted} <= {e["event_id"] for e in truth}
    assert 0.9 * len(truth) < len(emitted) < 1.1 * len(truth)
    for part in emitted_dir.glob("dt=*/part-0.jsonl"):
        day = part.parent.name.removeprefix("dt=")
        assert all(e["emitted_at"][:10] <= day for e in read_events(part))
