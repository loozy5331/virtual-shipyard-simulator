"""Kafka 출력(ADR-007).

토픽은 출처 시스템별 `<source>.events`, 마감 집계는 `<source>.manifest`. 키는 entity_key라
같은 개체는 같은 파티션에 들어간다. 값은 봉투 JSON 그대로, 메시지 타임스탬프는 emitted_at.
브로커가 없거나 내려가도 버리지 않고 기다린다: 전달 제한 시간 없음, 멱등 프로듀서,
버퍼가 차면 비워질 때까지 기다린다.
"""

import json
from datetime import datetime
from typing import Any

MANIFEST = "system.manifest_published"
CONFIG = {
    "message.timeout.ms": 0,  # 0 = 제한 없음. 브로커가 돌아올 때까지 재시도한다
    "enable.idempotence": True,
    "linger.ms": 50,
}


def topic(event: dict[str, Any]) -> str:
    kind = "manifest" if event["event_type"] == MANIFEST else "events"
    return f"{event['source']}.{kind}"


def _producer(bootstrap: str):
    try:
        from confluent_kafka import Producer
    except ImportError as e:  # 선택 의존성
        raise SystemExit("Kafka 출력에는 confluent-kafka가 필요하다: uv sync --extra kafka") from e
    return Producer({"bootstrap.servers": bootstrap, **CONFIG})


class KafkaSink:
    """방출기의 sink. 보낸 것을 모두 확인받으려면 flush()."""

    def __init__(self, bootstrap: str = "localhost:9092", producer=None):
        self.producer = producer if producer is not None else _producer(bootstrap)
        self.count = 0
        self.error: Exception | None = None

    def _delivered(self, err, _msg) -> None:
        # 제한 시간이 없으니 여기 오는 오류는 재시도로 풀리지 않는 것(권한, 너무 큰 메시지 등)
        if err is not None and self.error is None:
            self.error = RuntimeError(f"Kafka 전달 실패: {err}")

    def __call__(self, event: dict[str, Any], _date: str) -> None:
        value = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
        ms = int(datetime.fromisoformat(event["emitted_at"]).timestamp() * 1000)
        while True:
            try:
                self.producer.produce(
                    topic(event),
                    key=event["entity_key"].encode(),
                    value=value,
                    timestamp=ms,
                    on_delivery=self._delivered,
                )
                break
            except BufferError:
                self.producer.poll(1)  # 버퍼가 비워질 때까지 기다린다
        self.producer.poll(0)
        self.count += 1
        self._raise()

    def flush(self) -> None:
        """보낸 것을 브로커가 모두 확인할 때까지 기다린다."""
        while self.producer.flush(1) > 0:
            pass
        self._raise()

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error
