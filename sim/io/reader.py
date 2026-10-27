"""JSON Lines 이벤트 읽기. 파일 하나 또는 날짜별 파일 디렉터리(dt=YYYY-MM-DD/part-0.jsonl).
줄바꿈으로 끝나지 않은 마지막 줄은 아직 쓰는 중이라 읽지 않는다."""

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


def files(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_dir():
        return sorted(path.glob("dt=*/part-*.jsonl"))
    return [path]


def _lines(f: Path, pos: int = 0) -> Iterator[tuple[bytes, int]]:
    """pos부터 다 쓴 줄과 그 줄 뒤의 위치."""
    with f.open("rb") as fh:
        fh.seek(pos)
        while (line := fh.readline()).endswith(b"\n"):
            yield line, fh.tell()


def read_events(
    path: Path,
    skip: int = 0,
    follow: bool = False,
    poll: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[dict[str, Any]]:
    """파일 순서(날짜 순), 파일 안의 줄 순서 그대로. 앞의 skip개는 읽지 않고 건너뛴다
    (체크포인트에서 이어 읽기, ADR-007). follow면 끝에 닿아도 멈추지 않고 poll초마다
    새로 쓴 줄과 새 날짜 파일을 기다린다(끝없는 정답 로그 따라 읽기, ADR-013)."""
    if not follow:
        for f in files(path):
            for line, _ in _lines(f):
                if skip:
                    skip -= 1
                    continue
                yield json.loads(line)
        return
    done: set[Path] = set()  # 다 읽은 파일. 쓰는 쪽은 다음 날짜 파일을 열기 전에 앞 파일을 닫는다
    current, pos = None, 0
    while True:
        # 목록을 먼저 본다: 다음 날짜 파일이 보였다면 지금 파일은 이미 닫혔다
        pending = [f for f in files(path) if f.exists() and f not in done]
        if not pending:
            sleep(poll)
            continue
        f = pending[0]
        if f != current:
            current, pos = f, 0
        for line, end in _lines(f, pos):
            pos = end  # 다음에는 다 읽은 줄 뒤에서 이어 읽는다
            if skip:
                skip -= 1
                continue
            yield json.loads(line)
        if len(pending) > 1:
            done.add(f)
        else:
            sleep(poll)
