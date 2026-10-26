"""5단계 완료 기준: 설정 비율대로 측정되고, seq·event_id로 노이즈를 모두 찾아낸다."""

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
        "entity_key": key,
        "seq": seq,
        "occurred_at": at,
        "emitted_at": emitted,
    }


def test_measure_small_case():
    """A: 2를 빠뜨림(빈 번호로 찾음). B: 2·3을 빠뜨림(마지막 번호라 못 찾음), 1을 중복."""
    truth = [_e("A", 1), _e("A", 2), _e("A", 3), _e("B", 1), _e("B", 2), _e("B", 3)]
    emitted = [_e("A", 3), _e("A", 1), _e("B", 1), _e("B", 1)]
    m = measure(truth, emitted)
    assert (m["dropped"], m["duplicated"], m["out_of_order"]) == (3, 1, 1)
    assert m["found"] == {"duplicates_by_event_id": 1, "drops_by_seq_gap": 1}
    assert m["drops_at_tail"] == 2


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


def test_every_noise_is_found(measured):
    """중복은 event_id로 모두, 누락은 seq 빈 번호 + 개체의 마지막 번호로 모두 설명된다."""
    m = measured
    assert m["found"]["duplicates_by_event_id"] == m["duplicated"] > 0
    assert m["found"]["drops_by_seq_gap"] + m["drops_at_tail"] == m["dropped"] > 0
    assert m["found"]["drops_by_seq_gap"] > m["drops_at_tail"]
    assert m["not_in_truth"] == 0


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
    assert m["found"]["duplicates_by_event_id"] == m["duplicated"]
    main(["--truth", str(truth), "--emitted", str(emitted)])
    assert "모두 찾음" in capsys.readouterr().out
