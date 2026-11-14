#!/usr/bin/env python3
"""Regression tests for numeric ProblemSizes / shape ordering.

The bug these lock down (`results.md` 13.4): a candidate phase's shapes were
sorted as *strings*, so the CC slot emitted ``1024, 192, 2048, 256, 512`` instead
of the deck's ``192, 256, 512, 1024, 2048``. Tensile runs a phase's ProblemSizes
in list order and each size's median absorbs the clock the previous size left, so
256^3 measured right after the slowest 2048^3 kernel at ~1/3 clock and was read
as a loser.

Three layers are tested so the same class of bug cannot reappear:

1. the shared ordering helper (``oto.tensile.shape_order``);
2. every *loaded* phase source -- the deck and the live seed overlay -- plus the
   synthesis sweep the deck feeds;
3. the last-mile writer, which must re-impose the canonical order regardless of
   what a producer hands it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml

from oto.runners.paths import results_rel
from oto.tensile.shape_order import (
    is_numerically_ordered,
    ordered_shapes,
    shape_order_key,
    shape_parts,
)

SEED_OVERLAY = REPO / results_rel("overlays", "phases.seed.overlay.yaml")


def _sides(shapes):
    return [int(str(s).split("x", 1)[0]) for s in shapes]


# --------------------------------------------------------------- helper layer

class TestShapeOrderHelper:
    def test_shape_parts_splits_cubes_and_exact_lists(self):
        assert shape_parts("256x256x256") == (256, 256, 256)
        assert shape_parts("32x4096x1") == (32, 4096, 1)
        assert shape_parts([256, 256, 256, 8]) == (256, 256, 256, 8)

    def test_shape_key_is_numeric_not_lexicographic(self):
        # The exact order the string sort got wrong.
        shapes = ["1024x1024x1024", "192x192x192", "2048x2048x2048",
                  "256x256x256", "512x512x512"]
        assert sorted(shapes) != ordered_shapes(shapes)  # string vs numeric
        assert _sides(ordered_shapes(shapes)) == [192, 256, 512, 1024, 2048]
        assert shape_order_key("1024x1024x1024") > shape_order_key("192x192x192")

    def test_ordered_shapes_dedupes_only_when_asked(self):
        shapes = ["512x512x512", "256x256x256", "512x512x512"]
        assert ordered_shapes(shapes) == ["256x256x256", "512x512x512",
                                          "512x512x512"]
        assert ordered_shapes(shapes, dedupe=True) == ["256x256x256",
                                                       "512x512x512"]

    def test_is_numerically_ordered(self):
        assert is_numerically_ordered(["192x192x192", "256x256x256"])
        assert not is_numerically_ordered(["256x256x256", "192x192x192"])


# ----------------------------------------------------- producers / loaded data

class TestLoadedPhaseSourcesAreOrdered:
    def test_deck_problem_sizes_are_numeric(self):
        phases = yaml.safe_load((REPO / "phases.yaml").read_text())
        assert phases, "deck is empty"
        for p in phases:
            shapes = p.get("shapes") or []
            assert is_numerically_ordered(shapes), (p.get("phase_id"), shapes)

    def test_seed_overlay_problem_sizes_are_numeric(self):
        if not SEED_OVERLAY.exists():
            pytest.skip("no live seed overlay in this checkout")
        doc = yaml.safe_load(SEED_OVERLAY.read_text()) or {}
        for p in doc.get("phases", []):
            shapes = p.get("shapes") or []
            if shapes:
                assert is_numerically_ordered(shapes), (p.get("phase_id"), shapes)

    def test_synthesis_family_sweeps_are_numeric(self):
        from oto.tensile.synthesis.manifest import family_shape_sweeps
        phases = yaml.safe_load((REPO / "phases.yaml").read_text())
        sweeps = family_shape_sweeps(phases)
        assert sweeps, "no family sweeps derived from the deck"
        for fam, sweep in sweeps.items():
            assert is_numerically_ordered(sweep), (fam, sweep)


# ----------------------------------------------------------------- last mile

class TestWriterReimposesOrder:
    """A producer that scrambles the sweep must not be able to reach Tensile.

    These cover the writer directly, independent of the candidate pool, so a
    future regression in any producer still cannot put a poisoned ProblemSizes
    list on the GPU.
    """

    @staticmethod
    def _deck_phase_with_sweep():
        deck = yaml.safe_load((REPO / "phases.yaml").read_text())
        for phase in deck:
            if len(phase.get("shapes") or []) >= 3:
                return phase
        pytest.skip("no multi-shape deck phase to exercise the writer")

    def test_write_phase_config_sorts_problem_sizes(self, tmp_path):
        from oto.tensile import config_writer
        try:
            pass
        except Exception as exc:
            pytest.skip(f"driver not importable: {exc}")

        phase = dict(self._deck_phase_with_sweep())
        # Hand the writer a deliberately reversed (descending) sweep.
        phase["shapes"] = list(reversed(phase["shapes"]))
        assert not is_numerically_ordered(phase["shapes"])

        out = tmp_path / "config.yaml"
        wrote, why = config_writer.write_phase_config(None, out, phase)
        assert wrote, why

        doc = yaml.safe_load(out.read_text())
        problem_sizes = doc["BenchmarkProblems"][0][1]["BenchmarkFinalParameters"][0]["ProblemSizes"]
        sides = [entry["Exact"][0] for entry in problem_sizes]
        assert sides == sorted(sides), sides
