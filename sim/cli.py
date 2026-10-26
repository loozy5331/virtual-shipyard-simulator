"""명령줄: python -m sim --seed 0 --out out/truth.jsonl"""

import argparse
from pathlib import Path

from sim import params
from sim.engine import simulate
from sim.writer import JsonlWriter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sim", description="가상 조선소 정답 이벤트 로그를 만든다"
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--params", type=Path, default=params.PARAMS_DIR)
    parser.add_argument("--out", type=Path, default=Path("out/truth.jsonl"))
    args = parser.parse_args(argv)

    with JsonlWriter(args.out) as writer:
        simulate(params.load(args.params), args.seed, writer)
    print(f"{writer.count} events → {args.out}")
    return 0
