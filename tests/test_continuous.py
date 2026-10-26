"""4단계 완료 기준: 포아송 수주로 몇 년을 이어 돌려도 메모리가 일정하다(ADR-004)."""

import gc

from sim import params
from sim.engine import Shipyard
from tests.helpers import fixed_orders

YEARS = 8  # 처음 3년은 워밍업(인도 없음), 그 뒤 5년을 본다


def test_state_is_freed_when_all_delivered():
    yard = Shipyard(fixed_orders(params.load()), seed=0, sink=lambda e: None)
    yard.run()
    assert yard.seq == {}


def test_memory_stays_flat_over_five_years():
    yard = Shipyard(params.load(), seed=0, sink=lambda e: None)
    start = yard.clock.at(0)
    events = []
    yard.sink = events.append
    objects, seq = [], []
    for year in range(1, YEARS + 1):
        events.clear()  # 이벤트는 sink로 나가 엔진에 남지 않는다
        until = start.replace(year=start.year + year).date().isoformat()
        yard.run(yard.clock.minute_of(until))
        gc.collect()
        objects.append(len(gc.get_objects()))
        seq.append(len(yard.seq))
    events.clear()
    steady = objects[3:]
    assert max(steady) <= 1.5 * objects[2], objects
    # 짓고 있는 배·블록만 남는다. 끝난 것을 지우지 않으면 해마다 블록 수천 개씩 쌓인다.
    assert max(seq) < 1000, seq
