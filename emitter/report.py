"""노이즈 리포트: python -m emitter.report --truth out/truth --emitted out/emitted

정답과 비교한 실제 비율(누락·중복·늦음·순서 어긋남, 지연 분포)과, 방출 로그만 보고 찾은 수
(event_id 중복, 개체별 seq 빈 번호)를 낸다(ADR-005). seq로는 개체의 마지막 이벤트 누락을
찾을 수 없어 따로 센다.
"""

import argparse
import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from statistics import quantiles
from typing import Any

from sim import params
from sim.reader import read_events

LATE_SECONDS = 600  # 이보다 늦게 도착하면 "늦음"으로 센다


def _delay(e: dict[str, Any]) -> float:
    return (
        datetime.fromisoformat(e["emitted_at"]) - datetime.fromisoformat(e["occurred_at"])
    ).total_seconds()


def measure(truth: Iterable[dict[str, Any]], emitted: Iterable[dict[str, Any]]) -> dict[str, Any]:
    truth_ids: set[str] = set()
    truth_last: dict[str, int] = {}  # 개체별 정답의 마지막 seq
    for e in truth:
        truth_ids.add(e["event_id"])
        truth_last[e["entity_key"]] = max(truth_last.get(e["entity_key"], 0), e["seq"])

    lines, seen = 0, set()
    delays, late, swapped = [], 0, 0
    got: dict[str, set[int]] = {}  # 개체별 받은 seq
    top: dict[str, int] = {}  # 개체별 지금까지 받은 가장 큰 seq
    for e in emitted:
        lines += 1
        if e["event_id"] in seen:
            continue  # 중복 사본: event_id로 걸러낸다
        seen.add(e["event_id"])
        d = _delay(e)
        delays.append(d)
        late += d > LATE_SECONDS
        key = e["entity_key"]
        if e["seq"] < top.get(key, 0):
            swapped += 1
        top[key] = max(top.get(key, 0), e["seq"])
        got.setdefault(key, set()).add(e["seq"])

    # 방출 로그만으로 찾은 누락: 받은 가장 큰 seq 아래의 빈 번호
    gaps = sum(top[k] - len(s) for k, s in got.items())
    # 찾을 수 없는 누락: 개체의 마지막 번호들(받은 가장 큰 seq 위)
    tail = sum(last - top.get(k, 0) for k, last in truth_last.items())
    unique = len(seen)
    n = len(truth_ids)
    q = quantiles(delays, n=100) if len(delays) > 1 else [0.0] * 99
    return {
        "truth": n,
        "emitted_lines": lines,
        "dropped": len(truth_ids - seen),
        "duplicated": lines - unique,
        "late": late,
        "out_of_order": swapped,
        "drop_rate": len(truth_ids - seen) / n,
        "duplicate_rate": (lines - unique) / n,
        "late_rate": late / unique,
        "out_of_order_rate": swapped / unique,
        "delay_seconds": {"p50": q[49], "p95": q[94], "p99": q[98], "max": max(delays)},
        "found": {"duplicates_by_event_id": lines - unique, "drops_by_seq_gap": gaps},
        "drops_at_tail": tail,
        "not_in_truth": len(seen - truth_ids),
    }


def render(m: dict[str, Any], noise: dict[str, Any]) -> str:
    def pct(x: float) -> str:
        return f"{x:.2%}"

    d = m["delay_seconds"]
    found = m["found"]
    drops_ok = found["drops_by_seq_gap"] + m["drops_at_tail"] == m["dropped"]
    dups_ok = found["duplicates_by_event_id"] == m["duplicated"]
    rows = [
        f"정답 {m['truth']:,}개 → 방출 {m['emitted_lines']:,}줄",
        "",
        "노이즈(설정 → 실제)",
        f"- 누락: {pct(noise['drop_rate'])} → {pct(m['drop_rate'])} ({m['dropped']:,}개)",
        f"- 중복: {pct(noise['duplicate_rate'])} → {pct(m['duplicate_rate'])}"
        f" ({m['duplicated']:,}개)",
        f"- 늦음(10분 넘게): {pct(noise['delay']['late_rate'])} → {pct(m['late_rate'])}"
        f" ({m['late']:,}개)",
        f"- 순서 어긋남(지연의 결과): {pct(m['out_of_order_rate'])} ({m['out_of_order']:,}개)",
        "",
        f"지연(초) p50 {d['p50']:.0f} · p95 {d['p95']:.0f} · p99 {d['p99']:.0f}"
        f" · 최대 {d['max']:.0f}",
        "",
        "방출 로그만으로 찾기",
        f"- 중복: event_id로 {found['duplicates_by_event_id']:,}개 / 실제 {m['duplicated']:,}개"
        f" {'모두 찾음' if dups_ok else '어긋남'}",
        f"- 누락: seq 빈 번호로 {found['drops_by_seq_gap']:,}개 + 개체의 마지막 번호라 못 찾음"
        f" {m['drops_at_tail']:,}개 / 실제 {m['dropped']:,}개 {'맞음' if drops_ok else '어긋남'}",
    ]
    if m["not_in_truth"]:
        rows.append(f"- 정답에 없는 이벤트 {m['not_in_truth']:,}개")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="emitter.report", description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=Path("out/truth"))
    parser.add_argument("--emitted", type=Path, default=Path("out/emitted"))
    parser.add_argument("--params", type=Path, default=params.PARAMS_DIR)
    parser.add_argument("--json", action="store_true", help="숫자를 JSON으로")
    args = parser.parse_args(argv)

    m = measure(read_events(args.truth), read_events(args.emitted))
    if args.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print(render(m, params.load(args.params)["variability"]["noise"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
