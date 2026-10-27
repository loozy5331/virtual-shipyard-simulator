"""재발행: python -m emitter.replay --requests FILE --at 2031-11-03T09:00:00 [--sink kafka]

재발행 요청(한 줄에 {"entity_key", "seq"}, schemas/replay_request.json)을 정답 로그에서 찾아
다시 보낸다(ADR-006). 요청은 플랫폼이 만든다(ADR-008). 형식이 틀린 줄이 있으면 보내지 않는다.
event_id·occurred_at·payload는 그대로, emitted_at만 처리 시각(--at, +09:00)이다. 노이즈는 없다.
출력은 방출 로그의 dt=<처리 날짜>/part-replay-<처리 시각>.jsonl이라 방출 로그와 함께 읽힌다.
--sink kafka면 처음 방출과 같은 토픽·키로 보내고, 브로커 확인을 받은 뒤 그 파일을 사본으로 쓴다.
"""

import argparse
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from emitter.noise import KST
from sim.reader import read_events
from sim.schema import request_validator

Event = dict[str, Any]


def replay(
    truth: Iterable[Event], requests: Iterable[dict[str, Any]], at: str
) -> tuple[list[Event], list[dict[str, Any]]]:
    """(재발행 이벤트, 정답에 없어 보내지 못한 요청). 재발행은 정답의 순서(occurred_at)대로."""
    wanted = {(r["entity_key"], r["seq"]) for r in requests}
    found, out = set(), []
    for e in truth:
        key = (e["entity_key"], e["seq"])
        if key in wanted and key not in found:
            found.add(key)
            out.append({**e, "emitted_at": at})
    unknown = [{"entity_key": k, "seq": s} for k, s in sorted(wanted - found)]
    return out, unknown


def read_requests(path: Path) -> list[dict[str, Any]]:
    """요청 파일을 읽어 스키마로 검증한다. 틀린 줄이 있으면 줄 번호와 함께 ValueError."""
    requests = []
    with path.open(encoding="utf-8") as lines:
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{n}: JSON이 아니다: {e}") from e
            if errors := [e.message for e in request_validator().iter_errors(r)]:
                raise ValueError(f"{path}:{n}: 재발행 요청 형식이 아니다: {'; '.join(errors)}")
            requests.append(r)
    return requests


def write(events: list[Event], out_dir: Path, at: datetime) -> Path:
    """방출 로그의 dt=<처리 날짜>/part-replay-<처리 시각>.jsonl에 쓴다."""
    path = out_dir / f"dt={at.date()}" / f"part-replay-{at:%Y%m%dT%H%M%S}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def publish(events: list[Event], out_dir: Path, at: datetime, kafka=None) -> Path:
    """kafka(KafkaSink)가 있으면 먼저 보내고 브로커 확인을 받는다. 그다음 파일을 쓴다.
    보낸 뒤 파일을 쓰기 전에 멈추면 같은 시각으로 한 번 더 보낸다(at-least-once)."""
    if kafka is not None:
        for e in events:
            kafka(e, str(at.date()))
        kafka.flush()
    return write(events, out_dir, at)


def kafka_sink(sink: str, bootstrap: str):
    if sink != "kafka":
        return None
    from emitter.kafka import KafkaSink

    return KafkaSink(bootstrap)


def add_sink_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sink", choices=["file", "kafka"], default="file")
    parser.add_argument("--bootstrap", default="localhost:9092", help="--sink kafka의 브로커")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emitter.replay", description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--at", required=True, help="처리 시각 YYYY-MM-DDTHH:MM:SS(+09:00)")
    parser.add_argument("--out-dir", type=Path, default=Path("out/emitted"), help="kafka면 사본")
    add_sink_args(parser)
    args = parser.parse_args(argv)

    at = datetime.fromisoformat(args.at).replace(tzinfo=KST)
    try:
        requests = read_requests(args.requests)
    except ValueError as e:
        parser.error(str(e))
    events, unknown = replay(read_events(args.truth), requests, at.isoformat(timespec="seconds"))
    path = publish(events, args.out_dir, at, kafka_sink(args.sink, args.bootstrap))
    to = f"kafka {args.bootstrap}, 사본 {path}" if args.sink == "kafka" else str(path)
    print(f"요청 {len(requests)}개 → 재발행 {len(events)}개 → {to}")
    if unknown:
        print(f"정답에 없는 요청 {len(unknown)}개(보내지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
