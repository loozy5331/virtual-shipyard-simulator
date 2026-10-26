"""도크 계획(ADR-004). 계약할 때 계약 순서대로 도크 자리를 예약해 착공·진수 예정을 정한다.

시간은 평균이고, 엔진은 예약을 강제하지 않는다. 도크마다 마지막 예약의 진수 예정과
반쪽 자리가 비는 예정만 든다(세미 탠덤, ADR-003).
"""

from dataclasses import dataclass


@dataclass
class Booking:
    dock: int
    keel: int  # 착공(도크에 들어가는) 예정
    launch: int  # 진수 예정(물 채우기 포함)
    half: bool  # 반쪽 자리에서 시작


@dataclass
class _Dock:
    launch_at: int = 0  # 마지막 예약 배의 진수 예정. 그때 전체 자리가 빈다
    half_free_at: int = 0  # 마지막 예약 배가 반쪽 자리를 비우는 예정


class DockPlan:
    def __init__(self, count: int, half_share: float, flood_minutes: int):
        self.docks = [_Dock() for _ in range(count)]
        self.half_share = half_share
        self.flood = flood_minutes

    def _fit(self, d: _Dock, earliest: int, erection: int) -> tuple[Booking, int]:
        """이 도크에 예약하면 (예약, 반쪽 자리가 비는 예정)."""
        half = round(erection * self.half_share)
        # 반쪽 자리: 자리가 비고, 앞 배 진수 예정까지 반쪽 몫을 마칠 수 있을 때만.
        # 못 마치면 앞 배 진수가 늦어지므로(ADR-003 규칙 5) 앞 배가 나간 뒤 전체 자리로 간다.
        if d.launch_at > earliest and max(earliest, d.half_free_at) + half <= d.launch_at:
            keel = d.launch_at - half  # 반쪽 몫을 앞 배 진수에 맞춰 마치도록 늦게 착공
            return Booking(-1, keel, d.launch_at + erection - half + self.flood, True), d.launch_at
        keel = max(earliest, d.launch_at)
        return Booking(-1, keel, keel + erection + self.flood, False), keel

    def book(self, earliest: int, erection: int) -> Booking:
        """earliest = 가장 이른 착공. 진수 예정이 가장 이른 도크를 예약한다(같으면 번호 순)."""
        best = None
        for i, d in enumerate(self.docks):
            booking, half_free_at = self._fit(d, earliest, erection)
            if best is None or booking.launch < best[0].launch:
                booking.dock = i
                best = (booking, half_free_at)
        booking, half_free_at = best
        self.docks[booking.dock] = _Dock(booking.launch, half_free_at)
        return booking
