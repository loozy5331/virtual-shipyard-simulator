"""재발행 서비스(ADR-012): 요청 디렉터리를 살펴 재발행하고, 처리한 파일은 옮긴다."""

import json

from emitter.replay_service import clock, main, scan


def _e(key, seq, emitted_at="2029-06-01T08:00:00+09:00"):
    return {"event_id": f"{key}-{seq}", "entity_key": key, "seq": seq, "emitted_at": emitted_at}


def _jsonl(path, rows, tail=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail)


def _dirs(tmp_path, emitted_at="2029-06-01T08:00:00+09:00"):
    truth, emitted, requests = tmp_path / "truth", tmp_path / "emitted", tmp_path / "requests"
    _jsonl(truth / "dt=2029-05-31" / "part-0.jsonl", [_e("A", 1), _e("A", 2), _e("B", 1)])
    _jsonl(emitted / "dt=2029-06-01" / "part-0.jsonl", [_e("A", 1, emitted_at)])
    requests.mkdir()
    return truth, emitted, requests


def _replayed(emitted):
    return [
        json.loads(line)
        for f in emitted.glob("dt=*/part-replay-*.jsonl")
        for line in f.read_text().splitlines()
    ]


def test_clock_is_latest_emitted_at_skipping_partial_line(tmp_path):
    day = tmp_path / "dt=2029-06-02"
    _jsonl(tmp_path / "dt=2029-06-01" / "part-0.jsonl", [_e("A", 1, "2029-06-01T23:00:00+09:00")])
    _jsonl(day / "part-0.jsonl", [_e("A", 2, "2029-06-02T03:00:00+09:00")], tail='{"entity_')
    _jsonl(day / "part-replay-20290602T020000.jsonl", [_e("B", 1, "2029-06-02T02:00:00+09:00")])
    assert clock(tmp_path).isoformat() == "2029-06-02T03:00:00+09:00"
    assert clock(tmp_path / "none") is None


def test_request_is_replayed_one_second_after_latest_and_moved_to_done(tmp_path):
    truth, emitted, requests = _dirs(tmp_path)
    _jsonl(requests / "r1.jsonl", [{"entity_key": "A", "seq": 2}, {"entity_key": "C", "seq": 1}])
    assert scan(requests, truth, emitted) == 1
    assert _replayed(emitted) == [{**_e("A", 2), "emitted_at": "2029-06-01T08:00:01+09:00"}]
    assert not (requests / "r1.jsonl").exists()
    assert (requests / "done" / "r1.jsonl").exists()


def test_each_request_gets_its_own_time_and_file(tmp_path):
    truth, emitted, requests = _dirs(tmp_path)
    _jsonl(requests / "r1.jsonl", [{"entity_key": "A", "seq": 2}])
    _jsonl(requests / "r2.jsonl", [{"entity_key": "B", "seq": 1}])
    assert scan(requests, truth, emitted) == 2
    times = sorted(e["emitted_at"] for e in _replayed(emitted))
    assert times == ["2029-06-01T08:00:01+09:00", "2029-06-01T08:00:02+09:00"]


def test_bad_request_moves_to_failed_with_reason_and_sends_nothing(tmp_path):
    truth, emitted, requests = _dirs(tmp_path)
    _jsonl(requests / "bad.jsonl", [{"entity_key": "A", "seq": 2}, {"entity_key": "A", "seq": 0}])
    assert scan(requests, truth, emitted) == 1
    assert _replayed(emitted) == []
    assert "bad.jsonl:2" in (requests / "failed" / "bad.jsonl.error").read_text()
    assert (requests / "failed" / "bad.jsonl").exists()


def test_waits_while_nothing_emitted_and_ignores_unfinished_files(tmp_path):
    truth, emitted, requests = _dirs(tmp_path)
    for f in emitted.rglob("*.jsonl"):
        f.unlink()
    _jsonl(requests / "r1.jsonl", [{"entity_key": "A", "seq": 2}])
    _jsonl(requests / "r2.jsonl.tmp", [{"entity_key": "B", "seq": 1}])
    assert scan(requests, truth, emitted) == 0
    assert (requests / "r1.jsonl").exists()


def test_cli_once(tmp_path, capsys):
    truth, emitted, requests = _dirs(tmp_path)
    _jsonl(requests / "r1.jsonl", [{"entity_key": "A", "seq": 2}])
    args = ["--requests-dir", str(requests), "--truth", str(truth), "--out-dir", str(emitted)]
    assert main([*args, "--once"]) == 0
    assert "r1.jsonl: 요청 1개 → 재발행 1개" in capsys.readouterr().out
    assert (requests / "done" / "r1.jsonl").exists()
