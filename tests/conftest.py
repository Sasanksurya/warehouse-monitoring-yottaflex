import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whmon.config import make_config  # noqa: E402
from whmon.pipeline import build_dataset  # noqa: E402
from whmon.export import export_all  # noqa: E402


@pytest.fixture(scope="session")
def starter(tmp_path_factory):
    """One starter dataset (seed 20261022) generated once and shared by read-only tests."""
    out = str(tmp_path_factory.mktemp("starter"))
    w = build_dataset(make_config("starter"))
    manifest, _ = export_all(w, out, ("csv", "sqlite"), "pytest")
    return {"out": out, "world": w, "manifest": manifest}


@pytest.fixture()
def copy_of_starter(starter, tmp_path):
    dst = str(tmp_path / "copy")
    shutil.copytree(starter["out"], dst)
    return dst
