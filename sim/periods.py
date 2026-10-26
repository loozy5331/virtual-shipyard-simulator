"""구간 평균 확인: 시드 여러 개로 한 척씩 돌려 마일스톤 사이 기간의 평균을 기간표와 견준다.

uv run python -m sim.periods --seeds 20
"""

import argparse
from datetime import datetime
from statistics import mean
from typing import Any

from sim import params
from sim.engine import simulate

MILESTONES = ["steel_cutting", "keel_laying", "launching", "delivery"]
# 마일스톤 기간표(도메인 모델 문서): 강재절단 → 착공, 착공 → 진수, 진수 → 인도 (개월)
TABLE = {
    "lng_carrier": (4, 4, 7),
    "vlcc": (4, 3, 4),
    "container": (4, 4, 4),
}
DAYS_PER_MONTH = 30.4


def periods(p: dict[str, Any], ship_type: str, seed: int) -> list[float]:
    """한 척만 수주해 돌린 뒤 마일스톤 사이 기간(개월). 다른 배와의 대기는 빠진다."""
    p = {**p, "orders": {**p["orders"]}}
    p["orders"]["contracts"] = [{"day": 0, "ship_type": ship_type, "owner": "-", "count": 1}]
    p["orders"]["arrivals"] = {**p["orders"]["arrivals"], "contracts_per_year": 0}
    at = {}

    def sink(e: dict[str, Any]) -> None:
        if e["event_type"] == "hull.milestone_reached":
            at[e["payload"]["milestone"]] = datetime.fromisoformat(e["occurred_at"])

    simulate(p, seed, sink)
    return [
        (at[b] - at[a]).total_seconds() / 86400 / DAYS_PER_MONTH
        for a, b in zip(MILESTONES, MILESTONES[1:], strict=False)
    ]


def period_means(p: dict[str, Any], ship_type: str, seeds: range) -> list[float]:
    runs = [periods(p, ship_type, seed) for seed in seeds]
    return [mean(col) for col in zip(*runs, strict=True)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sim.periods", description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=20, help="시드 0..N-1")
    args = parser.parse_args(argv)

    p = params.load()
    print(f"{'선종':<13} {'구간':<24} 기간표   평균    차이")
    for ship_type, table in TABLE.items():
        got = period_means(p, ship_type, range(args.seeds))
        for a, b, want, x in zip(MILESTONES, MILESTONES[1:], table, got, strict=False):
            print(f"{ship_type:<15} {a + '→' + b:<26} {want:>5} {x:6.2f} {x / want - 1:+6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
