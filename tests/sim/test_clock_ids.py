import random
import uuid

import pytest

from sim.clock import Clock, days
from sim.ids import uuid7


def test_clock_formats_kst():
    clock = Clock("2026-11-02T08:00:00+09:00")
    assert clock.iso(days(1) + 90) == "2026-11-03T09:30:00+09:00"
    assert clock.date(days(30)) == "2026-12-02"


def test_clock_rejects_other_offset():
    with pytest.raises(ValueError):
        Clock("2026-11-02T08:00:00+00:00")


def test_uuid7_is_deterministic_and_time_ordered():
    a = [uuid7(ms, random.Random(1)) for ms in (1_000, 2_000)]
    b = [uuid7(ms, random.Random(1)) for ms in (1_000, 2_000)]
    assert a == b
    assert a[0] < a[1]
    parsed = uuid.UUID(a[0])
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122
