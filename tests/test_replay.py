"""재발행(ADR-006): 요청을 정답에서 찾아 emitted_at만 바꿔 다시 보낸다.
요청 형식은 스키마로 검증한다. 찾기 → 요청 → 재발행 → 복구 한 바퀴는 test_recoverable.py."""

import pytest

from emitter.replay import main as replay_main
from emitter.replay import read_requests, replay

AT = "2029-06-01T09:00:00"


def _e(key, seq):
    return {"event_id": f"{key}-{seq}", "entity_key": key, "seq": seq, "emitted_at": "x"}


def test_replay_keeps_event_and_sets_emitted_at():
    truth = [_e("A", 1), _e("A", 2), _e("B", 1)]
    out, unknown = replay(truth, [{"entity_key": "A", "seq": 2}, {"entity_key": "C", "seq": 1}], AT)
    assert out == [{**_e("A", 2), "emitted_at": AT}]
    assert unknown == [{"entity_key": "C", "seq": 1}]


def test_read_requests_skips_blank_lines(tmp_path):
    path = tmp_path / "req.jsonl"
    path.write_text('{"entity_key": "A", "seq": 2}\n\n')
    assert read_requests(path) == [{"entity_key": "A", "seq": 2}]


@pytest.mark.parametrize(
    "line",
    [
        '{"entity_key": "A"}',
        '{"entity_key": "A", "seq": 0}',
        '{"entity_key": "", "seq": 1}',
        '{"entity_key": "A", "seq": "2"}',
        '{"entity_key": "A", "seq": 2, "event_id": "x"}',
        "not json",
    ],
)
def test_bad_request_is_rejected_with_line_number(tmp_path, line):
    path = tmp_path / "req.jsonl"
    path.write_text('{"entity_key": "A", "seq": 1}\n' + line + "\n")
    with pytest.raises(ValueError, match=r"req\.jsonl:2"):
        read_requests(path)


def test_cli_sends_nothing_on_bad_request(tmp_path, capsys):
    requests, out = tmp_path / "req.jsonl", tmp_path / "emitted"
    requests.write_text('{"entity_key": "A", "seq": 0}\n')
    with pytest.raises(SystemExit):
        replay_main(["--requests", str(requests), "--at", AT, "--out-dir", str(out)])
    assert not out.exists()
    assert "재발행 요청 형식" in capsys.readouterr().err
