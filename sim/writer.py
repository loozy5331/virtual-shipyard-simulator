"""이벤트를 JSON Lines로 쓴다. 한 줄 = 이벤트 하나, 키 순서는 봉투 순서 그대로.
파일 하나(JsonlWriter) 또는 날짜별 파일(PartitionedWriter)."""

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


class PartitionedWriter:
    """날짜별 파일 root/dt=YYYY-MM-DD/part-0.jsonl(ADR-004). 날짜는 occurred_at의 날짜(+09:00).
    이벤트가 시각 순서로 오므로 한 번에 파일 하나만 열고, 날짜가 바뀌면 앞 파일을 닫는다.
    닫힌 날짜 파일은 다시 쓰지 않는다(수집 쪽이 닫힌 날짜부터 가져가도 된다)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.count = 0
        self.date: str | None = None
        self._file = None

    def __enter__(self) -> "PartitionedWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        if self._file is not None:
            self._file.close()

    def path(self, date: str) -> Path:
        return self.root / f"dt={date}" / "part-0.jsonl"

    def __call__(self, event: dict[str, Any]) -> None:
        date = event["occurred_at"][:10]
        if date != self.date:
            if self.date is not None and date < self.date:
                raise ValueError(f"이벤트 시각이 거꾸로 간다: {self.date} 다음 {date}")
            if self._file is not None:
                self._file.close()
            path = self.path(date)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("w", encoding="utf-8", newline="\n")
            self.date = date
        self._file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.count += 1
