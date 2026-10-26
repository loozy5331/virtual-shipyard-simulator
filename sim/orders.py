"""수주 계약을 호선 단위 주문으로 펼친다."""

from typing import Any

from sim.clock import Clock, days


def expand(orders: dict[str, Any], clock: Clock) -> list[dict[str, Any]]:
    """계약 한 건(같은 선종 count척)을 호선 하나씩으로. 호선 번호는 계약한 해마다 01부터."""
    hulls = []
    per_year: dict[int, int] = {}
    for c in sorted(orders["contracts"], key=lambda c: c["day"]):
        contracted = days(c["day"])
        year = clock.at(contracted).year
        for _ in range(c["count"]):
            per_year[year] = per_year.get(year, 0) + 1
            if per_year[year] > 99:
                raise ValueError(f"{year}년 계약이 99척을 넘는다(호선 번호 H-YYNN)")
            hulls.append(
                {
                    "hull_no": f"H-{year % 100:02d}{per_year[year]:02d}",
                    "ship_type": c["ship_type"],
                    "owner": c["owner"],
                    "contracted": contracted,
                    "min_start_lag": days(orders["start_lag_days"]),
                    "buffer": days(orders["delivery_buffer_days"]),
                }
            )
    return hulls
