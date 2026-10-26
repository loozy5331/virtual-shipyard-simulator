"""SimPy 엔진(ADR-002). 배와 블록의 생애를 프로세스로 돌리고, 일어난 일을 이벤트로 낸다.

엔진은 출력 방식을 모른다. 이벤트 dict를 sink에 넘길 뿐이다(파일 쓰기는 writer).
"""

import math
import random
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any

import simpy

from sim.clock import Clock, days
from sim.ids import uuid7

Event = dict[str, Any]
Sink = Callable[[Event], None]

SOURCE = {"order": "erp", "block": "mes", "hull": "mes", "equipment": "eam"}


@dataclass
class Process:
    id: str
    unit: str
    resource: str
    milestones: dict[str, str]


@dataclass
class Hull:
    hull_no: str
    ship_type: str
    owner: str
    contracted: int
    start_lag: int
    buffer: int
    block_ids: list[str]
    weights_t: list[float]
    block_durations: dict[str, list[int]]
    block_release: list[int]
    durations: dict[str, int]
    steel_cut: bool = field(default=False)


def block_weights(steel_weight_t: float, n: int) -> list[float]:
    """강재 중량을 블록 n개로 나눈다. 평균의 0.6~1.4배로 고르게 퍼뜨리고, 큰 블록과 작은 블록이
    섞여 나오게 순서를 섞는다. 난수는 쓰지 않는다(무게 분포는 3단계에서 params로)."""
    mean = steel_weight_t / n
    spread = [0.6 + 0.8 * i / (n - 1) for i in range(n)] if n > 1 else [1.0]
    step = next(k for k in range(n // 2 + 1, n + 1) if math.gcd(k, n) == 1)
    return [round(mean * spread[i * step % n], 1) for i in range(n)]


def _chain(processes: list[dict[str, Any]], unit: str, first_after: list[str]) -> list[Process]:
    """unit에 속한 공정을 선행 관계 순서로. MVP는 한 줄로 이어진 공정만 받는다."""
    chain = [p for p in processes if p["unit"] == unit]
    after = first_after
    for p in chain:
        if p["after"] != after:
            raise ValueError(f"{p['id']}: 선행 공정은 {after}여야 한다(한 줄 공정)")
        after = [p["id"]]
    return [Process(p["id"], unit, p["resource"], p.get("milestones", {})) for p in chain]


class Shipyard:
    def __init__(self, params: dict[str, Any], seed: int, sink: Sink):
        yard = params["yard"]
        self.env = simpy.Environment()
        self.clock = Clock(yard["epoch"])
        self.run_id = f"{yard['params_version']}-s{seed}"
        self.rng_ids = random.Random(f"ids-{seed}")
        self.sink = sink
        self.seq: dict[str, int] = {}

        processes = params["processes"]["processes"]
        self.block_chain = _chain(processes, "block", [])
        self.hull_chain = _chain(processes, "hull", [self.block_chain[-1].id])

        # 자원 하나 = 작업장 번호를 담은 Store. 먼저 기다린 쪽이 먼저 받는다.
        # 작업장 하나에 칸(slots)이 여럿이면 같은 번호를 칸 수만큼 넣는다. 작업장을 번갈아 채운다.
        self.pools: dict[str, simpy.Store] = {}
        for name, r in yard["resources"].items():
            ids = [f"{r['prefix']}-{i}" for i in range(1, r["count"] + 1)]
            store = simpy.Store(self.env, capacity=r["count"] * r["slots"])
            store.items.extend(ids * r["slots"])
            self.pools[name] = store

        self.ship_types = params["ship_types"]["ship_types"]
        for order in params["orders"]["orders"]:
            self.env.process(self.hull_life(self._hull(order)))

    def _hull(self, order: dict[str, Any]) -> Hull:
        ship = self.ship_types[order["ship_type"]]
        n = ship["block_count"]
        if n > 999:
            raise ValueError(f"{order['ship_type']}: block_id(B001~B999)는 블록 999개까지")
        weights = block_weights(ship["steel_weight_t"], n)
        block_durations = {
            p.id: [
                days(
                    ship["block_work"][p.id]["base_days"]
                    + w * ship["block_work"][p.id]["days_per_100t"] / 100
                )
                for w in weights
            ]
            for p in self.block_chain
        }
        return Hull(
            hull_no=order["hull_no"],
            ship_type=order["ship_type"],
            owner=order["owner"],
            contracted=days(order["contracted_day"]),
            start_lag=days(order["start_lag_days"]),
            buffer=days(order["delivery_buffer_days"]),
            block_ids=[f"{order['hull_no']}-B{i:03d}" for i in range(1, n + 1)],
            weights_t=weights,
            block_release=[days(ship["release_window_days"]) * i // n for i in range(n)],
            block_durations=block_durations,
            durations={k: days(v) for k, v in ship["durations_days"].items()},
        )

    def run(self, until: int | None = None) -> None:
        self.env.run(until=until)

    # 이벤트

    def emit(
        self,
        event_type: str,
        entity_key: str,
        hull: Hull,
        payload: dict[str, Any],
        block_id: str | None = None,
        process: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        now = self.env.now
        self.seq[entity_key] = self.seq.get(entity_key, 0) + 1
        at = self.clock.iso(now)
        self.sink(
            {
                "event_id": uuid7(self.clock.unix_ms(now), self.rng_ids),
                "event_type": event_type,
                "schema_version": 1,
                "source": SOURCE[event_type.split(".")[0]],
                "occurred_at": at,
                "emitted_at": at,  # 정답 로그에는 노이즈가 없다. 방출기가 늦춘다(5단계).
                "run_id": self.run_id,
                "entity_key": entity_key,
                "seq": self.seq[entity_key],
                "hull_no": hull.hull_no,
                "block_id": block_id,
                "process": process,
                "resource_id": resource_id,
                "payload": payload,
            }
        )

    def milestone(self, hull: Hull, name: str) -> None:
        self.emit("hull.milestone_reached", hull.hull_no, hull, {"milestone": name})

    # 프로세스

    def planned_delivery(self, hull: Hull) -> int:
        """계약 납기 = 계약 + 착수 대기 + 공정 시간 + 버퍼. 공정 시간은 마지막 블록이 착수한 뒤
        블록 공정마다 가장 긴 블록만큼, 그다음 배 공정을 더한다(작업장 대기는 없다고 본다).
        4단계에서 수주잔량을 반영한 계산으로 바꾼다."""
        work = hull.block_release[-1]
        work += sum(max(hull.block_durations[p.id]) for p in self.block_chain)
        work += sum(hull.durations[p.id] for p in self.hull_chain)
        return hull.contracted + hull.start_lag + work + hull.buffer

    def hull_life(self, hull: Hull) -> Generator:
        yield self.env.timeout(hull.contracted)
        self.emit(
            "order.contracted",
            hull.hull_no,
            hull,
            {
                "ship_type": hull.ship_type,
                "owner": hull.owner,
                "contract_delivery_date": self.clock.date(self.planned_delivery(hull)),
                "block_count": len(hull.block_ids),
            },
        )
        yield self.env.timeout(hull.start_lag)

        blocks = [self.env.process(self.block_life(hull, i)) for i in range(len(hull.block_ids))]
        yield self.env.all_of(blocks)

        for p in self.hull_chain:
            yield from self.work(hull, p)

    def block_life(self, hull: Hull, i: int) -> Generator:
        yield self.env.timeout(hull.block_release[i])
        for p in self.block_chain:
            yield from self.work(hull, p, i)

    def work(self, hull: Hull, p: Process, block: int | None = None) -> Generator:
        """자원을 받아 공정 하나를 하고 돌려준다. 블록 공정이면 block에 블록 순번."""
        pool = self.pools[p.resource]
        resource_id = yield pool.get()
        duration = hull.durations[p.id] if block is None else hull.block_durations[p.id][block]
        planned_end = self.clock.date(self.env.now + duration)

        if block is None:
            key, block_id = hull.hull_no, None
            started = {"planned_end": planned_end}
        else:
            key = block_id = hull.block_ids[block]
            started = {"planned_end": planned_end, "weight_t": hull.weights_t[block]}
        unit = "block" if block is not None else "hull"

        self.emit(f"{unit}.process_started", key, hull, started, block_id, p.id, resource_id)
        if "first_start" in p.milestones and not hull.steel_cut:
            hull.steel_cut = True
            self.milestone(hull, p.milestones["first_start"])
        if "start" in p.milestones:
            self.milestone(hull, p.milestones["start"])

        yield self.env.timeout(duration)

        done = {"work_hours": duration / 60} if block is not None else {}
        self.emit(f"{unit}.process_completed", key, hull, done, block_id, p.id, resource_id)
        if "end" in p.milestones:
            self.milestone(hull, p.milestones["end"])
        yield pool.put(resource_id)


def simulate(params: dict[str, Any], seed: int, sink: Sink, until: int | None = None) -> None:
    Shipyard(params, seed, sink).run(until)
