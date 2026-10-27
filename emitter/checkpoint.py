"""체크포인트에서 이어 보내기(ADR-007).

체크포인트 = 읽은 정답 이벤트 수 + 방출기 상태. 정답 로그의 날짜가 바뀔 때마다, 보낸 것을
모두 비우고(flush, 브로커 확인) 저장한다. 다시 켜면 상태를 불러오고 그만큼 건너뛰어 이어 읽는다.
노이즈는 이벤트별 난수라 끊김 없이 돈 것과 같은 메시지가 나간다. 마지막 체크포인트 뒤에
보낸 것은 한 번 더 갈 수 있다(at-least-once).
"""

import os
import pickle
from collections.abc import Callable
from pathlib import Path

from emitter.noise import Emitter
from sim.io.reader import read_events

VERSION = 1


def save(path: Path, read: int, emitter: Emitter) -> None:
    """쓰다가 멈춰도 앞 체크포인트가 남도록 임시 파일에 쓰고 바꿔 넣는다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(pickle.dumps({"version": VERSION, "read": read, "state": emitter.state()}))
    os.replace(tmp, path)


def load(path: Path) -> tuple[int, dict] | None:
    """(읽은 정답 이벤트 수, 방출기 상태). 체크포인트가 없으면 None.
    자기가 쓴 로컬 파일만 읽는다(pickle)."""
    path = Path(path)
    if not path.exists():
        return None
    data = pickle.loads(path.read_bytes())
    if data["version"] != VERSION:
        raise ValueError(f"{path}: 체크포인트 버전 {data['version']}은 읽을 수 없다")
    return data["read"], data["state"]


def run(
    truth: Path,
    emitter: Emitter,
    flush: Callable[[], None],
    checkpoint: Path | None = None,
    follow: bool = False,
) -> int:
    """정답 로그를 방출기에 흘린다. checkpoint가 있으면 거기서 이어 읽고, 날짜가 바뀔 때마다
    flush 후 저장한다. follow면 정답 로그를 끝없이 따라 읽는다(ADR-013).
    반환값은 이번에 이어 읽기 시작한 위치(정답 이벤트 수)."""
    start = 0
    if checkpoint is not None and (saved := load(checkpoint)) is not None:
        start, state = saved
        emitter.restore(state)
    read, day = start, None
    for event in read_events(truth, skip=start, follow=follow):
        today = event["occurred_at"][:10]
        if checkpoint is not None and day is not None and today != day:
            flush()
            save(checkpoint, read, emitter)
        day = today
        emitter(event)
        read += 1
    emitter.close()
    flush()
    return start
