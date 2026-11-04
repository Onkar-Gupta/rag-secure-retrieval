import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_data", Path(__file__).resolve().parent.parent / "eval" / "check_data.py")
check_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_data)


def test_data_passes():
    errors, *_ = check_data.check()
    assert errors == []
