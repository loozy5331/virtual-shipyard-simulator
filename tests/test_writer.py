import json

import pytest

from sim.cli import main
from sim.writer import PartitionedWriter


def _event(at, n):
    return {"occurred_at": at, "seq": n}


def test_events_split_by_local_date(tmp_path):
    with PartitionedWriter(tmp_path) as w:
        w(_event("2026-11-02T08:00:00+09:00", 1))
        w(_event("2026-11-02T23:59:00+09:00", 2))
        w(_event("2026-11-04T00:00:00+09:00", 3))
    assert w.count == 3
    assert sorted(p.parent.name for p in tmp_path.glob("dt=*/part-0.jsonl")) == [
        "dt=2026-11-02",
        "dt=2026-11-04",
    ]
    lines = (tmp_path / "dt=2026-11-02" / "part-0.jsonl").read_text().splitlines()
    assert [json.loads(x)["seq"] for x in lines] == [1, 2]


def test_time_going_back_is_rejected(tmp_path):
    with PartitionedWriter(tmp_path) as w:
        w(_event("2026-11-03T08:00:00+09:00", 1))
        with pytest.raises(ValueError):
            w(_event("2026-11-02T08:00:00+09:00", 2))


def test_cli_daily_files_equal_single_file(tmp_path):
    """날짜별 파일을 이어 붙이면 파일 하나로 쓴 것과 같다."""
    args = ["--seed", "0", "--until", "2027-06-01"]
    main([*args, "--out", str(tmp_path / "all.jsonl")])
    main([*args, "--out-dir", str(tmp_path / "truth")])
    parts = sorted((tmp_path / "truth").glob("dt=*/part-0.jsonl"))
    assert len(parts) > 1
    joined = "".join(p.read_text() for p in parts)
    assert joined == (tmp_path / "all.jsonl").read_text()
    for p in parts:
        dates = {json.loads(x)["occurred_at"][:10] for x in p.read_text().splitlines()}
        assert dates == {p.parent.name.removeprefix("dt=")}
