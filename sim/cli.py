"""명령줄: python -m sim --seed 0 --until 2031-11-02 [--out-dir out/truth | --out FILE]

포아송 수주가 끝없이 들어오므로(ADR-004) --until 날짜 0시 전까지 돌린다. 기본은 시작부터 5년.
--forever면 멈출 때(Ctrl-C)까지 돈다. 출력은 기본으로 날짜별 파일
out/truth/dt=YYYY-MM-DD/part-0.jsonl, --out FILE이면 파일 하나.
--speed N이면 가상 시각을 실제 시간에 맞춰(가상 N초 = 실제 1초) --lead-days만큼만 앞서 쓴다.
정답 로그가 --max-gb(기본 10)에 닿으면 그날까지 쓰고 멈춘다(ADR-013).
"""

import argparse
from pathlib import Path

import simpy

from sim import params
from sim.clock import Clock
from sim.engine import Shipyard
from sim.io.writer import JsonlWriter, PartitionedWriter
from sim.pace import Pacer

DEFAULT_YEARS = 5
TICK_MINUTES = 10  # 재생 속도를 맞추는 간격(가상 분)
GB = 1024**3


class Capped:
    """쓴 바이트가 limit에 닿으면 그날까지 쓰고, 다음 날 이벤트가 오면 시뮬레이션을 멈춘다."""

    def __init__(self, writer, limit: int):
        self.writer, self.limit = writer, limit
        self.full: str | None = None  # 상한에 닿은 날

    def __call__(self, event) -> None:
        day = event["occurred_at"][:10]
        if self.full is not None and day != self.full:
            raise simpy.core.StopSimulation(None)
        self.writer(event)
        if self.full is None and self.writer.bytes >= self.limit:
            self.full = day


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim", description="가상 조선소 정답 이벤트 로그를 만든다"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--params", type=Path, default=params.PARAMS_DIR)
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--out-dir", type=Path, default=Path("out/truth"), help="날짜별 파일(기본)")
    out.add_argument("--out", type=Path, help="파일 하나")
    end = parser.add_mutually_exclusive_group()
    end.add_argument(
        "--until", help=f"YYYY-MM-DD, 그날 0시 전까지(기본 시작부터 {DEFAULT_YEARS}년)"
    )
    end.add_argument("--forever", action="store_true", help="멈출 때(Ctrl-C)까지")
    parser.add_argument("--speed", type=float, help="가상 N초 = 실제 1초(1440이면 가상 하루 = 1분)")
    parser.add_argument("--lead-days", type=float, default=1.0, help="--speed일 때 앞서 쓰는 날")
    parser.add_argument("--max-gb", type=float, default=10.0, help="정답 로그 상한(GB)")
    args = parser.parse_args(argv)

    p = params.load(args.params)
    clock = Clock(p["yard"]["epoch"])
    if args.forever:
        until = None
    elif args.until:
        until = clock.minute_of(args.until)
    else:
        start = clock.at(0)
        until = clock.minute_of(start.replace(year=start.year + DEFAULT_YEARS).date().isoformat())

    writer = JsonlWriter(args.out) if args.out else PartitionedWriter(args.out_dir)
    capped = Capped(writer, int(args.max_gb * GB))
    tick = None
    if args.speed:
        pacer = Pacer(args.speed, lead=args.lead_days * 86400, idle=writer.flush)
        tick = lambda minute: pacer(minute * 60)  # noqa: E731
    with writer:
        try:
            Shipyard(p, args.seed, capped).run(until, every=TICK_MINUTES, tick=tick)
        except KeyboardInterrupt:
            print("멈춤")
    if capped.full is not None:
        print(f"정답 로그가 {args.max_gb:g}GB에 닿아 {capped.full}까지 쓰고 멈춤")
    print(f"{writer.count} events → {args.out or args.out_dir}")
    return 0
