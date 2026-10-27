"""원천의 계약만으로 누락을 모두 찾아 복구할 수 있다(ADR-008).

계약: 개체별 seq는 1부터 빈 번호 없이 매긴다, 하루 한 번 마감 집계(ADR-006),
재발행 요청 형식(schemas/replay_request.json)과 재발행(emitter.replay).
대사는 플랫폼의 일이다. 여기의 reconcile은 계약이 충분한지 보이려는 참조 구현이다.
"""

import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from emitter.cli import main as emit_main
from emitter.manifest import DAY, ManifestPublisher
from emitter.noise import KST, Emitter
from emitter.replay import main as replay_main
from emitter.report import measure
from sim import params
from sim.cli import main as sim_main
from sim.engine import simulate
from sim.reader import read_events
from sim.schema import request_validator
from tests.helpers import fixed_orders

MANIFEST = "system.manifest_published"
VARIABILITY = params.load()["variability"]
NOISE, LOOKBACK = VARIABILITY["noise"], VARIABILITY["manifest"]["lookback_days"]


def reconcile(emitted: list[dict[str, Any]]) -> dict[str, Any]:
    """방출 로그만 보고 중복과 누락을 찾는다. 누락은 받은 가장 큰 seq 아래의 빈 번호와,
    그 위로 마감 집계가 알려 준 번호(개체마다 시스템을 가로질러 가장 큰 값)."""
    seen, duplicates = set(), 0
    got: dict[str, set[int]] = {}
    manifested: dict[str, int] = {}
    for e in emitted:
        if e["event_type"] == MANIFEST:
            for key, seq in e["payload"]["last_seq"].items():
                manifested[key] = max(manifested.get(key, 0), seq)
            continue
        if e["event_id"] in seen:
            duplicates += 1
            continue
        seen.add(e["event_id"])
        got.setdefault(e["entity_key"], set()).add(e["seq"])

    missing, by_gap, by_manifest = [], 0, 0
    for key in sorted(got.keys() | manifested.keys()):
        received = got.get(key, set())
        high = max(received, default=0)
        for seq in range(1, max(high, manifested.get(key, 0)) + 1):
            if seq not in received:
                missing.append({"entity_key": key, "seq": seq})
                if seq < high:
                    by_gap += 1
                else:
                    by_manifest += 1
    return {
        "duplicates": duplicates,
        "missing": missing,
        "by_seq_gap": by_gap,
        "by_manifest": by_manifest,
    }


def _dropped(truth, emitted) -> list[dict[str, Any]]:
    ids = {e["event_id"] for e in emitted}
    lost = [(e["entity_key"], e["seq"]) for e in truth if e["event_id"] not in ids]
    return [{"entity_key": k, "seq": s} for k, s in sorted(lost)]


def _e(key, seq, source="mes"):
    return {
        "event_id": f"{key}-{seq}",
        "event_type": "block.process_completed",
        "source": source,
        "entity_key": key,
        "seq": seq,
    }


def _manifest(last_seq, source="mes"):
    return {"event_type": MANIFEST, "source": source, "payload": {"last_seq": last_seq}}


def test_gap_and_tail_small_case():
    """A의 2는 빈 번호로, B의 끝 번호 2·3은 마감 집계로 찾는다. B의 1은 중복."""
    emitted = [_e("A", 3), _e("A", 1), _e("B", 1), _e("B", 1), _manifest({"A": 3, "B": 3})]
    r = reconcile(emitted)
    assert (r["duplicates"], r["by_seq_gap"], r["by_manifest"]) == (1, 1, 2)
    assert r["missing"] == [
        {"entity_key": "A", "seq": 2},
        {"entity_key": "B", "seq": 2},
        {"entity_key": "B", "seq": 3},
    ]


def test_tail_is_lost_without_manifest():
    """마감 집계가 없으면 끝 번호 누락은 알 수 없다. 집계가 필요한 까닭."""
    r = reconcile([_e("B", 1)])
    assert r["missing"] == []


def test_seq_runs_across_systems():
    """호선의 seq는 erp(수주 1번)에서 mes로 이어진다. 시스템별 집계 중 큰 값을 본다."""
    emitted = [
        _e("H-2601", 1, "erp"),
        _manifest({"H-2601": 1}, "erp"),
        _manifest({"H-2601": 3}, "mes"),
    ]
    assert reconcile(emitted)["missing"] == [
        {"entity_key": "H-2601", "seq": 2},
        {"entity_key": "H-2601", "seq": 3},
    ]


def test_manifest_covers_entity_only_within_lookback():
    """개체의 마지막 이벤트 뒤 lookback_days 동안만 집계에 든다.
    플랫폼은 그 안에 대사해야 끝 번호 누락을 찾는다."""
    publisher = ManifestPublisher(0, LOOKBACK, KST)
    last = int(datetime(2027, 1, 1, 12, tzinfo=KST).timestamp())
    publisher.due(last)  # 방출기처럼 기록 전에 마감을 본다(첫 마감을 정한다)
    publisher.record({**_e("B", 3), "run_id": "v0-s0"}, last)
    manifests = [m for _, m in publisher.due(last + (LOOKBACK + 10) * DAY)]
    assert len(manifests) == LOOKBACK
    assert all(m["payload"]["last_seq"] == {"B": 3} for m in manifests)
    end = datetime.fromtimestamp(last, KST) + timedelta(days=LOOKBACK)
    assert datetime.fromisoformat(manifests[-1]["occurred_at"]) <= end


@pytest.fixture(scope="module")
def run():
    truth = []
    simulate(fixed_orders(params.load()), seed=0, sink=truth.append)
    emitted = []
    emitter = Emitter(NOISE, 0, lambda e, _date: emitted.append(e), LOOKBACK)
    for e in truth:
        emitter(e)
    emitter.close()
    return truth, emitted


def test_every_drop_and_duplicate_is_found(run):
    truth, emitted = run
    m, r = measure(truth, emitted), reconcile(emitted)
    assert r["duplicates"] == m["duplicated"] > 0
    assert r["missing"] == _dropped(truth, emitted)
    assert r["by_seq_gap"] > 0 and r["by_manifest"] > 0


def test_requests_match_schema(run):
    _, emitted = run
    missing = reconcile(emitted)["missing"]
    assert missing and all(request_validator().is_valid(r) for r in missing)


def test_find_request_replay_recovers_every_drop(tmp_path, capsys):
    """대사 → 요청 파일 → emitter.replay → 누락 0, 중복은 그대로."""
    truth, emitted, requests = tmp_path / "truth", tmp_path / "emitted", tmp_path / "req.jsonl"
    sim_main(["--seed", "0", "--until", "2029-06-01", "--out-dir", str(truth)])
    emit_main(["--truth", str(truth), "--out-dir", str(emitted)])
    before = measure(read_events(truth), read_events(emitted))
    missing = reconcile(list(read_events(emitted)))["missing"]
    assert len(missing) == before["dropped"] > 0
    requests.write_text("".join(json.dumps(r) + "\n" for r in missing))

    at = "2029-06-01T09:00:00"
    replay_main(
        ["--truth", str(truth), "--requests", str(requests), "--at", at, "--out-dir", str(emitted)]
    )
    part = emitted / "dt=2029-06-01" / "part-replay-20290601T090000.jsonl"
    replayed = [json.loads(line) for line in part.read_text().splitlines()]
    assert len(replayed) == before["dropped"]
    assert {e["emitted_at"] for e in replayed} == {at + "+09:00"}

    after = measure(read_events(truth), read_events(emitted))
    assert after["dropped"] == 0
    assert after["duplicated"] == before["duplicated"]
    assert reconcile(list(read_events(emitted)))["missing"] == []
    capsys.readouterr()
