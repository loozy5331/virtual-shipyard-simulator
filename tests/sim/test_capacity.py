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
    """도크는 처리량을 정하는 전체 자리 하나만 센다(ADR-003)."""
    return RES[name]["count"] * RES[name].get("slots", 1)


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
                r = RES[p["resource"]]
                if "half_share" in r:  # 전체 자리에 머무는 기간 = 남은 몫 + 물 채우기
                    days = days * (1 - r["half_share"]) + r["flood_days"]
            need[p["resource"]] += n * days
    return need


def test_mix_adds_up_to_deliveries():
    assert sum(MIX.values()) == YARD["annual_plan"]["deliveries"]


@pytest.mark.parametrize("resource", list(RES))
def test_utilization_in_range(resource):
    utilization = _demand()[resource] / (365 * _slots(resource))
    assert 0.5 <= utilization <= 0.85, f"{resource}: {utilization:.0%}"


def _annual_block_mh():
    total = 0.0
    for ship_type, n in MIX.items():
        ship = SHIPS[ship_type]
        mh_per_t = sum(w["mh_per_t"] for w in ship["block_work"].values())
        total += n * ship["steel_weight_t"] * mh_per_t
    return total


def test_block_work_fits_workforce():
    """블록 공정(가공·조립, 도장·선행의장 흡수)은 인력이 낼 수 있는 연간 공수의 20~50%.
    나머지는 탑재·안벽 의장·시운전과 설계·관리 등이다(가정)."""
    w = YARD["workforce"]
    capacity = (w["direct"] + w["subcontract"]) * w["annual_hours"]
    share = _annual_block_mh() / capacity
    assert 0.2 <= share <= 0.5, f"{share:.0%}"
