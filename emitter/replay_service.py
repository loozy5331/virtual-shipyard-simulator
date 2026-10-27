"""재발행 서비스: python -m emitter.replay_service --requests-dir requests [--once]

플랫폼이 요청 디렉터리에 둔 요청 파일(*.jsonl, schemas/replay_request.json)을 살펴 이름 순서로
하나씩 재발행한다(ADR-012). 처리한 파일은 done/으로 옮긴다. 형식이 틀려 아무것도 보내지 않은
파일은 failed/로 옮기고 까닭을 <이름>.error에 쓴다. 다 쓴 파일만 처리하도록 플랫폼은 다른
이름(예: .tmp)으로 쓰고 바꿔 넣는다.

처리 시각(emitted_at)은 방출 로그에서 가장 늦은 도착 시각 + 1초다. 방출기의 가상 시각을 따르고,
요청마다 달라 재발행 파일이 겹치지 않는다. 방출 로그가 비어 있으면 처리하지 않고 기다린다.
"""

import argparse
import json
import os
import signal
import time
from datetime import datetime, timedelta
from pathlib import Path

from emitter.noise import KST
from emitter.replay import read_requests, replay, write
from sim.reader import read_events

DONE, FAILED = "done", "failed"


def clock(emitted: Path) -> datetime | None:
    """방출 로그에서 가장 늦은 도착 시각. 가장 늦은 날짜 디렉터리만 본다. 비어 있으면 None.
    방출기가 쓰고 있는 마지막 줄(줄바꿈 전)은 건너뛴다."""
    for day in sorted(emitted.glob("dt=*"), reverse=True):
        latest = None
        for f in day.glob("part-*.jsonl"):
            with f.open(encoding="utf-8") as lines:
                for line in lines:
                    if line.endswith("\n"):
                        t = datetime.fromisoformat(json.loads(line)["emitted_at"])
                        latest = t if latest is None else max(latest, t)
        if latest is not None:
            return latest
    return None


def process(path: Path, truth: Path, emitted: Path) -> str | None:
    """요청 파일 하나를 처리하고 옮긴다. 옮긴 곳(done, failed), 기다리면 None."""
    try:
        requests = read_requests(path)
    except ValueError as e:
        _move(path, FAILED).with_name(path.name + ".error").write_text(f"{e}\n", encoding="utf-8")
        print(f"{path.name}: 보내지 않음 → {FAILED}/ ({e})")
        return FAILED
    if (latest := clock(emitted)) is None:
        return None
    at = (latest + timedelta(seconds=1)).astimezone(KST)
    events, unknown = replay(read_events(truth), requests, at.isoformat(timespec="seconds"))
    out = write(events, emitted, at)
    _move(path, DONE)
    note = f", 정답에 없는 요청 {len(unknown)}개(보내지 않음)" if unknown else ""
    print(f"{path.name}: 요청 {len(requests)}개 → 재발행 {len(events)}개 → {out}{note}")
    return DONE


def _move(path: Path, to: str) -> Path:
    dest = path.parent / to / path.name
    dest.parent.mkdir(exist_ok=True)
    os.replace(path, dest)
    return dest


def scan(requests_dir: Path, truth: Path, emitted: Path, stop=lambda: False) -> int:
    """기다리는 요청 파일을 이름 순서로 처리한다. 처리한 수."""
    n = 0
    for path in sorted(requests_dir.glob("*.jsonl")):
        if stop() or process(path, truth, emitted) is None:
            break
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="emitter.replay_service", description=__doc__.splitlines()[0]
    )
    parser.add_argument("--requests-dir", type=Path, default=Path("out/requests"))
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--out-dir", type=Path, default=Path("out/emitted"))
    parser.add_argument("--interval", type=float, default=5.0, help="살펴보는 간격(초)")
    parser.add_argument("--once", action="store_true", help="한 번 살펴보고 끝낸다")
    args = parser.parse_args(argv)

    args.requests_dir.mkdir(parents=True, exist_ok=True)
    stopping = []  # 컨테이너가 멈출 때(SIGTERM) 처리 중인 파일은 끝내고 나간다
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    print(f"재발행 서비스: {args.requests_dir} 살펴보기({args.interval:g}초마다)", flush=True)
    while not stopping:
        scan(args.requests_dir, args.truth, args.out_dir, stop=lambda: bool(stopping))
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
