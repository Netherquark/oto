#!/usr/bin/env python3
"""Option H Phase 4 (``Hplan.6``): band laziness/re-entrancy and the agent wiring.

Step 3 end-to-end: the band resolver is lazily built, re-enters the sampler
safely, and the mutator-side wiring feeds synthesized candidates into the run
loop. See ``tests/test_synthesis_sampler.py`` for the sampler core.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

import oto.metrics.coverage as coverage
from oto.ledger.mutator import Mutator
from oto.runners.paths import results_rel
from oto.tensile.candidate import CandidateConfig

REPO = Path(__file__).resolve().parent.parent

class StubGenerator:
    """Minimal CandidateGenerator surface that `mutate_and_feed` uses."""

    def __init__(self, mutants=(), valid=True, reason=""):
        self._mutants = list(mutants)
        self._valid = valid
        self._reason = reason
        self.appended = []

    def mutate_winner(self, config, mutation_budget):
        return list(self._mutants)

    def emit_candidate(self, phase_id, label, dtype, shapes, template, knobs):
        import hashlib
        import json
        full = {**template, **knobs}
        fp = hashlib.sha256(
            json.dumps(full, sort_keys=True).encode()).hexdigest()
        return CandidateConfig(
            phase_id=phase_id, label=label, dtype=dtype, shapes=list(shapes),
            template=template, knobs=knobs, fingerprint=fp)

    def validate_config(self, config):
        return (self._valid, self._reason)

    def append_to_phases(self, candidate, phases_file=None):
        self.appended.append(candidate)
        return candidate.phase_id

class BandResolutionTests(unittest.TestCase):
    """Regression: construction must not reach for the band.

    `ab_audit.arm_record_sets` builds a ConvergenceAgent to manage phases, and
    `coverage.measured_band_pct` calls `arm_record_sets`. So resolving the band
    inside `__init__` is a cycle -- measured_band_pct -> agent -> agent -- and it
    terminates only by exhausting the stack.
    """

    def _agent(self, **kw):
        import oto.ledger.agent as agent
        return agent.ConvergenceAgent(
            Path(kw.pop("base", REPO)), scheduler=None, analytics=None, **kw)

    def test_construction_does_not_call_the_audit(self):
        calls = []
        real = coverage.measured_band_pct

        def spy(base_dir):
            calls.append(base_dir)
            return 18.29

        coverage.measured_band_pct = spy
        try:
            self._agent()
        finally:
            coverage.measured_band_pct = real
        assert calls == []

    def test_a_supplied_band_is_used_without_any_lookup(self):
        calls = []
        real = coverage.measured_band_pct
        coverage.measured_band_pct = calls.append
        try:
            a = self._agent(band_pct=12.5)
            assert a.band() == 12.5
        finally:
            coverage.measured_band_pct = real
        assert calls == []

    def test_the_band_is_looked_up_at_most_once(self):
        calls = []
        real = coverage.measured_band_pct

        def spy(base_dir):
            calls.append(base_dir)
            return 18.29

        coverage.measured_band_pct = spy
        try:
            a = self._agent()
            assert a.band() == 18.29
            assert a.band() == 18.29
        finally:
            coverage.measured_band_pct = real
        assert len(calls) == 1

    def test_a_failing_lookup_yields_no_band_rather_than_raising(self):
        real = coverage.measured_band_pct

        def boom(base_dir):
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            assert self._agent().band() is None
        finally:
            coverage.measured_band_pct = real

    def test_a_lookup_failure_is_remembered(self):
        calls = []
        real = coverage.measured_band_pct

        def boom(base_dir):
            calls.append(base_dir)
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            a = self._agent()
            a.band()
            a.band()
        finally:
            coverage.measured_band_pct = real
        assert len(calls) == 1

    def test_reentrancy_returns_no_band_instead_of_recursing(self):
        # The nested agent is what `arm_record_sets` builds; asking it for the
        # band mid-audit must not start the cycle again.
        a = self._agent()
        a._band_computing = True
        assert a.band() is None

    def test_constructing_an_agent_from_the_audit_path_terminates(self):
        # The end-to-end shape of the cycle, with a depth limit standing in for
        # the stack: if __init__ ever reaches the audit again this raises.
        sys.setrecursionlimit(200)
        try:
            self._agent()
        finally:
            sys.setrecursionlimit(1000)


class AgentWiringTests(unittest.TestCase):
    """Hplan.6 step 3 end to end: the sweep must reach the overlay.

    The sampler is stubbed here. Its internals are covered above; what is new and
    easy to get wrong is the wiring -- that the sweep replaces `[shape]`, that
    the ledger's single `shape` column still holds the *cell* so coverage joins
    stay 1:1, and that a retired cell is skipped instead of re-searched.
    """

    DECK = """\
- phase_id: phase_sweep_a
  label: sweep_a
  shapes: ['256x256x256', '512x512x512', '1024x1024x1024']
  config:
    FamilyLabel: SS
    MacroTile: 64x64x16
"""

    WINNERS = {
        "ss_128x128x128": {
            "family": "SS", "dtype": "s", "shape": "128x128x128",
            "fp": "parentfp", "median_gflops": 12.0,
            "config": {"MacroTile": "64x64x16", "ThreadTile": "4x4"},
        }
    }

    SWEEP = ["256x256x256", "512x512x512", "1024x1024x1024"]

    def setUp(self):
        import shutil
        import tempfile

        from oto.ledger.mutator import Mutator
        from oto.ledger.registry import SQLiteRegistry
        from oto.metrics.analytics import AnalyticsEngine

        self.tmp = Path(tempfile.mkdtemp(prefix="oto_p4_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "phases.yaml").write_text(self.DECK)
        self.registry = SQLiteRegistry(self.tmp)
        self.analytics = AnalyticsEngine(self.registry, self.tmp)
        self.mutator = Mutator(self.registry, self.tmp, self.analytics)

    def _agent(self):
        import oto.ledger.agent as agent
        return agent.ConvergenceAgent(
            self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator,
            band_pct=18.29)

    def _stub(self, **over):
        result = {"candidates": [{"knobs": {"MacroTile": "64x64x16"},
                                  "groups": ("tile",)}],
                  "source": "manifest_sampler", "dropped": {},
                  "shapes": list(self.SWEEP), "graded": True, "family": "SS"}
        result.update(over)
        return result

    def _overlay_entries(self):
        entries = []
        for p in (self.tmp / results_rel("overlays")).glob("*.yaml"):
            entries += ((yaml.safe_load(p.read_text()) or {}).get("phases")
                        or [])
        return entries

    def test_the_sweep_replaces_the_single_shape(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            emitted = a.mutate_and_feed(self.WINNERS)
        assert emitted[0].shapes == self.SWEEP

    def test_the_overlay_phase_is_flagged_graded(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            a.mutate_and_feed(self.WINNERS)
        entries = self._overlay_entries()
        assert entries, "no overlay phase was written"
        assert all(e.get("graded") for e in entries)
        assert all(len(e.get("shapes") or []) >= 2 for e in entries)

    def test_the_overlay_sweep_matches_the_deck_sweep(self):
        # Asserted against the file rather than the in-memory candidate: the file
        # is what the driver actually merges into the run.
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            a.mutate_and_feed(self.WINNERS)
        assert self._overlay_entries()[0]["shapes"] == self.SWEEP

    def test_the_ledger_shape_stays_the_cell_not_the_sweep(self):
        # Coverage joins on (family, shape). Recording the sweep's first shape
        # would silently re-file the candidate into a different cell.
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()):
            emitted = a.mutate_and_feed(self.WINNERS)
        row = self.registry.get_proposal(emitted[0].fingerprint)
        assert row["shape"] == "128x128x128"
        assert row["family"] == "SS"

    def test_a_lone_shape_is_reported_as_ungraded(self):
        a = self._agent()
        stub = self._stub(shapes=["128x128x128"], graded=False)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            emitted = a.mutate_and_feed(self.WINNERS)
        assert emitted[0].shapes == ["128x128x128"]
        assert a.last_emission_stats["ungraded_cells"] == ["ss_128x128x128"]

    def test_a_missing_sweep_does_not_invent_shapes(self):
        a = self._agent()
        stub = self._stub(shapes=[], graded=False)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            emitted = a.mutate_and_feed(self.WINNERS)
        assert emitted[0].shapes == ["128x128x128"]

    def test_a_lattice_fallback_is_reported(self):
        # A run that quietly fell back looks identical to one that did not unless
        # it is surfaced.
        a = self._agent()
        stub = self._stub(source="lattice", fallback_reason="no shipped support")
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=stub):
            a.mutate_and_feed(self.WINNERS)
        assert a.last_emission_stats["lattice_fallback_cells"] == ["ss_128x128x128"]

    def test_a_retired_cell_is_skipped(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_RETIRED):
            emitted = a.mutate_and_feed(self.WINNERS)
        assert emitted == []
        assert a.last_emission_stats["retired_cells"] == ["ss_128x128x128"]

    def test_a_retired_cell_is_never_proposed(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_RETIRED):
            a.mutate_and_feed(self.WINNERS)
        assert self.registry.proposed_fps() == set()

    def test_explore_and_replicate_cells_are_sampled(self):
        for state in (coverage.STATE_EXPLORE, coverage.STATE_REPLICATE):
            with self.subTest(state=state):
                a = self._agent()
                with mock.patch.object(Mutator, "sample_cell_synthesized",
                                       return_value=self._stub()) as m, \
                     mock.patch.object(type(a), "_cell_coverage_state",
                                       return_value=state):
                    a.mutate_and_feed(self.WINNERS)
                assert m.call_count == 1
                assert a.last_emission_stats["retired_cells"] == []

    def test_the_cell_state_is_recorded_on_the_phase(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()), \
             mock.patch.object(type(a), "_cell_coverage_state",
                               return_value=coverage.STATE_REPLICATE):
            a.mutate_and_feed(self.WINNERS)
        assert self._overlay_entries()[0]["coverage_state"] == coverage.STATE_REPLICATE

    def test_the_band_is_passed_to_the_sampler(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        assert m.call_args.kwargs["band_pct"] == 18.29

    def test_the_sweep_is_read_from_the_deck_not_constructed(self):
        a = self._agent()
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        assert m.call_args.kwargs["sweeps"]["SS"] == self.SWEEP

    def test_an_unmeasurable_band_still_emits(self):
        # No band means no guidance, not a failure and not a guess: the sampler
        # is told None and excludes nothing.
        import oto.ledger.agent as agent_mod
        real = coverage.measured_band_pct

        def boom(base_dir):
            raise RuntimeError("no arm data")

        coverage.measured_band_pct = boom
        try:
            a = agent_mod.ConvergenceAgent(
                self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator)
            with mock.patch.object(Mutator, "sample_cell_synthesized",
                                   return_value=self._stub()) as m:
                emitted = a.mutate_and_feed(self.WINNERS)
            assert emitted
            assert m.call_args.kwargs["band_pct"] is None
        finally:
            coverage.measured_band_pct = real

    def test_the_band_is_resolved_lazily_and_passed(self):
        # Not supplied at construction, yet the sampler still receives it.
        import oto.ledger.agent as agent_mod
        a = agent_mod.ConvergenceAgent(
            self.tmp, StubGenerator([]), self.analytics, mutator=self.mutator)
        with mock.patch.object(Mutator, "sample_cell_synthesized",
                               return_value=self._stub()) as m:
            a.mutate_and_feed(self.WINNERS)
        assert isinstance(m.call_args.kwargs["band_pct"], float)
