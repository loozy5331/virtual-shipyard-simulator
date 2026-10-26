"""연간 생산 계획을 작업장이 소화하는지. 가동률이 너무 높으면 대기가 끝없이 쌓이고,
너무 낮으면 경합이 생기지 않아 데이터가 심심해진다."""

import pytest

from sim import params

P = params.load()
YARD = P["yard"]
SHIPS = P["ship_types"]["ship_types"]
MIX = YARD["annual_plan"]["mix"]
RES = YARD["resources"]


def _slots(name):
    return RES[name]["count"] * RES[name]["slots"]


def _mean_block_days(ship, process):
    w = ship["steel_weight_t"] / ship["block_count"]
    work = ship["block_work"][process]
    return work["base_days"] + w * work["days_per_100t"] / 100


def _demand():
    """작업장별 1년 동안 필요한 칸·일(slot-days)."""
    need = {name: 0.0 for name in RES}
    for ship_type, n in MIX.items():
        ship = SHIPS[ship_type]
        for p in P["processes"]["processes"]:
            if p["unit"] == "block":
                days = ship["block_count"] * _mean_block_days(ship, p["id"])
            else:
                days = ship["durations_days"][p["id"]]
            need[p["resource"]] += n * days
    return need


def test_mix_adds_up_to_deliveries():
    assert sum(MIX.values()) == YARD["annual_plan"]["deliveries"]


@pytest.mark.parametrize("resource", list(RES))
def test_utilization_in_range(resource):
    utilization = _demand()[resource] / (365 * _slots(resource))
    assert 0.5 <= utilization <= 0.85, f"{resource}: {utilization:.0%}"
