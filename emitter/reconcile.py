"""대사(ADR-006). 출처 시스템마다 하루 한 번 0시 마감으로, 보낸 개체별 마지막 seq를 낸다.

대사 범위는 마감 전 lookback_days 안에 이벤트가 있었던 개체뿐이다. 그보다 오래된 개체는
상태에서 지운다. 그래서 끝없이 돌려도 상태가 범위만큼만 남는다.
"""

import random
from datetime import datetime, time, timedelta
from typing import Any

from sim.ids import uuid7

DAY = 86400
Event = dict[str, Any]


class Reconciler:
    def __init__(self, seed: int, lookback_days: int, tz):
        self.lookback_days = lookback_days
        self.tz = tz
        self.rng_ids = random.Random(f"{seed}:recon")
        # 시스템 → 개체 → (보낸 마지막 seq, 마지막 이벤트 시각 초)
        self.sent: dict[str, dict[str, tuple[int, int]]] = {}
        self.seq: dict[str, int] = {}
        self.cutoff: int | None = None
        self.run_id: str | None = None

    def _iso(self, seconds: int) -> str:
        return datetime.fromtimestamp(seconds, self.tz).isoformat(timespec="seconds")

    def _next_midnight(self, seconds: int) -> int:
        day = datetime.fromtimestamp(seconds, self.tz).date() + timedelta(days=1)
        return int(datetime.combine(day, time(), self.tz).timestamp())

    def due(self, occurred: int) -> list[tuple[int, Event]]:
        """occurred까지 지난 마감의 대사 이벤트 (마감 시각, 이벤트).
        0시 정각 이벤트는 다음 날 몫이라 마감을 먼저 낸다."""
        if self.cutoff is None:
            self.cutoff = self._next_midnight(occurred)
        out = []
        while self.cutoff <= occurred:
            out += self._reconcile(self.cutoff)
            self.cutoff += DAY
        return out

    def record(self, event: Event, occurred: int) -> None:
        """시스템이 보낸 이벤트. 전송 중 빠지는 것(누락)과 상관없이 보낸 것으로 센다."""
        self.run_id = event["run_id"]
        sent = self.sent.setdefault(event["source"], {})
        last = sent.get(event["entity_key"], (0, 0))[0]
        sent[event["entity_key"]] = (max(last, event["seq"]), occurred)

    def close(self) -> list[tuple[int, Event]]:
        """마지막 이벤트 다음 마감의 대사."""
        return [] if self.cutoff is None else self._reconcile(self.cutoff)

    def _reconcile(self, cutoff: int) -> list[tuple[int, Event]]:
        oldest = cutoff - self.lookback_days * DAY
        out = []
        for source in sorted(self.sent):
            sent = self.sent[source]
            for key in [k for k, (_, at) in sent.items() if at < oldest]:
                del sent[key]  # 대사 범위 밖: 다시는 대사하지 않는다
            if not sent:
                continue
            key = f"RECON-{source.upper()}"
            self.seq[key] = self.seq.get(key, 0) + 1
            at = self._iso(cutoff)
            event = {
                "event_id": uuid7(cutoff * 1000, self.rng_ids),
                "event_type": "system.reconciled",
                "schema_version": 1,
                "source": source,
                "occurred_at": at,
                "emitted_at": at,  # 통제 경로라 노이즈가 없다
                "run_id": self.run_id,
                "entity_key": key,
                "seq": self.seq[key],
                "hull_no": None,
                "block_id": None,
                "process": None,
                "resource_id": None,
                "payload": {
                    "lookback_days": self.lookback_days,
                    "last_seq": {k: s for k, (s, _) in sorted(sent.items())},
                },
            }
            out.append((cutoff, event))
        return out

    def size(self) -> int:
        return sum(len(s) for s in self.sent.values())
