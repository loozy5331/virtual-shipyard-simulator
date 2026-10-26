from sim.clock import Clock, days
from sim.orders import expand

CLOCK = Clock("2026-11-02T08:00:00+09:00")


def _orders(*contracts):
    return {"start_lag_days": 760, "delivery_buffer_days": 30, "contracts": list(contracts)}


def test_contract_expands_to_hulls():
    hulls = expand(_orders({"day": 0, "ship_type": "vlcc", "owner": "가", "count": 3}), CLOCK)
    assert [h["hull_no"] for h in hulls] == ["H-2601", "H-2602", "H-2603"]
    assert {h["ship_type"] for h in hulls} == {"vlcc"}
    assert hulls[0]["start_lag"] == days(760)


def test_hull_numbers_restart_each_contract_year():
    hulls = expand(
        _orders(
            {"day": 70, "ship_type": "lng_carrier", "owner": "나", "count": 1},  # 2027-01-11
            {"day": 0, "ship_type": "vlcc", "owner": "가", "count": 2},  # 2026-11-02
        ),
        CLOCK,
    )
    assert [h["hull_no"] for h in hulls] == ["H-2601", "H-2602", "H-2701"]
    assert hulls[-1]["contracted"] == days(70)
