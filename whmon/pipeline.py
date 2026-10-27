"""End-to-end build: masters -> lots -> telemetry -> rule engine -> workflow."""
from __future__ import annotations

from .config import Config
from .util import World, Clock
from .masters import build_masters
from .lots import build_lots
from .telemetry import build_telemetry
from .detect import detect
from .workflow import run_workflow


def build_dataset(cfg: Config) -> World:
    w = World(cfg, Clock(cfg))
    build_masters(w)      # parents first
    build_lots(w)
    build_telemetry(w)    # children / events with valid parent ids
    detect(w)             # alarms + explicit gaps derived from the telemetry
    run_workflow(w)       # inspections, remediations, histories, derived lot state
    # ground truth: stable ids, ordered, kept separate from input tables
    w.truth.sort(key=lambda t: (t["window_start"], t["issue_type"], t["entity_id"]))
    for i, t in enumerate(w.truth, start=1):
        t["truth_id"] = f"GT-{i:06d}"
    return w
