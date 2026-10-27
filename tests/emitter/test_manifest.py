"""마감 집계(ADR-006): 출처 시스템마다 하루 한 번, 최근 lookback_days 안의 개체만
마지막 seq를 낸다."""

from datetime import datetime, timedelta

import pytest

from emitter.manifest import ManifestPublisher
from emitter.noise import KST, Emitter
from sim import params
from sim.engine import simulate
from sim.io.schema import validator
from tests.helpers import fixed_orders

NOISE = params.load()["variability"]["noise"]
LOOKBACK = 3


@pytest.fixture(scope="module")
def truth():
    out = []
    simulate(fixed_orders(params.load()), seed=0, sink=out.append)
    return out


@pytest.fixture(scope="module")
def emitted(truth):
    out = []
    emitter = Emitter(NOISE, 0, lambda e, _d: out.append(e), lookback_days=LOOKBACK)
    for e in truth:
        emitter(e)
    emitter.close()
    return out


def _manifests(emitted):
    return [e for e in emitted if e["event_type"] == "system.manifest_published"]


def test_daily_per_source_at_midnight(emitted):
    manifests = _manifests(emitted)
    v = validator()
    assert manifests and all(v.is_valid(e) for e in manifests)
    assert {e["source"] for e in manifests} == {"erp", "mes", "eam"}  # eam: 설비 고장(ADR-010)
    for e in manifests:
        assert e["occurred_at"].endswith("T00:00:00+09:00")
        assert e["emitted_at"] == e["occurred_at"]
    for source in ("erp", "mes"):
        seqs = [e["seq"] for e in manifests if e["source"] == source]
        assert seqs == list(range(1, len(seqs) + 1))


def test_last_seq_is_what_source_sent_within_lookback(truth, emitted):
    """집계 값 = 마감 전 그 시스템이 보낸 마지막 seq(빠진 것 포함). 범위 밖 개체는 없다."""
    for manifest in _manifests(emitted)[::25]:
        cutoff = datetime.fromisoformat(manifest["occurred_at"])
        oldest = cutoff - timedelta(days=LOOKBACK)
        want = {}
        for e in truth:
            at = datetime.fromisoformat(e["occurred_at"])
            if e["source"] == manifest["source"] and oldest <= at < cutoff:
                want[e["entity_key"]] = e["seq"]
        assert manifest["payload"]["last_seq"] == want


def test_old_entities_leave_manifest(emitted):
    """인도한 배는 마지막 이벤트 뒤 lookback_days가 지나면 집계에서 빠진다."""
    mes = [e for e in _manifests(emitted) if e["source"] == "mes"]
    seen = {k for e in mes for k in e["payload"]["last_seq"]}
    final = mes[-1]["payload"]["last_seq"]
    assert len(final) < len(seen) / 10


def test_every_dropped_event_is_covered_by_a_manifest(truth, emitted):
    """빠진 이벤트마다 그 시스템의 어떤 마감 집계가 그 seq 이상을 알려 준다.
    그래서 대사로 끝 번호 누락도 찾는다."""
    got = {e["event_id"] for e in emitted}
    best = {}
    for r in _manifests(emitted):
        for key, seq in r["payload"]["last_seq"].items():
            best[(r["source"], key)] = max(best.get((r["source"], key), 0), seq)
    dropped = [e for e in truth if e["event_id"] not in got]
    assert dropped
    for e in dropped:
        assert best[(e["source"], e["entity_key"])] >= e["seq"]


def test_state_is_bounded_by_lookback():
    r = ManifestPublisher(0, lookback_days=2, tz=KST)
    start = int(datetime(2027, 1, 1, 8, tzinfo=KST).timestamp())
    for day in range(30):
        t = start + day * 86400
        r.due(t)
        r.record({"run_id": "x", "source": "mes", "entity_key": f"B{day}", "seq": 1}, t)
    assert r.size() <= 3
