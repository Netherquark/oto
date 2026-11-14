#!/usr/bin/env python3
"""
test_mutation_arm.py — the mutation arm must not touch the curated deck.

This is the behavioural half of Option H Phase 1. The ledger tests prove the
table works; these prove the loop actually uses it, and that the two conditions
Hplan.3 flags as correctness dependencies really do flip the behaviour:

  * ledger present + outcome signal present -> bypass the identical-fp skip
  * ledger missing                            -> skip stays ON (step 8)
  * ledger present but no outcome signal      -> skip stays ON (step 11)

Step 11 is the one that is easy to get wrong. A novelty-only ledger over a
non-functional search makes a run *look* productive while measuring nothing, so
novelty alone must not unlock the bypass.

No test here runs Tensile or touches the GPU. Candidates are built from a stub
scheduler so the emission logic is exercised without any hardware.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.ledger.convergence_agent import ConvergenceAgent
from oto.ledger.mutator import Mutator
from oto.ledger.registry import SQLiteRegistry
from oto.metrics.benchmark_analytics import AnalyticsEngine
from oto.runners.result_paths import results_rel
from oto.tensile.candidate import CandidateConfig

CURATED = """\
- phase_id: phase_curated_a
  label: curated_a
  config:
    MacroTile: 64x64x16
    ThreadTile: 4x4
- phase_id: phase_curated_b
  label: curated_b
  config:
    MacroTile: 32x32x16
    ThreadTile: 4x4
"""


class StubGenerator:
    """Minimal CandidateGenerator surface that mutate_and_feed uses."""

    def __init__(self, mutants, valid=True, reason=""):
        self._mutants = mutants
        self._valid = valid
        self._reason = reason
        self.family_decks = {"ZZ": [{"MacroTile": "64x64x16", "ThreadTile": "4x4"}]}
        self.appended = []
        self.validated = []

    def mutate_winner(self, config, mutation_budget):
        return list(self._mutants)

    def emit_candidate(self, phase_id, label, dtype, shapes, template, knobs):
        import hashlib
        import json
        full = {**template, **knobs}
        fp = hashlib.sha256(
            json.dumps(full, sort_keys=True).encode()).hexdigest()
        return CandidateConfig(
            phase_id=phase_id, label=label, dtype=dtype, shapes=shapes,
            template=template, knobs=knobs, fingerprint=fp)

    def validate_config(self, config):
        self.validated.append(config)
        return (self._valid, self._reason)

    def append_to_phases(self, candidate, phases_file=None):
        self.appended.append(candidate)
        return candidate.phase_id


WINNERS = {
    "zz_128x128x128": {
        "family": "ZZ",
        "dtype": "z",
        "shape": "128x128x128",
        "fp": "parentfp",
        "median_gflops": 12.0,
        "pct_of_ceiling": 0.4,
        "is_below_ceiling": True,
        "bound_class": "occupancy",
        "config": {"MacroTile": "64x64x16", "ThreadTile": "4x4"},
    }
}


class AgentTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oto_arm_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.registry = SQLiteRegistry(self.tmp)
        self.phases = self.tmp / "phases.yaml"
        self.phases.write_text(CURATED)
        self.analytics = AnalyticsEngine(self.registry, self.tmp)

    def make_agent(self, mutants, **kw):
        self.scheduler = StubGenerator(mutants, **kw)
        self.mutator = Mutator(self.registry, self.tmp, self.analytics)
        self.agent = ConvergenceAgent(
            self.tmp, self.scheduler, self.analytics, mutator=self.mutator)

    def assert_deck_unchanged(self):
        assert self.phases.read_text() == CURATED, "the curated deck was modified; candidates belong in the overlay"


class OverlayRoutingTests(AgentTestCase):
    def test_candidates_go_to_the_overlay_not_the_deck(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        emitted = self.agent.mutate_and_feed(WINNERS)
        assert len(emitted) >= 1
        assert self.scheduler.appended == []
        self.assert_deck_unchanged()

    def test_overlay_file_is_written_for_the_run(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        run_id = self.registry.create_run_dir("run_arm").name
        self.agent.mutate_and_feed(WINNERS)
        overlays = sorted((self.tmp / results_rel("overlays")).glob("*.yaml"))
        # create_run_dir returns a path; latest_run_id is what write_overlay binds
        assert overlays or self.mutator.load_overlay("run_arm")
        assert self.mutator.load_overlay(run_id) or self.mutator.load_overlay(self.registry.latest_run_id())

    def test_every_emitted_candidate_is_in_the_ledger(self):
        self.make_agent([{"MacroTile": "64x64x16"}, {"ThreadTile": "4x4"}])
        emitted = self.agent.mutate_and_feed(WINNERS)
        assert len(emitted) >= 1
        assert self.registry.proposed_fps() == {c.fingerprint for c in emitted}

    def test_iteration_and_parent_are_recorded(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        emitted = self.agent.mutate_and_feed(WINNERS)
        row = self.registry.get_proposal(emitted[0].fingerprint)
        assert row["parent_fp"] == "parentfp"
        assert row["iteration"] == 0
        assert row["family"] == "ZZ"
        assert row["shape"] == "128x128x128"

    def test_second_iteration_does_not_repropose_fingerprints(self):
        """This is D2. Before the ledger existed, iteration 2 re-proposed 25 of
        59 iteration-1 fingerprints.

        The prior re-seeds per iteration on purpose -- that is how the loop
        explores new ground -- so the property under test is that no fingerprint
        is ever emitted twice, not that a later pass emits something. A later
        pass may legitimately emit nothing: the coupled 2-group budget
        (`tile` fusing `DepthU`, `split`) over a 4-vector family like Z physical
        exhausts the neighbourhood in one iteration, and iteration 2's draw
        space is then all-non-novel. What must hold is disjunction and a ledger
        that counts exactly what was emitted -- never a re-proposed row.
        """
        self.make_agent([{"MacroTile": "64x64x16"}, {"ThreadTile": "4x4"}])
        first = self.agent.mutate_and_feed(WINNERS)
        second = self.agent.mutate_and_feed(WINNERS)
        assert len(first) >= 1
        assert {c.fingerprint for c in first} & {c.fingerprint for c in second} == set()
        assert len(self.registry.proposed_fps()) == len(first) + len(second)

    def test_repeating_an_iteration_suppresses_every_candidate(self):
        """Given the same iteration and cell, the prior must not re-emit.

        The sampler seed is `iteration:cell`, so replaying one iteration draws
        the same candidates; novelty then has to reject all of them. This is the
        direct regression guard for the closed-graph defect.
        """
        self.make_agent([{"MacroTile": "64x64x16"}, {"ThreadTile": "4x4"}])
        first = self.agent.mutate_and_feed(WINNERS)
        assert len(first) >= 1
        replay_iteration = self.agent.iteration - 1
        self.agent.iteration = replay_iteration
        second = self.agent.mutate_and_feed(WINNERS)
        assert second == [], "duplicate fingerprints were re-emitted"
        assert self.agent.last_emission_stats["rejected_non_novel"] >= 1
        assert len(self.registry.proposed_fps()) == len(first)


class ValidationAssertionTests(AgentTestCase):
    def test_invalid_candidates_are_recorded_as_legal_rejected(self):
        self.make_agent([{"MacroTile": "128x64"}], valid=False,
                        reason="occupancy illegal: register file")
        emitted = self.agent.mutate_and_feed(WINNERS)
        assert emitted == []
        rows = self.registry.coverage_view()
        assert rows[0]["n_legal_rejected"] >= 1
        attempted = self.agent.last_emission_stats.get("candidates_sampled", None)
        if attempted is not None:
            assert rows[0]["n_legal_rejected"] == attempted
        row = self.registry.pending_proposals()
        assert row == []   # it was resolved, not left pending
        fp = next(iter(self.registry.proposed_fps()))
        assert "occupancy" in self.registry.get_proposal(fp)["build_class"]
        self.assert_deck_unchanged()

    def test_validate_config_is_still_called(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        self.agent.mutate_and_feed(WINNERS)
        assert self.scheduler.validated, "validate_config must stay an assertion, not be dropped"


class SkipBypassTests(AgentTestCase):
    """Hplan.3 steps 8 and 11."""

    def test_bypass_allowed_with_ledger_and_outcome(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        assert not self.agent.skip_mutation_arm()
        assert self.agent.ledger_enabled
        assert self.agent.has_outcome_signal

    def test_skip_reenabled_when_no_mutator(self):
        self.scheduler = StubGenerator([{"MacroTile": "64x64x16"}])
        agent = ConvergenceAgent(self.tmp, self.scheduler, self.analytics)
        assert not agent.ledger_enabled
        assert agent.skip_mutation_arm(), "without a ledger the identical-fp skip must stay on"

    def test_skip_re_enabled_when_ledger_is_missing(self):
        import sqlite3
        self.make_agent([{"MacroTile": "64x64x16"}])
        with sqlite3.connect(self.registry.db_path) as c:
            c.execute("DROP TABLE proposals")
            c.commit()
        assert not self.mutator.ledger_available()
        assert self.agent.skip_mutation_arm(), "a missing ledger must not unlock novelty-based bypass"

    def test_skip_re_enabled_without_outcome_signal(self):
        """Step 11: novelty alone is not enough."""
        self.make_agent([{"MacroTile": "64x64x16"}])
        with mock.patch.object(type(self.mutator), "resolve_phase_dir", None):
            agent = ConvergenceAgent(
                self.tmp, self.scheduler, self.analytics, mutator=self.mutator)
            assert not agent.has_outcome_signal
            assert agent.skip_mutation_arm(), "a novelty-only ledger must keep the skip on"

    def test_no_mutator_falls_back_to_legacy_append(self):
        """The pre-Phase-1 path stays reachable for comparison."""
        self.scheduler = StubGenerator([{"MacroTile": "64x64x16"}])
        agent = ConvergenceAgent(self.tmp, self.scheduler, self.analytics)
        emitted = agent.mutate_and_feed(WINNERS)
        assert len(emitted) == 1
        assert len(self.scheduler.appended) == 1
        assert not agent.last_emission_stats["wrote_overlay"]


class NoCorpusLiteralsTests(unittest.TestCase):
    """claude.md §5: never transcribe a corpus count into code.

    The forbidden values are assembled from digit strings at runtime rather than
    written literally, because this test file is itself scanned: a literal here
    would trip the check it exists to perform. Prose in a docstring is not a
    corpus count, so comments and docstrings are exempt -- only executable lines
    are inspected.
    """

    FORBIDDEN = ("".join(("29", "60")), "".join(("24", "80")))

    def _executable_lines(self, path):
        """Every NAME and NUMBER token, with comments and strings discarded.

        Docstrings and comments go via `tokenize` rather than a regex because a
        naive strip cannot tell a docstring from a SQL string, and prose that
        legitimately names a historical figure must not count as a transcribed
        count. SQL literals are excluded too -- the point of the rule is counts
        baked into *behaviour*, and a column name in a DDL string is not one.

        Numbers are normalised so that `2960`, `2_960` and `0x0b98` all collapse
        to their decimal value; otherwise the check is trivially evadable by
        writing the same count differently.
        """
        import io
        import tokenize
        src = Path(path).read_text()
        found = []
        # Line ranges occupied by comments/strings, so their tokens can be cut.
        excluded = set()
        try:
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    for ln in range(tok.start[0], tok.end[0] + 1):
                        excluded.add(ln)
        except (tokenize.TokenError, IndentationError):
            return []
        try:
            for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                if tok.start[0] in excluded:
                    continue
                if tok.type == tokenize.NAME:
                    found.append((tok.start[0], tok.string))
                elif tok.type == tokenize.NUMBER:
                    try:
                        val = int(tok.string.replace("_", ""), 0)
                    except ValueError:
                        continue
                    found.append((tok.start[0], str(val)))
        except (tokenize.TokenError, IndentationError):
            return []
        return found

    def test_no_corpus_counts_in_executable_code(self):
        for rel in ("oto/ledger/mutator.py", "tests/test_mutator.py",
                    "tests/test_proposals_ledger.py",
                    "tests/test_mutation_arm.py"):
            path = Path(__file__).parent.parent / rel
            for lineno, word in self._executable_lines(path):
                for bad in self.FORBIDDEN:
                    assert word != bad, f"{rel}:{lineno} uses the literal {bad} in executable code; " "corpus counts must be read from the registry at runtime"

    def test_scanner_sees_identifiers_and_numeric_literals(self):
        """Sanity: the guardrail must not pass vacuously.

        `proposals` is a SQL string, not an identifier, so it is invisible to a
        NAME-only scanner. The ledger's own methods and its numeric columns
        (INTEGER, PRAGMA timeout, index arity) are what must be visible.
        """
        path = Path(__file__).parent.parent / "oto" / "ledger" / "registry_proposals.py"
        words = {w for _, w in self._executable_lines(path)}
        for expected in ("record_proposal", "resolve_proposal", "coverage_view"):
            assert expected in words, f"scanner missed {expected}; the guardrail would pass vacuously"
        assert any(w.isdigit() for w in words), "scanner saw no numeric literals at all"

    def test_scanner_would_catch_a_planted_count(self):
        """Prove the detector detects, using a scratch file."""
        import tempfile as _tf
        planted = "LIMIT " + "".join(("29", "60")) + "\n"
        with _tf.TemporaryDirectory() as d:
            f = Path(d) / "scratch.py"
            f.write_text(planted)
            seen = {w for _, w in self._executable_lines(f)}
        assert "".join(("29", "60")) in seen, "the scanner is not detecting the token it exists to detect"


#: A cell whose measured best has climbed above its family's published
#: realistic ceiling. `REALISTIC_CEILINGS["SS"]` was measured before the port
#: learned to hold 1135 GFLOPS on this cell, and nothing recomputes it, so
#: `is_below_ceiling` is False and the ceiling rule alone marks the cell settled.
AT_CEILING_TIED = {
    "ss_1024x1024x1024": {
        "family": "SS",
        "dtype": "s",
        "shape": "1024x1024x1024",
        "fp": "tiedfp",
        "median_gflops": 1135.0,
        "pct_of_ceiling": 101.5,
        "is_below_ceiling": False,
        "bound_class": "ALU",
        "config": {"MacroTile": "128x128x8", "ThreadTile": "8x8"},
    }
}


class FloorRelativeTargetingTests(AgentTestCase):
    """The objective is to beat the floor, so a TIE is not a finished cell.

    The 2026-10-18 run is the reason these exist: every one of its 412
    candidates went to a small cell that already beat the floor by 100%+, and
    the large tied cells got none, because `is_below_ceiling` was False on all
    of them. These pin the second, floor-relative settling reason that keeps
    such a cell mutable.
    """

    def setUp(self):
        super().setUp()
        self.calls = []

    def _stub_floor(self, mapping):
        """Install a floor reading without walking the corpus (~90s)."""
        def fake():
            self.calls.append(1)
            return mapping
        self.agent._floor_losers = fake

    def test_a_tied_cell_is_still_mutated(self):
        self.make_agent([{"MacroTile": "128x128x16"}])
        self._stub_floor({"SS:1024": {"verdict": "TIE"}})
        emitted = self.agent.mutate_and_feed(AT_CEILING_TIED)
        assert len(emitted) >= 1, "an at-ceiling cell that only ties got no candidate"
        assert self.calls, "the floor was never consulted"

    def test_a_cell_that_beats_the_floor_is_settled(self):
        self.make_agent([{"MacroTile": "128x128x16"}])
        self._stub_floor({"ZZ:128": {"verdict": "TIE"}})   # a different cell
        assert self.agent.mutate_and_feed(AT_CEILING_TIED) == []

    def test_an_unreadable_floor_keeps_the_ceiling_rule(self):
        """Empty means "cannot judge", so the old rule must stand unchanged."""
        self.make_agent([{"MacroTile": "128x128x16"}])
        self._stub_floor({})
        assert self.agent.mutate_and_feed(AT_CEILING_TIED) == []

    def test_a_below_ceiling_cell_never_pays_for_the_floor_scan(self):
        self.make_agent([{"MacroTile": "64x64x16"}])
        self._stub_floor({"ZZ:128": {}})
        emitted = self.agent.mutate_and_feed(WINNERS)   # is_below_ceiling True
        assert len(emitted) >= 1
        assert self.calls == [], "a below-ceiling cell triggered the corpus-wide scan"


if __name__ == "__main__":
    unittest.main()
