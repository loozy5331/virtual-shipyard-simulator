"""정답 이벤트에 노이즈를 섞어 도착 순서로 내보낸다(ADR-005).

이벤트마다 난수를 따로 뽑아(시드, event_id) 어떤 조각으로 읽어도 같은 노이즈가 붙는다.
지연에 상한이 있으므로 도착 시각 순 힙에 담았다가, 지금 읽은 occurred_at까지 도착한 것을 내보낸다.
"""

import heapq
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from emitter.manifest import ManifestPublisher

KST = timezone(timedelta(hours=9))
Event = dict[str, Any]
# (방출 이벤트, 도착 날짜 YYYY-MM-DD)
Sink = Callable[[Event, str], None]


@dataclass
class Fate:
    """이벤트 하나에 붙는 노이즈. dropped면 나머지는 의미 없다."""

    dropped: bool
    delay: int = 0  # 초, occurred_at → emitted_at
    late: bool = False
    retry: int | None = None  # 초, 중복 사본이 원본 뒤로 늦게 도착하는 간격. None이면 중복 없음


def _lognormal(rng: random.Random, median: float, sigma: float, cap: float) -> int:
    return round(min(rng.lognormvariate(math.log(median), sigma), cap))


def fate(noise: dict[str, Any], seed: int, event_id: str) -> Fate:
    rng = random.Random(f"{seed}:noise:{event_id}")
    if rng.random() < noise["drop_rate"]:
        return Fate(dropped=True)
    d = noise["delay"]
    cap = d["max_hours"] * 3600
    late = rng.random() < d["late_rate"]
    if late:
        delay = _lognormal(rng, d["late_median_minutes"] * 60, d["late_sigma"], cap)
    else:
        delay = _lognormal(rng, d["median_seconds"], d["sigma"], cap)
    retry = None
    if rng.random() < noise["duplicate_rate"]:
        retry = max(1, _lognormal(rng, noise["retry_median_seconds"], 1.0, cap))
    return Fate(dropped=False, delay=delay, late=late, retry=retry)


def _seconds(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp())


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, KST).isoformat(timespec="seconds")


class Emitter:
    """정답 이벤트를 occurred_at 순서로 받아(__call__), 방출 이벤트를 도착 순서로 sink에 넘긴다.
    끝나면 close()로 남은 것을 내보낸다. lookback_days를 주면 하루 한 번 마감 집계도
    낸다(ADR-006)."""

    def __init__(
        self, noise: dict[str, Any], seed: int, sink: Sink, lookback_days: int | None = None
    ):
        self.manifest = (
            None if lookback_days is None else ManifestPublisher(seed, lookback_days, KST)
        )
        self.noise = noise
        self.seed = seed
        self.sink = sink
        self.heap: list[tuple[int, int, Event]] = []
        self.n = 0  # 같은 도착 시각이면 먼저 읽은 것부터
        self.now = 0

    def __call__(self, event: Event) -> None:
        occurred = _seconds(event["occurred_at"])
        if occurred < self.now:
            raise ValueError(f"정답 이벤트 시각이 거꾸로 간다: {event['occurred_at']}")
        self.now = occurred
        if self.manifest is not None:
            for cutoff, manifest in self.manifest.due(occurred):
                self._push(cutoff, manifest)
            self.manifest.record(event, occurred)
        self._flush(occurred)
        f = fate(self.noise, self.seed, event["event_id"])
        if f.dropped:
            return
        emitted_at = occurred + f.delay
        out = {**event, "emitted_at": _iso(emitted_at)}
        self._push(emitted_at, out)
        if f.retry is not None:
            self._push(emitted_at + f.retry, out)

    def _push(self, arrival: int, event: Event) -> None:
        heapq.heappush(self.heap, (arrival, self.n, event))
        self.n += 1

    def _flush(self, until: int | None) -> None:
        """도착이 until 이하인 것을 내보낸다. 앞으로 읽을 이벤트는 occurred ≥ until이라
        그보다 먼저 도착하지 않는다."""
        while self.heap and (until is None or self.heap[0][0] <= until):
            arrival, _, event = heapq.heappop(self.heap)
            self.sink(event, _iso(arrival)[:10])

    def close(self) -> None:
        if self.manifest is not None:
            for cutoff, manifest in self.manifest.close():
                self._push(cutoff, manifest)
        self._flush(None)
