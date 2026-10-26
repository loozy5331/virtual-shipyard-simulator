"""세미 탠덤 도크 규칙(ADR-003)을 도크 모듈만 떼어 확인한다. 시간 단위는 그냥 정수."""

import simpy

from sim.dock import FULL, HALF, DockYard


def _ship(env, docks, log, key, arrive, half_work, full_work):
    """도크에 들어가 탑재를 하는 배. half_work + full_work = 탑재 전체."""
    yield env.timeout(arrive)
    dock, position = yield docks.enter(key)
    log.append((env.now, key, "enter", dock.id, position))
    if position == HALF:
        yield env.timeout(half_work)
        yield docks.half_done(dock)
        log.append((env.now, key, "move", dock.id, FULL))
        yield env.timeout(full_work)
    else:
        yield env.timeout(half_work + full_work)
    yield docks.finished(dock)
    log.append((env.now, key, "launch", dock.id, None))


def _run(ships, docks=1, flood=1):
    env = simpy.Environment()
    yard = DockYard(env, [f"DOCK-{i}" for i in range(1, docks + 1)], flood)
    log = []
    for key, arrive, half_work, full_work in ships:
        env.process(_ship(env, yard, log, key, arrive, half_work, full_work))
    env.run()
    return log


def test_empty_dock_takes_whole_ship_at_full():
    assert _run([("A", 0, 50, 50)]) == [
        (0, "A", "enter", "DOCK-1", FULL),
        (101, "A", "launch", "DOCK-1", None),  # 100일 + 물 채우기 1
    ]


def test_second_ship_builds_half_then_moves_up_when_first_launches():
    log = _run([("A", 0, 50, 50), ("B", 10, 50, 50)])
    assert log == [
        (0, "A", "enter", "DOCK-1", FULL),
        (10, "B", "enter", "DOCK-1", HALF),
        (101, "A", "launch", "DOCK-1", None),
        (101, "B", "move", "DOCK-1", FULL),  # 같은 물 채우기에 옮겨진다
        (152, "B", "launch", "DOCK-1", None),  # 101 + 남은 50 + 물 채우기 1
    ]


def test_third_ship_waits_for_half_position_then_enters_after_flood():
    log = _run([("A", 0, 50, 50), ("B", 0, 50, 50), ("C", 0, 50, 50)])
    assert (101, "C", "enter", "DOCK-1", HALF) in log
    assert [e for e in log if e[1] == "C"][0][0] == 101


def test_finished_ship_waits_until_half_can_float():
    # B는 늦게 와서 A가 완성(100)될 때 반쪽 몫이 아직이다(90 + 50 = 140)
    log = _run([("A", 0, 50, 50), ("B", 90, 50, 50)])
    launch_a = next(t for t, k, what, *_ in log if k == "A" and what == "launch")
    assert launch_a == 141  # 140에 B가 뜰 수 있게 되고 물 채우기 1


def test_ship_arriving_while_full_waits_for_launch_enters_half_after_flood():
    # A(20 완성)는 B의 반쪽 몫(5 + 50 = 55)을 기다려 56에 진수.
    # 30에 온 C는 반쪽 자리가 빌 때까지 기다린다.
    log = _run([("A", 0, 10, 10), ("B", 5, 50, 50), ("C", 30, 50, 50)])
    assert (56, "A", "launch", "DOCK-1", None) in log
    assert (56, "B", "move", "DOCK-1", FULL) in log
    assert (56, "C", "enter", "DOCK-1", HALF) in log


def test_first_come_first_served_across_docks():
    log = _run([(k, i, 50, 50) for i, k in enumerate("ABCDEF")], docks=2)
    enters = [e for e in log if e[2] == "enter"]
    assert [e[1] for e in sorted(enters)] == list("ABCDEF")
    assert {e[4] for e in enters[:2]} == {FULL}


def test_never_more_than_one_full_and_one_half_per_dock():
    ships = [(f"S{i:02d}", i * 7, 30 + i, 40) for i in range(12)]
    log = _run(ships, docks=2)
    full, half = {}, {}
    for _, key, what, dock, position in sorted(log, key=lambda e: (e[0], e[2] != "launch")):
        if what == "enter":
            (full if position == FULL else half).setdefault(dock, set()).add(key)
        elif what == "move":
            half[dock].discard(key)
            full.setdefault(dock, set()).add(key)
        else:
            full[dock].discard(key)
        assert len(full.get(dock, ())) <= 1
        assert len(half.get(dock, ())) <= 1
    assert len([e for e in log if e[2] == "launch"]) == 12


def _ship_to(env, docks, log, key, arrive, work, want):
    yield env.timeout(arrive)
    dock, position = yield docks.enter(key, want)
    log.append((env.now, key, dock.id, position))
    if position == HALF:
        yield env.timeout(work // 2)
        yield docks.half_done(dock)
        work -= work // 2
    yield env.timeout(work)
    yield docks.finished(dock)


def test_ship_enters_only_planned_dock():
    env = simpy.Environment()
    yard = DockYard(env, ["DOCK-1", "DOCK-2"], 1)
    log = []
    env.process(_ship_to(env, yard, log, "a", 0, 10, 0))
    env.process(_ship_to(env, yard, log, "b", 1, 10, 0))  # DOCK-2가 비어도 DOCK-1 반쪽
    env.run()
    assert log == [(0, "a", "DOCK-1", FULL), (1, "b", "DOCK-1", HALF)]


def test_ship_for_other_dock_is_not_blocked():
    env = simpy.Environment()
    yard = DockYard(env, ["DOCK-1", "DOCK-2"], 1)
    log = []
    for key, arrive in [("a", 0), ("b", 1), ("c", 2)]:
        env.process(_ship_to(env, yard, log, key, arrive, 10, 0))
    env.process(_ship_to(env, yard, log, "d", 3, 10, 1))  # c는 DOCK-1을 기다리고 d는 지나간다
    env.run()
    assert (3, "d", "DOCK-2", FULL) in log
    assert [k for _, k, d, _ in log if d == "DOCK-1"] == ["a", "b", "c"]


def test_ship_planned_for_full_does_not_take_half():
    env = simpy.Environment()
    yard = DockYard(env, ["DOCK-1"], 1)
    log = []

    def ship(key, arrive, work, plan):
        yield env.timeout(arrive)
        dock, position = yield yard.enter(key, 0, plan)
        log.append((env.now, key, position))
        yield env.timeout(work)
        yield yard.finished(dock)

    env.process(ship("a", 0, 10, FULL))
    env.process(ship("b", 5, 10, FULL))  # 반쪽 자리가 비어도 a가 진수(10 + 물 1)할 때까지
    env.run()
    assert log == [(0, "a", FULL), (11, "b", FULL)]
