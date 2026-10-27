"""방출기 재생 속도(ADR-013): 속도를 줘도 같은 메시지가 같은 순서로 나간다."""

from emitter.cli import main as emitter_main
from sim.cli import main as sim_main


def test_paced_output_is_same_as_unpaced(tmp_path):
    truth = tmp_path / "truth"
    sim_main(["--until", "2027-01-01", "--out-dir", str(truth)])
    for name, extra in [("fast", []), ("paced", ["--speed", "1e12"])]:
        emitter_main(["--truth", str(truth), "--out-dir", str(tmp_path / name), *extra])
    fast = sorted(p.relative_to(tmp_path / "fast") for p in (tmp_path / "fast").rglob("*.jsonl"))
    for rel in fast:
        assert (tmp_path / "paced" / rel).read_bytes() == (tmp_path / "fast" / rel).read_bytes()
    assert fast
