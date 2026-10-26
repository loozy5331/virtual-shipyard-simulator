"""시뮬레이션 시계(정수 분)와 이벤트 시각 문자열 사이의 변환(ADR-002)."""

from datetime import datetime, timedelta

MINUTES_PER_DAY = 24 * 60


def days(n: float) -> int:
    """달력 일을 정수 분으로. MVP 근무 달력은 24시간 연속이다."""
    return round(n * MINUTES_PER_DAY)


class Clock:
    def __init__(self, epoch: str):
        self.epoch = datetime.fromisoformat(epoch)
        if self.epoch.utcoffset() != timedelta(hours=9):
            raise ValueError("epoch는 +09:00 시각이어야 한다")

    def at(self, minute: int) -> datetime:
        return self.epoch + timedelta(minutes=minute)

    def minute_of(self, date: str) -> int:
        """YYYY-MM-DD 0시(+09:00)의 시계 분."""
        at = datetime.fromisoformat(date).replace(tzinfo=self.epoch.tzinfo)
        return int((at - self.epoch).total_seconds() // 60)

    def iso(self, minute: int) -> str:
        return self.at(minute).isoformat(timespec="seconds")

    def date(self, minute: int) -> str:
        return self.at(minute).date().isoformat()

    def unix_ms(self, minute: int) -> int:
        return int(self.at(minute).timestamp() * 1000)
