"""이벤트를 JSON Lines 파일로 쓴다. 한 줄 = 이벤트 하나, 키 순서는 봉투 순서 그대로."""

import json
from pathlib import Path
from typing import Any


class JsonlWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.count = 0
        self._file = None

    def __enter__(self) -> "JsonlWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", newline="\n")
        return self

    def __exit__(self, *exc: object) -> None:
        self._file.close()

    def __call__(self, event: dict[str, Any]) -> None:
        self._file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.count += 1
