"""명령줄: python -m emitter --truth out/truth --seed 0 [--out-dir out/emitted | --out FILE]
        python -m emitter --sink kafka [--bootstrap HOST:PORT] [--checkpoint FILE] [--copy-dir DIR]

정답 로그(파일 하나 또는 날짜별 디렉터리)를 읽어 노이즈를 섞은 방출 로그를 도착 순서로
쓴다(ADR-005). 날짜별 파일의 날짜는 도착 날짜다. Kafka로 보낼 때는 체크포인트에서 이어 보내고,
--copy-dir에 채점용 사본을 함께 쓴다(ADR-007).
"""

import argparse
from contextlib import nullcontext
from pathlib import Path

from emitter.checkpoint import run
from emitter.noise import Emitter
from sim import params
from sim.io.writer import JsonlWriter, PartitionedWriter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emitter", description="정답 로그에 노이즈를 섞는다")
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--seed", type=int, default=0, help="노이즈 시드(시뮬레이션 시드와 따로)")
    parser.add_argument("--params", type=Path, default=params.PARAMS_DIR)
    parser.add_argument("--sink", choices=["file", "kafka"], default="file")
    out = parser.add_mutually_exclusive_group()
    out.add_argument("--out-dir", type=Path, default=Path("out/emitted"), help="날짜별 파일(기본)")
    out.add_argument("--out", type=Path, help="파일 하나")
    kafka = parser.add_argument_group("kafka")
    kafka.add_argument("--bootstrap", default="localhost:9092")
    kafka.add_argument("--checkpoint", type=Path, help="이어 보내기 체크포인트 파일")
    kafka.add_argument("--copy-dir", type=Path, help="채점용 사본(날짜별 파일)")
    args = parser.parse_args(argv)
    if args.sink == "file" and (args.checkpoint or args.copy_dir):
        parser.error("--checkpoint, --copy-dir은 --sink kafka에서만 쓴다")

    p = params.load(args.params)["variability"]
    noise, lookback = p["noise"], p["manifest"]["lookback_days"]
    if args.sink == "kafka":
        return _kafka(args, noise, lookback)
    if args.out:
        writer = JsonlWriter(args.out)
        sink = lambda event, _date: writer(event)  # noqa: E731
    else:
        writer = PartitionedWriter(args.out_dir)
        sink = writer.write
    with writer:
        run(args.truth, Emitter(noise, args.seed, sink, lookback), flush=lambda: None)
    print(f"{writer.count} events → {args.out or args.out_dir}")
    return 0


def _kafka(args: argparse.Namespace, noise: dict, lookback: int) -> int:
    from emitter.kafka import KafkaSink

    producer = KafkaSink(args.bootstrap)
    resuming = args.checkpoint is not None and args.checkpoint.exists()
    copy = PartitionedWriter(args.copy_dir, append=resuming) if args.copy_dir else None
    first: list[str] = []  # 이번에 처음 보낸 메시지의 도착 시각

    def sink(event, date):
        if not first:
            first.append(event["emitted_at"])
        producer(event, date)
        if copy is not None:
            copy.write(event, date)

    def flush():
        producer.flush()
        if copy is not None:
            copy.flush()

    with copy or nullcontext():
        start = run(args.truth, Emitter(noise, args.seed, sink, lookback), flush, args.checkpoint)
    print(f"{producer.count} messages → kafka {args.bootstrap}")
    if start and first:
        # 앞 실행이 마지막 체크포인트 뒤에 보낸 것은 한 번 더 갔다(at-least-once)
        print(f"체크포인트에서 이어 보냄: 정답 {start}개 건너뜀, 첫 메시지 도착 {first[0]}부터")
    return 0
