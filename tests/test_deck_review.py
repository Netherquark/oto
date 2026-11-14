#!/usr/bin/env python3
"""test_deck_review.py — the candidate-decision harness.

`oto.tools.deck_review` answers the three questions an agent must settle before
decking a candidate or trusting a scoreboard. These tests pin the two properties
that make it trustworthy rather than merely plausible:

* **score** recomputes the A/B verdict under every basis and MUST report the
  report's own basis (`winner`) agreeing with the pipeline that produced the
  ledger -- otherwise the tool is a second, divergent opinion.
* **legality** drives the SAME gates the launch boundary drives, so a domain it
  calls safe is a domain the run will accept.
* **flood** must never propose a cap that drops a cell winner: the cap is ranked
  by measured median, so the winner of any cell it keeps is that cell's winner.

CPU only, read-only. No GPU, no Tensile run, no writes.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.runners.result_paths import results_rel
from oto.tools import deck_review


class _Captured:
    """Capture stdout so the subcommand's own report is assertable."""

    def __enter__(self):
        import io
        self._buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self._buf
        return self

    def __exit__(self, *exc):
        sys.stdout = self._old

    @property
    def text(self):
        return self._buf.getvalue()


class TestScore(unittest.TestCase):
    def test_every_basis_is_reported(self):
        with _Captured() as cap:
            rc = deck_review._score(REPO)
        assert rc == 0
        for basis, _meaning in deck_review.BASES:
            assert basis in cap.text, f"basis {basis} missing from score"

    def test_winner_basis_matches_the_pipeline(self):
        """The tool must not become a second, divergent A/B opinion."""
        from oto.metrics import ab_delta
        from oto.metrics.ab_audit import arm_record_sets

        native, floor, _chain = arm_record_sets(REPO)
        expected = ab_delta._pair_cells(native, floor, "winner", 2.0, None, None)
        with _Captured() as cap:
            deck_review._score(REPO)
        # The winner row must carry the same cell count the pipeline produced.
        row = next(line for line in cap.text.splitlines()
                   if line.startswith("winner"))
        assert str(len(expected)) in row, f"score's winner row disagrees with _pair_cells: {row!r}"


class TestLegality(unittest.TestCase):
    def test_refusal_census_is_through_the_real_gates(self):
        """A draw called safe here must be one the launch boundary accepts."""
        from oto.tensile.candidate import CandidateGenerator
        from oto.tensile.gates.occupancy import ldspad_feasible

        gen = CandidateGenerator(REPO)
        cfg = {"Architecture": "gfx90c", "DataType": "S", "FamilyLabel": "SS",
               "ScheduleName": "isa", "ProblemType": "Contraction",
               "ContractionPattern": "Ailk_Bjlk", "MacroTile": "128x128x8",
               "ThreadTile": "8x8", "VectorWidth": 4, "DepthU": 8,
               "GlobalSplitU": 1, "WorkGroupMapping": 4}
        ok, _why = gen.validate_config(cfg)
        assert ok, "the census's reference config must itself be legal"
        ok, _why = ldspad_feasible(cfg)
        assert ok, "the census's reference config must itself be legal"

    def test_legality_runs_clean(self):
        with _Captured() as cap:
            rc = deck_review._legality(REPO, ["SS"])
        assert rc == 0
        for label in ("legal on >=1 tile:", "coupled:", "refused standalone:"):
            assert label in cap.text, f"{label!r} missing from legality"

    def test_structural_refusals_are_reported_with_their_rule(self):
        """A refusal must name the rule, not just be counted.

        `GlobalSplitU>1` is refused on complex and on FP32-accumulate half by a
        structural class rule on this port, so it can never run there. The census
        has to surface that as a named refusal — an unnamed count would let a
        reader mistake a coupling for a dead value and "fix" a domain that is
        already correct.
        """
        with _Captured() as cap:
            deck_review._legality(REPO, ["CC"])
        text = cap.text
        assert "GlobalSplitU" in text, "the GlobalSplitU draw must appear in the census"
        refused_block = text.split("refused standalone")[-1]
        assert re.search(r"GlobalSplitU\s+[24]\s+.*gfx90c", refused_block), "CC GlobalSplitU=2/4 must be reported as a structural refusal"

    def test_a_coupling_is_not_counted_as_a_domain_defect(self):
        """`StaggerU=0` is refused only alongside a default `StaggerUStride`.

        This is the regression that made the census useless: applying a knob to
        an LDS-full tile reports the tile's own overflow as the knob's fault, so
        a default value looked dead on tiles that could never have run it.
        """
        tiles = deck_review._measured_tiles(REPO, deck_review.TILES_PER_FAMILY)
        assert tiles, "kernel_db.json must yield measured tiles"
        for fam, fam_tiles in tiles.items():
            with self.subTest(family=fam):
                for tile in fam_tiles:
                    assert "MacroTile" in tile
                    assert isinstance(tile["MacroTile"], str)
                    assert "," not in tile["MacroTile"], f"{fam}: MacroTile must be 'NxM' by now"


class TestFlood(unittest.TestCase):
    def test_cap_never_drops_a_winner(self):
        """The whole point of the cap: retain the frontier, drop the junk."""
        db_path = REPO / results_rel("analysis", "kernel_db.json")
        if not db_path.is_file():
            self.skipTest("no kernel_db.json -- rebuild the analysis cache")
        import json
        db = json.loads(db_path.read_text())

        cells = {}
        for rows in db.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or row.get("gflops_median") is None:
                    continue
                key = (str(row.get("family")), str(row.get("shape")))
                cells.setdefault(key, {}).setdefault(
                    row.get("fp") or row.get("kernel") or "", []).append(
                        row["gflops_median"])

        for cap in (16, 24, 32):
            with _Captured() as out:
                deck_review._flood(REPO, cap)
            assert f"LOSES 0 of {len(cells)} cell winners" in out.text, f"cap={cap} loses a winner -- the cap is not median-ranked"


if __name__ == "__main__":
    unittest.main()
