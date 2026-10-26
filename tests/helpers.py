from sim import params


def single_hull_params(ship_type: str = "lng_carrier") -> dict:
    """수주 목록을 한 척짜리 계약 하나로 바꾼 params. 한 척의 흐름만 볼 때 쓴다."""
    p = params.load()
    p["orders"]["contracts"] = [{"day": 0, "ship_type": ship_type, "owner": "남해해운", "count": 1}]
    return p
