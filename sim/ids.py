"""결정적 UUID v7. 시각 부분은 occurred_at, 난수 부분은 시드를 받은 난수열에서 뽑는다."""

import random
import uuid


def uuid7(unix_ms: int, rng: random.Random) -> str:
    rand_a = rng.getrandbits(12)
    rand_b = rng.getrandbits(62)
    value = (unix_ms & (1 << 48) - 1) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return str(uuid.UUID(int=value))
