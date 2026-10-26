"""명령줄: python -m emitter --truth out/truth --seed 0 [--out-dir out/emitted | --out FILE]

정답 로그(파일 하나 또는 날짜별 디렉터리)를 읽어 노이즈를 섞은 방출 로그를 도착 순서로
쓴다(ADR-005). 날짜별 파일의 날짜는 도착 날짜다.
"""

import argparse
from pathlib import Path

from emitter.noise import Emitter
from sim import params
from sim.reader import read_events
from sim.writer import JsonlWriter, PartitionedWriter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emitter", description="정답 로그에 노이즈를 섞는다")
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--seed", type=int, default=0, help="노이즈 시드(시뮬레이션 시드와 따로)")
    parser.add_argument("--params", type=Path, default=params.PARAMS_DIR)
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--out-dir", type=Path, default=Path("out/emitted"), help="날짜별 파일(기본)")
    out.add_argument("--out", type=Path, help="파일 하나")
    args = parser.parse_args(argv)

    p = params.load(args.params)["variability"]
    noise, lookback = p["noise"], p["manifest"]["lookback_days"]
    if args.out:
        writer = JsonlWriter(args.out)
        sink = lambda event, _date: writer(event)  # noqa: E731
    else:
        writer = PartitionedWriter(args.out_dir)
        sink = writer.write
    with writer:
        emitter = Emitter(noise, args.seed, sink, lookback)
        for event in read_events(args.truth):
            emitter(event)
        emitter.close()
    print(f"{writer.count} events → {args.out or args.out_dir}")
    return 0
