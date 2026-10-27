from sim.planner import DockPlan

E, FLOOD = 1000, 10  # 탑재 1000분, 반쪽 몫 500분


def _plan(count=1):
    return DockPlan(count, half_share=0.5, flood_minutes=FLOOD)


def test_empty_dock_takes_whole_erection():
    b = _plan().book(earliest=100, erection=E)
    assert (b.dock, b.keel, b.launch, b.half) == (0, 100, 100 + E + FLOOD, False)


def test_second_ship_starts_in_half_and_finishes_after_first_launch():
    plan = _plan()
    first = plan.book(0, E)
    second = plan.book(0, E)
    assert second.half
    assert second.keel == first.launch - 500  # 반쪽 몫을 앞 배 진수에 맞춰 마친다
    assert second.launch == first.launch + 500 + FLOOD


def test_half_ship_finishes_its_share_by_ahead_launch():
    """반쪽 몫을 앞 배 진수까지 못 마치면 반쪽 자리를 쓰지 않고 앞 배 진수 뒤 전체 자리로."""
    plan = _plan()
    first = plan.book(0, E)
    second = plan.book(first.launch - 100, E)
    assert not second.half
    assert second.keel == first.launch
    assert second.launch == first.launch + E + FLOOD


def test_tandem_chain_keeps_pace():
    """같은 배가 이어지면 반쪽 자리를 계속 쓰고, 진수 간격 = 남은 몫 + 물 채우기."""
    plan = _plan()
    bookings = [plan.book(0, E) for _ in range(4)]
    assert [b.half for b in bookings] == [False, True, True, True]
    gaps = [b.launch - a.launch for a, b in zip(bookings, bookings[1:], strict=False)]
    assert gaps == [500 + FLOOD] * 3
    for ahead, b in zip(bookings, bookings[1:], strict=False):
        assert b.keel + 500 == ahead.launch


def test_picks_dock_with_earliest_launch():
    plan = _plan(2)
    a, b = plan.book(0, E), plan.book(0, E)
    assert (a.dock, a.half, b.dock, b.half) == (0, False, 1, False)
    c = plan.book(0, E)
    assert c.dock == 0 and c.half
