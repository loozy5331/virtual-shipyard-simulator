"""재발행(ADR-006): 리포트가 찾은 누락을 요청하면 정답에서 찾아 다시 보내고, 누락이 0이 된다."""

import json

from emitter.cli import main as emit_main
from emitter.replay import main as replay_main
from emitter.replay import replay
from emitter.report import main as report_main
from emitter.report import measure
from sim.cli import main as sim_main
from sim.reader import read_events

AT = "2029-06-01T09:00:00"


def _e(key, seq):
    return {"event_id": f"{key}-{seq}", "entity_key": key, "seq": seq, "emitted_at": "x"}


def test_replay_keeps_event_and_sets_emitted_at():
    truth = [_e("A", 1), _e("A", 2), _e("B", 1)]
    out, unknown = replay(truth, [{"entity_key": "A", "seq": 2}, {"entity_key": "C", "seq": 1}], AT)
    assert out == [{**_e("A", 2), "emitted_at": AT}]
    assert unknown == [{"entity_key": "C", "seq": 1}]


def test_find_request_replay_recovers_every_drop(tmp_path, capsys):
    truth, emitted, requests = tmp_path / "truth", tmp_path / "emitted", tmp_path / "req.jsonl"
    sim_main(["--seed", "0", "--until", "2029-06-01", "--out-dir", str(truth)])
    emit_main(["--truth", str(truth), "--out-dir", str(emitted)])
    report_main(["--truth", str(truth), "--emitted", str(emitted), "--requests", str(requests)])
    before = measure(read_events(truth), read_events(emitted))
    assert before["dropped"] > 0

    replay_main(
        ["--truth", str(truth), "--requests", str(requests), "--at", AT, "--out-dir", str(emitted)]
    )
    part = emitted / "dt=2029-06-01" / "part-replay-20290601T090000.jsonl"
    replayed = [json.loads(line) for line in part.read_text().splitlines()]
    assert len(replayed) == before["dropped"]
    assert {e["emitted_at"] for e in replayed} == {"2029-06-01T09:00:00+09:00"}

    after = measure(read_events(truth), read_events(emitted))
    assert after["dropped"] == 0 and after["missing"] == []
    assert after["duplicated"] == before["duplicated"]
    capsys.readouterr()
