"""세미 탠덤 도크(ADR-003). 도크 하나에 전체 자리와 반쪽 자리가 있다.

배 쪽(엔진)이 부르는 순서:
    dock, position = yield docks.enter(key)
    position == "half"면: 몫을 짓고 → yield docks.half_done(dock) (앞으로 옮겨질 때까지)
    나머지를 짓고 → yield docks.finished(dock) (물을 채워 진수할 때까지)
"""

from collections.abc import Generator, Hashable
from dataclasses import dataclass, field

import simpy

FULL, HALF = "full", "half"


@dataclass
class Dock:
    id: str
    full: Hashable | None = None
    half: Hashable | None = None
    half_ready: bool = False  # 반쪽 배가 몫을 마쳐 뜰 수 있다
    launch: simpy.Event | None = None  # 전체 자리 배가 완성되어 진수를 기다린다
    move: simpy.Event | None = None  # 반쪽 배가 앞으로 옮겨지기를 기다린다
    flooding: bool = False
    launched: list[Hashable] = field(default_factory=list)


class DockYard:
    def __init__(self, env: simpy.Environment, ids: list[str], flood_minutes: int):
        self.env = env
        self.docks = [Dock(i) for i in ids]
        self.flood_minutes = flood_minutes
        self.waiting: list[tuple[Hashable, simpy.Event]] = []

    def enter(self, key: Hashable) -> simpy.Event:
        """도크 자리를 기다린다. 값은 (dock, "full" | "half")."""
        event = self.env.event()
        self.waiting.append((key, event))
        self._admit()
        return event

    def half_done(self, dock: Dock) -> simpy.Event:
        """반쪽 몫을 마쳤다. 물을 채워 전체 자리로 옮겨지면 이벤트가 끝난다."""
        dock.half_ready = True
        dock.move = self.env.event()
        event = dock.move
        self._flood_if_ready(dock)
        return event

    def finished(self, dock: Dock) -> simpy.Event:
        """전체 자리 배가 완성됐다. 물을 채워 진수하면 이벤트가 끝난다."""
        dock.launch = self.env.event()
        event = dock.launch
        self._flood_if_ready(dock)
        return event

    def _admit(self) -> None:
        """먼저 기다린 배부터. 맨 앞 배가 못 들어가면 뒤 배도 못 들어간다(자격이 같다)."""
        while self.waiting:
            key, event = self.waiting[0]
            spot = self._spot()
            if spot is None:
                return
            dock, position = spot
            setattr(dock, position, key)
            self.waiting.pop(0)
            event.succeed((dock, position))

    def _spot(self) -> tuple[Dock, str] | None:
        for dock in self.docks:
            if not dock.flooding and dock.full is None and dock.half is None:
                return dock, FULL
        for dock in self.docks:
            if not dock.flooding and dock.full is not None and dock.half is None:
                return dock, HALF
        return None

    def _flood_if_ready(self, dock: Dock) -> None:
        if dock.flooding:
            return
        # 반쪽 배는 전체 자리에 배가 있을 때만 들어오고, 전체 자리 배는 물을 채울 때만 나가며
        # 그때 반쪽 배도 앞으로 옮겨진다. 그래서 물을 채우는 까닭은 진수 하나뿐이다.
        if dock.launch is not None and (dock.half is None or dock.half_ready):
            dock.flooding = True
            self.env.process(self._flood(dock))

    def _flood(self, dock: Dock) -> Generator:
        yield self.env.timeout(self.flood_minutes)
        launch, move = dock.launch, dock.move
        dock.launched.append(dock.full)
        dock.full, dock.half = dock.half, None
        dock.half_ready, dock.launch, dock.move, dock.flooding = False, None, None, False
        launch.succeed()
        if move is not None:
            move.succeed()
        self._admit()
