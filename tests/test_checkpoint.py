"""체크포인트(ADR-007): 멈췄다 다시 켜도 끊김 없이 돈 것과 같은 메시지가 나간다.
마지막 체크포인트 뒤에 보낸 것만 한 번 더 간다(at-least-once)."""

import pytest

from emitter.checkpoint import load, run, save
from emitter.noise import Emitter
from sim import params
from sim.cli import main as sim_main

P = params.load()["variability"]
NOISE, LOOKBACK = P["noise"], P["manifest"]["lookback_days"]


class Crash(Exception):
    pass


@pytest.fixture(scope="module")
def truth(tmp_path_factory):
    path = tmp_path_factory.mktemp("truth")
    sim_main(["--seed", "0", "--until", "2029-09-01", "--out-dir", str(path)])
    return path


def _emitter(out):
    return Emitter(NOISE, 0, lambda e, d: out.append((e["event_id"], e["emitted_at"], d)), LOOKBACK)


def test_resume_after_crash_sends_same_messages(truth, tmp_path):
    whole = []
    run(truth, _emitter(whole), flush=lambda: None)

    ckpt = tmp_path / "ckpt.pickle"
    first, flushed = [], []

    def flush():
        flushed.append(len(first))  # 여기까지는 브로커가 받았다고 확인했다

    def crash_after(limit):
        def sink(e, d):
            if len(first) >= limit:
                raise Crash
            first.append((e["event_id"], e["emitted_at"], d))

        return sink

    em = Emitter(NOISE, 0, crash_after(len(whole) // 2), LOOKBACK)
    with pytest.raises(Crash):
        run(truth, em, flush=flush, checkpoint=ckpt)
    acked = flushed[-1]
    assert 0 < acked < len(first)

    second = []
    start = run(truth, _emitter(second), flush=lambda: None, checkpoint=ckpt)
    assert start > 0
    # 확인받은 것 + 이어 보낸 것 = 끊김 없이 돈 것
    assert first[:acked] + second == whole
    # 확인받지 못한 채 보낸 것은 이어 보낸 것의 앞부분과 같다(한 번 더 간다)
    assert second[: len(first) - acked] == first[acked:]


def test_checkpoint_roundtrip(tmp_path):
    em = Emitter(NOISE, 0, lambda e, d: None, LOOKBACK)
    em.heap.append((1, 0, {"x": 1}))
    save(tmp_path / "c.pickle", 7, em)
    read, state = load(tmp_path / "c.pickle")
    assert read == 7 and state["heap"] == [(1, 0, {"x": 1})]
    assert load(tmp_path / "none.pickle") is None
