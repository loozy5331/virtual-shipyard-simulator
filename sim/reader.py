"""JSON Lines 이벤트 읽기. 파일 하나 또는 날짜별 파일 디렉터리(dt=YYYY-MM-DD/part-0.jsonl)."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def files(path: Path) -> list[Path]:
    path = Path(path)
    if path.is_dir():
        return sorted(path.glob("dt=*/part-*.jsonl"))
    return [path]


def read_events(path: Path, skip: int = 0) -> Iterator[dict[str, Any]]:
    """파일 순서(날짜 순), 파일 안의 줄 순서 그대로. 앞의 skip개는 읽지 않고 건너뛴다
    (체크포인트에서 이어 읽기, ADR-007)."""
    for f in files(path):
        with f.open(encoding="utf-8") as lines:
            for line in lines:
                if skip:
                    skip -= 1
                    continue
                yield json.loads(line)
