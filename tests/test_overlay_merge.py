#!/usr/bin/env python3
"""Phase 1 overlay-merge and proposal run_id regression tests.

The overlay was written and never merged, and ``run_id`` was dropped on
emission; these drive the driver's merge path and the proposal emission
contract. See ``tests/support_convergence.py`` for the shared fixtures.
"""
import yaml
from support_convergence import Harness, _StubScheduler

from oto.runners.driver import TensileDriver
from oto.runners.paths import results_rel


class OverlayMergeTests(Harness):
    def _driver(self, run_id):
        # Build only what the merge reads, so the test does not depend on Tensile
        # being installed for an unrelated reason.
        driver = TensileDriver.__new__(TensileDriver)
        driver.base_dir = self.tmp
        driver.run_dir = self.registry.create_run_dir(run_id)
        driver.mutator = self.mutator
        return driver

    def test_overlay_phases_are_merged(self):
        run_id = self._driver("run_merge").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_0", "fp": "fpA", "label": "m0",
             "dtype": "s", "shapes": ["128x128x128"], "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        assert "phase_auto_0" in [p["phase_id"] for p in phases]

    def test_curated_phases_survive_the_merge(self):
        run_id = self._driver("run_keep").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_1", "fp": "fpB", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        assert "phase_curated_0" in [p["phase_id"] for p in phases]
        assert "phase_auto_1" in [p["phase_id"] for p in phases]

    def test_merged_phases_are_tagged(self):
        run_id = self._driver("run_tag").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_2", "fp": "fpC", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        merged = next(p for p in phases if p["phase_id"] == "phase_auto_2")
        assert merged["origin"] == "overlay"
        assert merged["overlay_run_id"] == run_id

    def test_phases_yaml_is_never_written(self):
        run_id = self._driver("run_ro").run_dir.name
        before = (self.tmp / "phases.yaml").read_text()
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_3", "fp": "fpD", "config": {}}])
        self._driver(run_id).load_phases_manifest()
        assert (self.tmp / "phases.yaml").read_text() == before
        assert len(self.read_phases_yaml()) == 1

    def test_no_overlay_means_the_curated_deck_alone(self):
        run_id = self._driver("run_none").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        assert [p["phase_id"] for p in phases] == ["phase_curated_0"]

    def test_another_runs_overlay_is_not_applied(self):
        """A stale overlay must not be silently executed in a new run."""
        self.write_overlay("old_run", [
            {"phase_id": "phase_auto_old", "fp": "fpE", "config": {}}])
        run_id = self._driver("new_run").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        assert "phase_auto_old" not in [p["phase_id"] for p in phases]

    def test_seed_overlay_is_merged_and_tagged(self):
        self.write_seed_overlay([
            {"phase_id": "phase_seed_0", "fp": "fpS", "config": {}}])
        run_id = self._driver("run_seed_merge").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        merged = [p for p in phases if p["phase_id"] == "phase_seed_0"]
        assert len(merged) == 1
        assert merged[0]["origin"] == "seed_overlay"
        assert merged[0]["overlay_run_id"] == "seed"
        assert "phase_curated_0" in [p["phase_id"] for p in phases]
        assert len(self.read_phases_yaml()) == 1

    def test_seed_overlay_absent_means_deck_alone(self):
        run_id = self._driver("run_no_seed").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        assert [p["phase_id"] for p in phases] == ["phase_curated_0"]

    def test_no_run_dir_means_no_overlay(self):
        self.write_overlay("anything", [
            {"phase_id": "phase_auto_x", "fp": "fpF", "config": {}}])
        driver = self._driver("tmp")
        driver.run_dir = None
        phases = driver.load_phases_manifest()
        assert [p["phase_id"] for p in phases] == ["phase_curated_0"]

    def test_explicit_deck_suppresses_the_overlay(self):
        # --gfx900-reference passes its own phases file; merging native candidates
        # into the spoof floor would corrupt the A/B comparison.
        run_id = self._driver("run_ref").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_ref", "fp": "fpG", "config": {}}])
        own = self.tmp / "own_deck.yaml"
        own.write_text(yaml.safe_dump([
            {"phase_id": "phase_ref_0", "config": {}}]))
        phases = self._driver(run_id).load_phases_manifest(own)
        assert [p["phase_id"] for p in phases] == ["phase_ref_0"]

    def test_include_overlay_false_suppresses_it(self):
        run_id = self._driver("run_off").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_off", "fp": "fpH", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest(include_overlay=False)
        assert [p["phase_id"] for p in phases] == ["phase_curated_0"]

    def test_phase_id_collision_is_dropped_not_duplicated(self):
        # phases.phase_id is UNIQUE, so a colliding overlay row would be silently
        # rejected at insert time and never run.
        run_id = self._driver("run_dup").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_curated_0", "fp": "fpI", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        assert [p["phase_id"] for p in phases].count("phase_curated_0") == 1

    def test_unreadable_overlay_does_not_break_the_deck(self):
        run_id = self._driver("run_bad").run_dir.name
        d = self.tmp / results_rel("overlays")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"phases.{run_id}.overlay.yaml").write_text("phases: [oops\n")
        phases = self._driver(run_id).load_phases_manifest()
        assert [p["phase_id"] for p in phases] == ["phase_curated_0"]

    def test_missing_phases_yaml_with_overlay_still_runs(self):
        run_id = self._driver("run_nodeck").run_dir.name
        (self.tmp / "phases.yaml").unlink()
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_only", "fp": "fpJ", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        assert [p["phase_id"] for p in phases] == ["phase_auto_only"]


# ------------------------------------------------------------------- run_id

class ProposalRunIdTests(Harness):
    def test_emit_candidate_phase_carries_the_run_id(self):
        from oto.ledger.mutator import Proposal
        self.mutator.emit_candidate_phase(
            Proposal(fp="fpR", family="SS", shape="128x128x128", run_id="run_7"),
            phase_id="phase_auto_r", phase_data={"config": {}})
        row = self.registry.get_proposal("fpR")
        assert row["run_id"] == "run_7"

    def test_agent_run_id_is_stamped_on_emission(self):
        from oto.ledger.convergence_agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=self.mutator)
        agent.run_id = "run_99"
        self.mutator.sample_cell = lambda *a, **k: None
        agent.harvested_winners = {
            "SS_128x128x128": {"family": "SS", "dtype": "s",
                               "shape": "128x128x128", "fp": "parent_fp",
                               "config": {"Architecture": "gfx90c"}}}
        agent.iteration = 0
        # Drive emission directly with one knob so the path is exercised without
        # depending on the shipped manifest being present.
        agent.scheduler.emit_candidate = lambda **kw: _StubScheduler().emit_candidate(
            **{k: kw[k] for k in
               ("phase_id", "label", "dtype", "shapes", "template", "knobs")})
        orig_sample = self.mutator.sample_cell
        self.mutator.sample_cell = lambda *a, **k: [{"MacroTile": "64x64x16"}]
        try:
            agent.mutate_and_feed(agent.harvested_winners, mutation_budget=1)
        finally:
            self.mutator.sample_cell = orig_sample
        rows = self.registry.all_proposals()
        assert rows, "no proposal was emitted"
        for r in rows:
            assert r["run_id"] == "run_99"

    def test_overlay_is_written_for_this_run(self):
        path = self.mutator.write_overlay(
            [{"phase_id": "phase_auto_o", "fp": "fpO", "config": {}}],
            run_id="run_explicit")
        assert "run_explicit" in path.name
        assert [p["phase_id"] for p in self.mutator.load_overlay("run_explicit")] == ["phase_auto_o"]


# ------------------------------------------------------------------- atomicity
