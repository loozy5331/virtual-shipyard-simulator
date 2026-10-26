import pytest

from sim import params
from sim.params import ParamsError, unwrap


def test_params_load():
    p = params.load()
    assert p["yard"]["resources"]["dock"]["count"] == 1
    assert p["ship_types"]["ship_types"]["lng_carrier"]["block_count"] == 8
    assert [x["id"] for x in p["processes"]["processes"]] == [
        "steel_fabrication",
        "block_assembly",
        "erection",
        "quay_outfitting",
        "sea_trial",
    ]


def test_graded_number_unwraps():
    assert unwrap({"a": {"value": 3, "grade": "가정", "note": "x"}}) == {"a": 3}
    assert unwrap({"w": {"value": [1, 2], "grade": "맞춤"}}) == {"w": [1, 2]}


@pytest.mark.parametrize(
    "node",
    [
        {"a": 3},
        {"a": [1, 2]},
        {"a": {"value": 3, "grade": "추정"}},
        {"a": {"grade": "가정"}},
    ],
)
def test_ungraded_number_is_rejected(node):
    with pytest.raises(ParamsError):
        unwrap(node)
