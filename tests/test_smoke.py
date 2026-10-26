import emitter
import sim


def test_packages_import():
    assert sim.__version__ == "0.0.1"
    assert emitter.__doc__
