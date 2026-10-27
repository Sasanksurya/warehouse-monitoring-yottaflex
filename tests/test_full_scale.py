"""Full baseline volume. Run with:  pytest -m slow"""
import pytest

from whmon.config import make_config
from whmon.export import export_all
from whmon.pipeline import build_dataset
from whmon.validate import validate


@pytest.mark.slow
def test_full_volume_and_validation(tmp_path):
    w = build_dataset(make_config("full"))
    m, _ = export_all(w, str(tmp_path), ("csv",), "pytest")
    c = m["row_counts"]
    assert c["warehouse"] == 10 and c["zone"] == 100 and c["sensor"] == 500 and c["inventory_lot"] == 10000
    assert c["sensor_reading"] >= 1_000_000
    assert validate(str(tmp_path)).errors == 0
