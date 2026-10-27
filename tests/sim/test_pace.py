"""재생 속도와 상한(ADR-013): 가상 시각을 실제 시간에 맞추고, 정답 로그가 상한에 닿으면 멈춘다."""

import pytest

from sim import params
from sim.cli import main as sim_main
from sim.engine import Shipyard
from sim.io.reader import read_events
from sim.pace import Pacer
from tests.helpers import fixed_orders


class FakeTime:
    def __init__(self):
        self.now, self.slept, self.idles = 100.0, [], 0

    def clock(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_pacer_waits_for_real_time_after_lead():
    t = FakeTime()
    pacer = Pacer(
        1440,
        lead=86400,
        idle=lambda: setattr(t, "idles", t.idles + 1),
        clock=t.clock,
        sleep=t.sleep,
    )
    pacer(0)  # 기준
    pacer(86400)  # 하루 앞은 lead 안이라 기다리지 않는다
    assert t.slept == []
    pacer(2 * 86400)  # 이틀째: lead 뒤 하루 = 실제 60초
    assert t.slept == [pytest.approx(60)] and t.idles == 1
    t.now += 120  # 실제 시간이 앞서 있으면 기다리지 않는다
    pacer(3 * 86400)
    assert len(t.slept) == 1


def test_pacer_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        Pacer(0)


def test_tick_does_not_change_events():
    def run(tick):
        events = []
        yard = Shipyard(fixed_orders(params.load()), seed=0, sink=events.append)
        yard.run(yard.clock.minute_of("2027-06-01"), every=10, tick=tick)
        return events

    ticks = []
    assert run(ticks.append) == run(None)
    assert ticks[:2] == [10, 20]


def test_stops_after_the_day_that_reaches_the_cap(tmp_path, capsys):
    full, capped = tmp_path / "full", tmp_path / "capped"
    sim_main(["--until", "2027-01-01", "--out-dir", str(full)])
    sim_main(["--until", "2027-01-01", "--out-dir", str(capped), "--max-gb", str(20_000 / 1024**3)])
    assert "에 닿아" in capsys.readouterr().out
    got = list(read_events(capped))
    last = got[-1]["occurred_at"][:10]
    # 상한(2만 바이트)을 넘긴 날까지 다 쓰고, 그다음 날은 없다
    assert got == [e for e in read_events(full) if e["occurred_at"][:10] <= last]
    size = {f.parent.name[3:]: f.stat().st_size for f in capped.glob("dt=*/part-0.jsonl")}
    assert sum(size.values()) >= 20_000 > sum(n for d, n in size.items() if d < last)
