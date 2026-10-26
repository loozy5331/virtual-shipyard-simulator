"""수주. 고정 목록 다음에 포아송 도착으로 계약이 들어오고(ADR-004), 계약은 호선 단위로 펼친다."""

import random
from typing import Any

from sim.clock import Clock, days


class HullNumbers:
    """호선 번호 H-YYNN. 계약한 해마다 01부터."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.year, self.count = None, 0

    def next(self, contracted: int) -> str:
        year = self.clock.at(contracted).year
        if year != self.year:
            self.year, self.count = year, 0
        self.count += 1
        if self.count > 99:
            raise ValueError(f"{year}년 계약이 99척을 넘는다(호선 번호 H-YYNN)")
        return f"H-{year % 100:02d}{self.count:02d}"


def hulls(
    orders: dict[str, Any], contract: dict[str, Any], contracted: int, numbers: HullNumbers
) -> list[dict[str, Any]]:
    """계약 한 건(같은 선종 count척)을 호선 하나씩으로."""
    return [
        {
            "hull_no": numbers.next(contracted),
            "ship_type": contract["ship_type"],
            "owner": contract["owner"],
            "contracted": contracted,
            "min_start_lag": days(orders["start_lag_days"]),
            "buffer": days(orders["delivery_buffer_days"]),
        }
        for _ in range(contract["count"])
    ]


def fixed_contracts(orders: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(orders["contracts"], key=lambda c: c["day"])


def arrivals_on(orders: dict[str, Any]) -> bool:
    return orders["arrivals"]["contracts_per_year"] > 0


def next_contract(
    rng: random.Random, arrivals: dict[str, Any], mix: dict[str, int]
) -> tuple[float, dict[str, Any]]:
    """(앞 계약부터 일 수, 계약). 간격은 지수분포, 척수는 1~4 가중치, 선종은 연간 계획 비율."""
    gap = rng.expovariate(arrivals["contracts_per_year"] / 365)
    ship_type = rng.choices(sorted(mix), weights=[mix[k] for k in sorted(mix)])[0]
    count = rng.choices(range(1, 5), weights=arrivals["count_weights"])[0]
    owner = rng.choice(arrivals["owners"][ship_type])
    return gap, {"ship_type": ship_type, "owner": owner, "count": count}
