"""3단계 흔들림: 소요 시간은 시드로 재현되는 로그정규 분포에서 뽑는다."""

import hashlib
import json
import random
from datetime import datetime, timedelta
from statistics import mean, stdev

import pytest

from sim import params
from sim.engine import Shipyard, lognormal_factor, simulate
from tests.helpers import single_hull_params


def _run(seed, vary=True):
    out = []
    simulate(single_hull_params(vary=vary), seed=seed, sink=out.append)
    return out


def _digest(events):
    return hashlib.sha256(json.dumps(events, ensure_ascii=False).encode()).hexdigest()


def _times(events):
    return [(e["event_type"], e["entity_key"], e["occurred_at"]) for e in events]


def test_same_seed_same_events():
    assert _digest(_run(1)) == _digest(_run(1))


def test_different_seed_different_times():
    assert _times(_run(1)) != _times(_run(2))


def test_planned_end_uses_mean_duration():
    """계획 종료일은 평균 시간으로 잡는다. 실제 종료는 그 앞뒤로 흩어진다."""
    durations = params.load()["ship_types"]["ship_types"]["lng_carrier"]["durations_days"]
    events = _run(1)
    for e in events:
        if e["event_type"] != "hull.process_started":
            continue
        start = datetime.fromisoformat(e["occurred_at"])
        planned = start + timedelta(days=durations[e["process"]])
        assert e["payload"]["planned_end"] == planned.date().isoformat()


def test_draw_is_per_entity():
    """같은 (시드, 개체, 공정)이면 같은 시간. 다른 블록이 몇 번 뽑혔는지와 무관하다."""
    yard = Shipyard(params.load(), seed=3, sink=lambda e: None)
    a = yard.draw("H-2601-B001", "block_assembly", 10_000)
    yard.draw("H-2601-B002", "block_assembly", 10_000)
    assert yard.draw("H-2601-B001", "block_assembly", 10_000) == a
    assert yard.draw("H-2601-B002", "block_assembly", 10_000) != a


def test_lognormal_factor_mean_and_cv():
    rng = random.Random(0)
    xs = [lognormal_factor(rng, 0.3) for _ in range(20_000)]
    assert mean(xs) == pytest.approx(1, abs=0.01)
    assert stdev(xs) == pytest.approx(0.3, abs=0.01)
    assert min(xs) > 0
    assert lognormal_factor(rng, 0) == 1


@pytest.mark.parametrize("process", ["steel_fabrication", "block_assembly"])
def test_block_factors_follow_cv(process):
    """블록 공수(MH) 배수 = 소요 시간 배수. 한 척 블록 170개의 평균과 흩어짐이 설정대로."""

    def work_hours(events):
        return {
            e["block_id"]: e["payload"]["work_hours"]
            for e in events
            if e["event_type"] == "block.process_completed" and e["process"] == process
        }

    varied, fixed = work_hours(_run(1)), work_hours(_run(1, vary=False))
    factors = [varied[b] / fixed[b] for b in fixed]
    cv = params.load()["variability"]["duration"][process]["cv"]
    assert mean(factors) == pytest.approx(1, abs=3 * cv / len(factors) ** 0.5)
    assert stdev(factors) == pytest.approx(cv, rel=0.25)
