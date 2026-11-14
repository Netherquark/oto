#!/usr/bin/env python3
"""Shared scaffolding for the Phase 1 production-integration tests.

Owns: the one-row Cijk CSV fixture (``HEADER``), the ``TensileDriver`` stand-in
scheduler (``_StubScheduler``), and the ``Harness`` base class every Phase 1
test builds on (temp dir, one-phase ``phases.yaml``, sqlite registry, analytics
engine, mutator). ``tests/test_phase1_*.py`` import these; the repo root is
already on ``sys.path`` via ``tests/conftest.py``.
Does NOT own: any assertions or driver internals (those live in the tests).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from oto.ledger.mutator import Mutator
from oto.ledger.registry import SQLiteRegistry
from oto.metrics.benchmark_analytics import AnalyticsEngine
from oto.runners.paths import results_rel

HEADER = (" SizeI , SizeJ , SizeL , Cijk_A , WinnerFreq \n"
          " 128 , 128 , 128 , 12.5 , 3 \n")


class _StubScheduler:
    """Minimal CandidateGenerator stand-in: the driver only needs these."""

    family_decks = {"SS": [{"MacroTile": "64x64x16", "ThreadTile": "4x4"}]}

    def emit_candidate(self, phase_id, label, dtype, shapes, template, knobs):
        from oto.ledger.registry import fingerprint_config
        from oto.tensile.candidate import CandidateConfig
        full = {**template, **knobs}
        return CandidateConfig(
            phase_id=phase_id, label=label, dtype=dtype, shapes=list(shapes),
            template=dict(template), knobs=dict(knobs),
            fingerprint=fingerprint_config(full))

    def validate_config(self, config):
        return True, ""

    def mutate_winner(self, config, budget):
        return []


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_phase1_integration_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / results_rel("")).mkdir()
        (self.tmp / "phases.yaml").write_text(yaml.safe_dump([
            {"phase_id": "phase_curated_0", "label": "curated",
             "dtype": "s", "shapes": ["128x128x128"], "fp": "fpCURATED",
             "config": {"Architecture": "gfx90c", "DataType": "S"}},
        ]))
        self.registry = SQLiteRegistry(self.tmp)
        self.analytics = AnalyticsEngine(self.registry, self.tmp)
        self.mutator = Mutator(self.registry, self.tmp, self.analytics)

    def write_overlay(self, run_id, phases):
        d = self.tmp / results_rel("overlays")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"phases.{run_id}.overlay.yaml").write_text(
            yaml.safe_dump({"run_id": run_id, "phases": phases}))

    def write_seed_overlay(self, phases):
        d = self.tmp / results_rel("overlays")
        d.mkdir(parents=True, exist_ok=True)
        (d / "phases.seed.overlay.yaml").write_text(
            yaml.safe_dump({"run_id": "seed", "phases": phases}))

    def read_phases_yaml(self):
        return yaml.safe_load((self.tmp / "phases.yaml").read_text())
