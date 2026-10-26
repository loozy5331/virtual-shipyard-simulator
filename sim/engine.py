"""SimPy 엔진(ADR-002). 배와 블록의 생애를 프로세스로 돌리고, 일어난 일을 이벤트로 낸다.

엔진은 출력 방식을 모른다. 이벤트 dict를 sink에 넘길 뿐이다(파일 쓰기는 writer).
"""

import math
import random
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

import simpy

from sim.clock import Clock, days
from sim.dock import FULL, HALF, DockYard
from sim.ids import uuid7
from sim.orders import HullNumbers, arrivals_on, fixed_contracts, hulls, next_contract
from sim.planner import DockPlan

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
    min_start_lag: int
    buffer: int
    block_ids: list[str]
    weights_t: list[float]
    block_durations: dict[str, list[int]]
    block_release: list[int]
    block_mh: dict[str, list[float]]
    durations: dict[str, int]
    start_lag: int = 0  # 계약할 때 도크 계획으로 정한다
    dock: int = 0  # 계약할 때 예약한 도크 순번
    dock_position: str = FULL  # 계약할 때 계획한 도크 자리
    steel_cut: bool = field(default=False)


def block_weights(steel_weight_t: float, n: int) -> list[float]:
    """강재 중량을 블록 n개로 나눈다. 평균의 0.6~1.4배로 고르게 퍼뜨리고, 큰 블록과 작은 블록이
    섞여 나오게 순서를 섞는다. 난수는 쓰지 않는다(무게 분포는 3단계에서 params로)."""
    mean = steel_weight_t / n
    spread = [0.6 + 0.8 * i / (n - 1) for i in range(n)] if n > 1 else [1.0]
    step = next(k for k in range(n // 2 + 1, n + 1) if math.gcd(k, n) == 1)
    return [round(mean * spread[i * step % n], 1) for i in range(n)]


def lognormal_factor(rng: random.Random, cv: float) -> float:
    """평균 1, 변동계수 cv인 로그정규 배수. cv 0이면 1(고정 시간)."""
    if cv == 0:
        return 1.0
    sigma = math.sqrt(math.log(1 + cv * cv))
    return rng.lognormvariate(-sigma * sigma / 2, sigma)


def lognormal_quantile(cv: float, q: float) -> float:
    """lognormal_factor 분포의 q 분위수. 계획을 평균보다 넉넉하게 잡을 때 쓴다."""
    if cv == 0:
        return 1.0
    sigma = math.sqrt(math.log(1 + cv * cv))
    return math.exp(-sigma * sigma / 2 + sigma * NormalDist().inv_cdf(q))


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
        self.seed = seed
        self.rng_ids = random.Random(f"ids-{seed}")
        self.cv = {pid: d["cv"] for pid, d in params["variability"]["duration"].items()}
        quantile = params["orders"]["plan_quantile"]
        self.plan_factor = {pid: lognormal_quantile(cv, quantile) for pid, cv in self.cv.items()}
        self.sink = sink
        self.seq: dict[str, int] = {}

        processes = params["processes"]["processes"]
        self.block_chain = _chain(processes, "block", [])
        self.hull_chain = _chain(processes, "hull", [self.block_chain[-1].id])

        # 자원 하나 = 작업장 번호를 담은 Store. 먼저 기다린 쪽이 먼저 받는다.
        # 작업장 하나에 칸(slots)이 여럿이면 같은 번호를 칸 수만큼 넣는다. 작업장을 번갈아 채운다.
        # 도크는 따로(ADR-003): 전체 자리 + 반쪽 자리, 진수 때 물을 채운다. 납기는 도크 계획으로.
        self.pools: dict[str, simpy.Store] = {}
        self.docks: dict[str, DockYard] = {}
        for name, r in yard["resources"].items():
            ids = [f"{r['prefix']}-{i}" for i in range(1, r["count"] + 1)]
            if "half_share" in r:
                self.docks[name] = DockYard(self.env, ids, days(r["flood_days"]))
                self.half_share = r["half_share"]
                self.dock_plan = DockPlan(r["count"], r["half_share"], days(r["flood_days"]))
                continue
            store = simpy.Store(self.env, capacity=r["count"] * r["slots"])
            store.items.extend(ids * r["slots"])
            self.pools[name] = store

        if self.hull_chain[0].resource not in self.docks:
            raise ValueError("배 공정의 첫째는 도크 공정이어야 한다(도크 계획, ADR-004)")

        self.ship_types = params["ship_types"]["ship_types"]
        self.orders = params["orders"]
        self.mix = yard["annual_plan"]["mix"]
        self.hull_numbers = HullNumbers(self.clock)
        self.env.process(self.order_book())

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
            contracted=order["contracted"],
            min_start_lag=order["min_start_lag"],
            buffer=order["buffer"],
            block_ids=[f"{order['hull_no']}-B{i:03d}" for i in range(1, n + 1)],
            weights_t=weights,
            block_mh={
                p.id: [round(w * ship["block_work"][p.id]["mh_per_t"], 1) for w in weights]
                for p in self.block_chain
            },
            block_release=[days(ship["release_window_days"]) * i // n for i in range(n)],
            block_durations=block_durations,
            durations={k: days(v) for k, v in ship["durations_days"].items()},
        )

    def run(self, until: int | None = None) -> None:
        """until(분) 전까지. None이면 끝까지인데, 포아송 수주가 켜져 있으면 끝이 없다."""
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

    def draw(self, key: str, process: str, mean: int) -> tuple[int, float]:
        """실제 소요 시간(분)과 평균 대비 배수. 난수는 (시드, 개체, 공정)마다 따로 뽑아,
        한 블록의 시간이 바뀌어도 다른 블록의 시간은 그대로다."""
        factor = lognormal_factor(random.Random(f"{self.seed}:{key}:{process}"), self.cv[process])
        return max(1, round(mean * factor)), factor

    def milestone(self, hull: Hull, name: str) -> None:
        self.emit("hull.milestone_reached", hull.hull_no, hull, {"milestone": name})

    # 프로세스

    def plan(self, hull: Hull) -> int:
        """계약할 때 도크 자리를 예약해 착수 대기를 정하고 계약 납기(분)를 낸다(ADR-004).
        블록 기간 = 마지막 블록 착수 + 블록 공정마다 가장 긴 블록. 시간은 공정마다 평균이 아니라
        plan_quantile 분위수로 넉넉하게 잡는다(착공은 가장 늦은 블록에 맞춰지므로)."""
        q = self.plan_factor
        blocks = hull.block_release[-1]
        blocks += sum(round(max(hull.block_durations[p.id]) * q[p.id]) for p in self.block_chain)
        earliest = hull.contracted + hull.min_start_lag + blocks
        erection = self.hull_chain[0].id
        booking = self.dock_plan.book(earliest, round(hull.durations[erection] * q[erection]))
        hull.start_lag = booking.keel - blocks - hull.contracted
        hull.dock = booking.dock
        hull.dock_position = HALF if booking.half else FULL
        after_dock = sum(round(hull.durations[p.id] * q[p.id]) for p in self.hull_chain[1:])
        return booking.launch + after_dock + hull.buffer

    def order_book(self) -> Generator:
        """고정 목록을 계약일마다 받고, 그다음 포아송 도착으로 끝없이 받는다(ADR-004).
        수주 난수는 공정 시간 난수와 따로라, 공정을 바꿔도 수주는 그대로다."""
        for c in fixed_contracts(self.orders):
            yield self.env.timeout(days(c["day"]) - self.env.now)
            self.contract(c)
        if not arrivals_on(self.orders):
            return
        rng = random.Random(f"{self.seed}:orders")
        while True:
            gap, c = next_contract(rng, self.orders["arrivals"], self.mix)
            yield self.env.timeout(max(1, days(gap)))
            self.contract(c)

    def contract(self, c: dict[str, Any]) -> None:
        for order in hulls(self.orders, c, self.env.now, self.hull_numbers):
            self.env.process(self.hull_life(self._hull(order)))

    def hull_life(self, hull: Hull) -> Generator:
        self.emit(
            "order.contracted",
            hull.hull_no,
            hull,
            {
                "ship_type": hull.ship_type,
                "owner": hull.owner,
                "contract_delivery_date": self.clock.date(self.plan(hull)),
                "block_count": len(hull.block_ids),
            },
        )
        yield self.env.timeout(hull.start_lag)

        blocks = [self.env.process(self.block_life(hull, i)) for i in range(len(hull.block_ids))]
        yield self.env.all_of(blocks)

        for p in self.hull_chain:
            yield from self.work(hull, p)
        self.seq.pop(hull.hull_no)  # 인도한 배는 더 이벤트가 없다. 끝없이 돌려도 상태가 쌓이지 않게

    def block_life(self, hull: Hull, i: int) -> Generator:
        yield self.env.timeout(hull.block_release[i])
        for p in self.block_chain:
            yield from self.work(hull, p, i)
        self.seq.pop(hull.block_ids[i])  # 탑재로 넘어간 블록은 더 이벤트가 없다

    def work(self, hull: Hull, p: Process, block: int | None = None) -> Generator:
        """자원을 받아 공정 하나를 하고 돌려준다. 블록 공정이면 block에 블록 순번.
        계획 종료일은 평균 시간으로, 실제 시간은 분포에서 뽑는다. 공수도 같은 배수로 늘고 준다."""
        if p.resource in self.docks:
            yield from self.erect(hull, p, self.docks[p.resource])
            return
        pool = self.pools[p.resource]
        resource_id = yield pool.get()
        mean = hull.durations[p.id] if block is None else hull.block_durations[p.id][block]
        planned_end = self.clock.date(self.env.now + mean)

        if block is None:
            key, block_id = hull.hull_no, None
            started = {"planned_end": planned_end}
        else:
            key = block_id = hull.block_ids[block]
            started = {"planned_end": planned_end, "weight_t": hull.weights_t[block]}
        unit = "block" if block is not None else "hull"
        duration, factor = self.draw(key, p.id, mean)

        self.emit(f"{unit}.process_started", key, hull, started, block_id, p.id, resource_id)
        if "first_start" in p.milestones and not hull.steel_cut:
            hull.steel_cut = True
            self.milestone(hull, p.milestones["first_start"])
        if "start" in p.milestones:
            self.milestone(hull, p.milestones["start"])

        yield self.env.timeout(duration)

        done = {}
        if block is not None:
            done["work_hours"] = round(hull.block_mh[p.id][block] * factor, 1)
        self.emit(f"{unit}.process_completed", key, hull, done, block_id, p.id, resource_id)
        if "end" in p.milestones:
            self.milestone(hull, p.milestones["end"])
        yield pool.put(resource_id)

    def erect(self, hull: Hull, p: Process, docks: DockYard) -> Generator:
        """도크 공정(ADR-003). 계약 때 예약한 도크에 들어간다(ADR-004).
        반쪽 자리면 몫을 짓고 물을 채울 때 앞으로 옮겨 나머지를 짓는다.
        완성되면 물을 채워 진수한다. 반쪽 배가 뜰 수 있을 때까지는 진수를 기다린다."""
        dock, position = yield docks.enter(hull.hull_no, hull.dock, hull.dock_position)
        mean = hull.durations[p.id]
        duration, _ = self.draw(hull.hull_no, p.id, mean)
        started = {
            "planned_end": self.clock.date(self.env.now + mean),
            "dock_position": position,
        }
        self.emit("hull.process_started", hull.hull_no, hull, started, None, p.id, dock.id)
        if "start" in p.milestones:
            self.milestone(hull, p.milestones["start"])

        if position == HALF:
            half = round(duration * self.half_share)
            yield self.env.timeout(half)
            yield docks.half_done(dock)
            duration -= half
        yield self.env.timeout(duration)
        yield docks.finished(dock)

        self.emit("hull.process_completed", hull.hull_no, hull, {}, None, p.id, dock.id)
        if "end" in p.milestones:
            self.milestone(hull, p.milestones["end"])


def simulate(params: dict[str, Any], seed: int, sink: Sink, until: int | None = None) -> None:
    """until(분) 전까지 돌린다. 포아송 수주가 켜져 있으면 until이 있어야 끝난다."""
    if until is None and arrivals_on(params["orders"]):
        raise ValueError("포아송 수주가 켜져 있어 끝이 없다: until을 주거나 Shipyard.run()으로")
    Shipyard(params, seed, sink).run(until)
