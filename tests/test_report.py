"""5단계 완료 기준: 정답과 비교해 노이즈가 설정 비율대로 측정된다.
방출 로그만으로 찾기(대사)는 test_recoverable.py(ADR-008)."""

import json

import pytest

from emitter.cli import main as emit_main
from emitter.noise import Emitter
from emitter.report import main, measure
from sim import params
from sim.cli import main as sim_main
from sim.engine import simulate
from tests.helpers import fixed_orders

NOISE = params.load()["variability"]["noise"]


def _e(key, seq, minute=0, delay_s=0):
    at = f"2027-01-01T00:{minute:02d}:00+09:00"
    emitted = f"2027-01-01T00:{minute:02d}:{delay_s:02d}+09:00"
    return {
        "event_id": f"{key}-{seq}",
        "event_type": "block.process_completed",
        "entity_key": key,
        "seq": seq,
        "occurred_at": at,
        "emitted_at": emitted,
    }


def test_measure_small_case():
    """A: 2를 빠뜨리고 3이 1보다 먼저 옴. B: 2·3을 빠뜨리고 1을 중복. 마감 집계는 세지 않는다."""
    truth = [_e("A", 1), _e("A", 2), _e("A", 3), _e("B", 1), _e("B", 2), _e("B", 3)]
    manifest = {
        "event_type": "system.manifest_published",
        "payload": {"last_seq": {"A": 3, "B": 3}},
    }
    emitted = [_e("A", 3), _e("A", 1), _e("B", 1), _e("B", 1), manifest]
    m = measure(truth, emitted)
    assert (m["dropped"], m["duplicated"], m["out_of_order"]) == (3, 1, 1)
    assert (m["emitted_lines"], m["not_in_truth"]) == (4, 0)


@pytest.fixture(scope="module")
def measured():
    truth = []
    simulate(fixed_orders(params.load()), seed=0, sink=truth.append)
    emitted = []
    emitter = Emitter(NOISE, 0, lambda e, _date: emitted.append(e))
    for e in truth:
        emitter(e)
    emitter.close()
    return measure(truth, emitted)


def test_rates_as_configured(measured):
    m = measured
    assert m["drop_rate"] == pytest.approx(NOISE["drop_rate"], rel=0.3)
    assert m["duplicate_rate"] == pytest.approx(NOISE["duplicate_rate"], rel=0.3)
    assert m["late_rate"] == pytest.approx(NOISE["delay"]["late_rate"], rel=0.2)
    assert m["delay_seconds"]["max"] <= NOISE["delay"]["max_hours"] * 3600
    assert m["out_of_order"] > 0


def test_cli_report(tmp_path, capsys):
    truth, emitted = tmp_path / "truth", tmp_path / "emitted"
    sim_main(["--seed", "0", "--until", "2029-06-01", "--out-dir", str(truth)])
    emit_main(["--truth", str(truth), "--out-dir", str(emitted)])
    capsys.readouterr()
    main(["--truth", str(truth), "--emitted", str(emitted), "--json"])
    m = json.loads(capsys.readouterr().out)
    assert m["dropped"] > 0 and m["duplicated"] > 0 and m["not_in_truth"] == 0
    main(["--truth", str(truth), "--emitted", str(emitted)])
    out = capsys.readouterr().out
    assert "노이즈(설정 → 실제)" in out and "방출 로그만으로 찾기" not in out
