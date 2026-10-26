"""3단계 완료 기준: 시드 여러 개의 구간 평균 ≈ 마일스톤 기간표(±10%)."""

import pytest

from sim import params
from sim.periods import TABLE, main, period_means


@pytest.mark.parametrize("ship_type", list(TABLE))
def test_period_means_near_table(ship_type):
    got = period_means(params.load(), ship_type, range(20))
    assert got == pytest.approx(TABLE[ship_type], rel=0.1)


def test_cli_prints_every_period(capsys):
    main(["--seeds", "1"])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 + 3 * len(TABLE)
