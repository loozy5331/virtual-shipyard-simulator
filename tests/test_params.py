import pytest

from sim import params
from sim.params import ParamsError, check_variability, unwrap


def test_params_load():
    p = params.load()
    assert p["yard"]["resources"]["dock"]["count"] == 5
    assert set(p["ship_types"]["ship_types"]) == {"lng_carrier", "vlcc", "container"}
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


def test_variability_loads_by_params_version():
    p = params.load()
    assert p["variability"]["params_version"] == p["yard"]["params_version"]
    duration = p["variability"]["duration"]
    assert set(duration) == {x["id"] for x in p["processes"]["processes"]}
    assert all(d["dist"] == "lognormal" and d["cv"] >= 0 for d in duration.values())


def _variability(**changes):
    p = params.load()
    v = p["variability"]
    v["duration"] = {k: dict(d) for k, d in v["duration"].items()}
    for pid, change in changes.items():
        if change is None:
            del v["duration"][pid]
        else:
            v["duration"][pid].update(change)
    return v, p["processes"]["processes"]


@pytest.mark.parametrize(
    "changes",
    [
        {"sea_trial": None},
        {"erection": {"dist": "normal"}},
        {"erection": {"cv": -0.1}},
    ],
)
def test_bad_variability_is_rejected(changes):
    v, processes = _variability(**changes)
    with pytest.raises(ParamsError):
        check_variability(v, processes)
