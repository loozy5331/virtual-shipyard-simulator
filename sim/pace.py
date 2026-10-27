"""재생 속도(ADR-013): 가상 시각을 실제 시간에 맞춘다. 가상 speed초 = 실제 1초
(1440이면 가상 하루 = 실제 1분)."""

import time
from collections.abc import Callable


class Pacer:
    """처음 부른 가상 시각과 그때의 실제 시각이 기준이다. 가상 시각이 기준에서 lead초 안이면
    기다리지 않고, 그 뒤로는 실제 시간보다 앞서지 않게 기다린다. 기다리기 전에 idle()을
    부른다(쓴 파일 비우기 등)."""

    def __init__(
        self,
        speed: float,
        lead: float = 0,
        idle: Callable[[], None] = lambda: None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if speed <= 0:
            raise ValueError(f"speed는 0보다 커야 한다: {speed}")
        self.speed, self.lead, self.idle = speed, lead, idle
        self.clock, self.sleep = clock, sleep
        self.start: tuple[float, float] | None = None

    def __call__(self, virtual: float) -> None:
        """가상 시각(초)에 닿을 때까지 기다린다."""
        if self.start is None:
            self.start = (virtual, self.clock())
            return
        v0, w0 = self.start
        wait = w0 + max(0.0, virtual - v0 - self.lead) / self.speed - self.clock()
        if wait > 0:
            self.idle()
            self.sleep(wait)
