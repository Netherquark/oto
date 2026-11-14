#!/usr/bin/env python3
"""Live-artifact regression tests for the occupancy gate.

These classes read the committed candidate deck (``phases.yaml``) and the
build-proof artifact Tensile's kernel writer emits, and shell out to
``check_candidates.py`` for the deck linter and generated-cell identity. No
GPU, no Tensile invocation: the build proof is read from the repo-local
``<cn>_results/analysis/tensile_build_proof.json`` (or the ``OCCUPANCY_PROOF``
environment variable), and it skips cleanly when absent.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml
from occupancy_gate_common import BASE

from oto.device import loader as _loader
from oto.tensile.gates.occupancy import occupancy_feasible


class TestLiveDeck(unittest.TestCase):
    """The whole deck must satisfy every gate, not just hand-picked cases."""

    def setUp(self):
        self.deck = yaml.safe_load((BASE / "phases.yaml").read_text()) or []

    def test_deck_is_fully_legal(self):
        bad = []
        for p in self.deck:
            ok, why = occupancy_feasible(p["config"])
            if not ok:
                bad.append(f"{p['phase_id']}: {why}")
        assert bad == [], f"{len(bad)} live phases rejected:\n" + "\n".join(bad[:10])

    def test_deck_has_no_dead_tiles(self):
        """The thread tiles that died on real hardware must be absent."""
        dead = {("128x32x8", "8x4"), ("128x32x16", "8x4"),
                ("64x64x16", "8x8"), ("128x64x8", "8x4"), ("64x128x8", "4x8")}
        zpresent = {
            (str(p["config"].get("MacroTile")), str(p["config"].get("ThreadTile")))
            for p in self.deck
            if str(p["config"].get("DataType", "")).upper() == "Z"
        }
        still = dead & zpresent
        assert still == set(), f"dead complex tiles still in deck: {still}"


class TestTensileBuildProof(unittest.TestCase):
    """If a build-proof report is present, the gate must agree with Tensile."""

    @staticmethod
    def _report():
        """Resolve the build-proof artifact, or None when absent.

        Artifact contract (keep this in sync with ``oto/checks/tensile_build.py`` --
        its ``--json`` flag is the only producer): the operator writes the proof
        to ``./<codename>_results/analysis/tensile_build_proof.json`` (default
        local contract) or to any path exported as ``$OCCUPANCY_PROOF``. Files
        are schema-validated before use; anything else fails loudly, and no
        /tmp path is ever consulted.
        """
        from oto.runners.paths import results_rel
        env = os.environ.get("OCCUPANCY_PROOF")
        if env:
            return Path(env)
        return Path(results_rel("analysis", "tensile_build_proof.json"))

    def test_agrees_with_tensile_when_report_available(self):
        rep = self._report()
        if not rep.exists():
            self.skipTest(f"no build proof at {rep}")
        rows = json.loads(rep.read_text())
        # Schema gate: the proof must be a list of {phase_id, ok} records --
        # anything else is not a build proof and failing loudly is correct.
        if not isinstance(rows, list) or any(
            not isinstance(r, dict)
            or not isinstance(r.get("phase_id"), str)
            or r.get("ok") not in (True, False, 0, 1)
            for r in rows
        ):
            self.fail(
                f"build proof at {rep} is malformed: expected a list of "
                '{"phase_id": str, "ok": bool} records. Produce it with '
                "`python3 -m oto check tensile-build --json "
                "<codename>_results/analysis/tensile_build_proof.json`, or "
                "export OCCUPANCY_PROOF to a valid report.")
        deck = {p["phase_id"]: p for p in yaml.safe_load((BASE / "phases.yaml").read_text())}
        checked = mismatch = 0
        for row in rows:
            phase = deck.get(row["phase_id"])
            if not phase:
                continue
            ok, _ = occupancy_feasible(phase["config"])
            checked += 1
            if ok != row["ok"]:
                mismatch += 1
                self.fail(f"{row['phase_id']}: model "
                          f"{'legal' if ok else 'illegal'} but Tensile "
                          f"{'legal' if row['ok'] else 'illegal'}")
        assert checked > 0
        assert mismatch == 0


class TestDeckLinter(unittest.TestCase):
    def test_check_candidates_reports_clean(self):
        cmd = [sys.executable, "-m", "oto", "check", "candidates", "--quiet"]
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd=str(BASE), timeout=1800,
        )
        assert proc.returncode in (0, 1), proc.stdout + proc.stderr
        assert "FAIL" not in proc.stdout


class TestGeneratedPhaseCellIdentity(unittest.TestCase):
    """A generated phase must carry the family that defines its workload cell.

    cell_key() is built from config["FamilyLabel"], and the driver drops the
    cell_key stamp entirely when that is missing (cell_key("", side) is None),
    leaving analytics to recover the family from the phase_id text instead.
    That fallback happens to work today, so a missing FamilyLabel is silent:
    the run completes, the cells still fill in, and nothing looks wrong. It is
    still a real defect -- the documented identity path is the config, and the
    H/HH_HPA split (both DataType 'H') is exactly what the phase_id heuristic
    has to get right on its own. So assert the config carries it, not that the
    fallback happens to cope.
    """

    def _generated(self, family, pattern="Ailk_Bjlk", shape="256x256x256"):
        import tempfile
        from pathlib import Path

        from oto.tensile.candidate import CandidateGenerator
        with tempfile.TemporaryDirectory() as tmp:
            gen = CandidateGenerator(Path(tmp))
            cands = gen.generate_family_phases(family, [pattern], [shape])
            assert cands, f"no candidates generated for {family}"
            return cands

    def test_every_family_emits_a_resolvable_cell_key(self):
        from oto.device.vocabulary import cell_key
        for family, sides in _loader.current_profile().family_shapes.items():
            with self.subTest(family=family):
                shape = f"{sides[0]}x{sides[0]}x{sides[0]}"
                for cand in self._generated(family, shape=shape):
                    cfg = {**cand.template, **cand.knobs}
                    assert cfg.get("FamilyLabel") == family, f"{cand.phase_id} has no FamilyLabel; its records would " f"be stamped with no cell_key"
                    assert cell_key(cfg.get("FamilyLabel"), shape) is not None, f"{cand.phase_id} does not resolve to a cell key"

    def test_family_label_is_not_derivable_from_dtype(self):
        """'H' covers three families, so DataType cannot stand in for it."""
        by_dtype = {}
        for fam, dt in _loader.current_profile().family_dtype_char.items():
            by_dtype.setdefault(dt, set()).add(fam)
        ambiguous = {dt: f for dt, f in by_dtype.items() if len(f) > 1}
        assert "H" in ambiguous, "expected the H dtype to be family-ambiguous"
        # dtype_to_family() resolves 'H' to HH alone, so anything relying on the
        # dtype fallback would fold HH_HPA and HS_HPA into HH.
        assert ambiguous["H"] == {"HH", "HH_HPA", "HS_HPA"}
