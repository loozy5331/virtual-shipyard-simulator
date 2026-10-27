"""정답 로그 읽기: 쓰는 중인 줄은 읽지 않고, follow면 새 줄과 새 날짜 파일을 따라 읽는다."""

import json

from sim.io.reader import read_events


def _line(n):
    return json.dumps({"n": n}) + "\n"


def test_incomplete_last_line_is_not_read(tmp_path):
    f = tmp_path / "dt=2029-01-01" / "part-0.jsonl"
    f.parent.mkdir()
    f.write_text(_line(1) + '{"n": 2')
    assert list(read_events(tmp_path)) == [{"n": 1}]


def test_follow_reads_appended_lines_and_new_days(tmp_path):
    d1 = tmp_path / "truth" / "dt=2029-01-01" / "part-0.jsonl"
    d2 = tmp_path / "truth" / "dt=2029-01-02" / "part-0.jsonl"

    def append(f, text):
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a") as fh:
            fh.write(text)

    # 읽는 쪽이 기다릴 때마다 쓰는 쪽이 한 걸음씩 쓴다. 처음에는 디렉터리도 없다
    steps = iter(
        [
            lambda: append(d1, _line(1) + '{"n": '),  # 2는 쓰는 중
            lambda: append(d1, "2}\n"),
            lambda: append(d2, _line(3)),  # 다음 날 파일이 생기면 앞 파일은 끝났다
            lambda: append(d2, _line(4)),
        ]
    )

    def sleep(_):
        next(steps)()

    got = read_events(tmp_path / "truth", skip=1, follow=True, sleep=sleep)
    assert [next(got)["n"] for _ in range(3)] == [2, 3, 4]
