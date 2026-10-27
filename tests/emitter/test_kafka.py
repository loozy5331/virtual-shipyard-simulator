"""Kafka 출력(ADR-007): 토픽·키·타임스탬프, 버퍼가 차면 기다림, 전달 실패는 멈춤.
브로커 없이 가짜 프로듀서로 확인한다."""

import json

import pytest

from emitter.kafka import KafkaSink, topic

EVENT = {
    "event_id": "e1",
    "event_type": "block.process_completed",
    "source": "mes",
    "emitted_at": "2028-12-05T10:00:00+09:00",
    "entity_key": "B-1",
}


class FakeProducer:
    def __init__(self, full=0, error=None):
        self.sent = []
        self.full = full  # 처음 몇 번은 버퍼가 찼다
        self.polls = 0
        self.error = error
        self.pending = []

    def produce(self, topic, key, value, timestamp, on_delivery):
        if self.full:
            self.full -= 1
            raise BufferError
        self.sent.append((topic, key, value, timestamp))
        self.pending.append(on_delivery)

    def poll(self, _timeout):
        self.polls += 1
        self._deliver()

    def flush(self, _timeout):
        self._deliver()
        return 0

    def _deliver(self):
        for cb in self.pending:
            cb(self.error, None)
        self.pending = []


def test_topic_key_value_timestamp():
    fake = FakeProducer()
    sink = KafkaSink(producer=fake)
    sink(EVENT, "2028-12-05")
    sink({**EVENT, "event_type": "system.manifest_published", "entity_key": "MANIFEST-MES"}, "")
    sink.flush()
    (t, key, value, ms), (t2, key2, _, _) = fake.sent
    assert (t, key) == ("mes.events", b"B-1")
    assert json.loads(value) == EVENT
    assert ms == 1859590800000  # 2028-12-05T01:00:00Z
    assert (t2, key2) == ("mes.manifest", b"MANIFEST-MES")
    assert sink.count == 2


def test_topic_by_source():
    assert topic({**EVENT, "source": "erp"}) == "erp.events"


def test_waits_when_buffer_full():
    fake = FakeProducer(full=3)
    sink = KafkaSink(producer=fake)
    sink(EVENT, "")
    assert len(fake.sent) == 1 and fake.polls >= 3


def test_delivery_error_stops():
    sink = KafkaSink(producer=FakeProducer(error="TOPIC_AUTHORIZATION_FAILED"))
    with pytest.raises(RuntimeError, match="TOPIC_AUTHORIZATION_FAILED"):
        sink(EVENT, "")
