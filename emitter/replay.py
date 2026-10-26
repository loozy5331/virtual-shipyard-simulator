"""재발행: python -m emitter.replay --requests out/requests.jsonl --at 2031-11-03T09:00:00

재발행 요청(한 줄에 {"entity_key", "seq"})을 정답 로그에서 찾아 다시 보낸다(ADR-006).
event_id·occurred_at·payload는 그대로, emitted_at만 처리 시각(--at, +09:00)이다. 노이즈는 없다.
출력은 방출 로그의 dt=<처리 날짜>/part-replay-<처리 시각>.jsonl이라 방출 로그와 함께 읽힌다.
"""

import argparse
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from emitter.noise import KST
from sim.reader import read_events

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emitter.replay", description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--at", required=True, help="처리 시각 YYYY-MM-DDTHH:MM:SS(+09:00)")
    parser.add_argument("--out-dir", type=Path, default=Path("out/emitted"))
    args = parser.parse_args(argv)

    at = datetime.fromisoformat(args.at).replace(tzinfo=KST)
    with args.requests.open(encoding="utf-8") as lines:
        requests = [json.loads(line) for line in lines if line.strip()]
    events, unknown = replay(read_events(args.truth), requests, at.isoformat(timespec="seconds"))

    path = args.out_dir / f"dt={at.date()}" / f"part-replay-{at:%Y%m%dT%H%M%S}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"요청 {len(requests)}개 → 재발행 {len(events)}개 → {path}")
    if unknown:
        print(f"정답에 없는 요청 {len(unknown)}개(보내지 않음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
