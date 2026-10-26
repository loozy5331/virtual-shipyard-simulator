from sim import params


def fixed(p: dict) -> dict:
    """소요 시간 흩어짐을 끈다(cv 0). 고정 시간에 기대는 구조 테스트에 쓴다."""
    for d in p["variability"]["duration"].values():
        d["cv"] = 0
    return p


def fixed_orders(p: dict) -> dict:
    """포아송 수주를 끈다. 고정 목록만 받아 다 인도하면 끝난다."""
    p["orders"]["arrivals"]["contracts_per_year"] = 0
    return p


def single_hull_params(ship_type: str = "lng_carrier", vary: bool = False) -> dict:
    """수주 목록을 한 척짜리 계약 하나로 바꾼 params. 한 척의 흐름만 볼 때 쓴다.
    기본은 고정 시간, vary=True면 v0 분포대로 흔든다."""
    p = fixed_orders(params.load())
    p["orders"]["contracts"] = [{"day": 0, "ship_type": ship_type, "owner": "남해해운", "count": 1}]
    return p if vary else fixed(p)
