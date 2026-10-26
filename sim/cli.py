"""명령줄: python -m sim --seed 0 --until 2031-11-02 [--out-dir out/truth | --out FILE]

포아송 수주가 끝없이 들어오므로(ADR-004) --until 날짜 0시 전까지 돌린다. 기본은 시작부터 5년.
--forever면 멈출 때(Ctrl-C)까지 돈다. 출력은 기본으로 날짜별 파일
out/truth/dt=YYYY-MM-DD/part-0.jsonl, --out FILE이면 파일 하나.
"""

import argparse
from pathlib import Path

from sim import params
from sim.clock import Clock
from sim.engine import Shipyard
from sim.writer import JsonlWriter, PartitionedWriter

DEFAULT_YEARS = 5


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
    with writer:
        try:
            Shipyard(p, args.seed, writer).run(until)
        except KeyboardInterrupt:
            print("멈춤")
    print(f"{writer.count} events → {args.out or args.out_dir}")
    return 0
