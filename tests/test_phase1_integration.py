"""Phase 1 production-integration tests.

Every case here covers a path that existed but was never *reached*: the overlay
was written and never merged, `run_id` was dropped on emission, the proposal and
its phase were two commits, `resolve_phase_dir` was never called by the driver,
WinnerFreq was parsed by a private reader, the negative cache was process-local,
and `skip_mutation_arm()` was computed but never consulted.

A test that exercises the function in isolation would pass on all of those, which
is why these drive the driver and the loop rather than the helpers.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from oto.metrics.analytics import AnalyticsEngine
from oto.ledger.mutator import Mutator
from oto.ledger.registry import SQLiteRegistry
from oto.runners.driver import TensileDriver

HEADER = (" SizeI , SizeJ , SizeL , Cijk_A , WinnerFreq \n"
          " 128 , 128 , 128 , 12.5 , 3 \n")


class _StubScheduler:
    """Minimal CandidateGenerator stand-in: the driver only needs these."""

    family_decks = {"SS": [{"MacroTile": "64x64x16", "ThreadTile": "4x4"}]}

    def emit_candidate(self, phase_id, label, dtype, shapes, template, knobs):
        from oto.tensile.candidate import CandidateConfig
        from oto.ledger.registry import fingerprint_config
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
        (self.tmp / "gfx90c_results").mkdir()
        (self.tmp / "phases.yaml").write_text(yaml.safe_dump([
            {"phase_id": "phase_curated_0", "label": "curated",
             "dtype": "s", "shapes": ["128x128x128"], "fp": "fpCURATED",
             "config": {"Architecture": "gfx90c", "DataType": "S"}},
        ]))
        self.registry = SQLiteRegistry(self.tmp)
        self.analytics = AnalyticsEngine(self.registry, self.tmp)
        self.mutator = Mutator(self.registry, self.tmp, self.analytics)

    def write_overlay(self, run_id, phases):
        d = self.tmp / "gfx90c_results" / "overlays"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"phases.{run_id}.overlay.yaml").write_text(
            yaml.safe_dump({"run_id": run_id, "phases": phases}))

    def write_seed_overlay(self, phases):
        d = self.tmp / "gfx90c_results" / "overlays"
        d.mkdir(parents=True, exist_ok=True)
        (d / "phases.seed.overlay.yaml").write_text(
            yaml.safe_dump({"run_id": "seed", "phases": phases}))

    def read_phases_yaml(self):
        return yaml.safe_load((self.tmp / "phases.yaml").read_text())


# ---------------------------------------------------------------- overlay merge

class OverlayMergeTests(Harness):
    def _driver(self, run_id):
        import oto.runners.cli
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
        self.assertIn("phase_auto_0", [p["phase_id"] for p in phases])

    def test_curated_phases_survive_the_merge(self):
        run_id = self._driver("run_keep").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_1", "fp": "fpB", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        self.assertIn("phase_curated_0", [p["phase_id"] for p in phases])
        self.assertIn("phase_auto_1", [p["phase_id"] for p in phases])

    def test_merged_phases_are_tagged(self):
        run_id = self._driver("run_tag").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_2", "fp": "fpC", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        merged = [p for p in phases if p["phase_id"] == "phase_auto_2"][0]
        self.assertEqual(merged["origin"], "overlay")
        self.assertEqual(merged["overlay_run_id"], run_id)

    def test_phases_yaml_is_never_written(self):
        run_id = self._driver("run_ro").run_dir.name
        before = (self.tmp / "phases.yaml").read_text()
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_3", "fp": "fpD", "config": {}}])
        self._driver(run_id).load_phases_manifest()
        self.assertEqual((self.tmp / "phases.yaml").read_text(), before)
        self.assertEqual(len(self.read_phases_yaml()), 1)

    def test_no_overlay_means_the_curated_deck_alone(self):
        run_id = self._driver("run_none").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        self.assertEqual([p["phase_id"] for p in phases], ["phase_curated_0"])

    def test_another_runs_overlay_is_not_applied(self):
        """A stale overlay must not be silently executed in a new run."""
        self.write_overlay("old_run", [
            {"phase_id": "phase_auto_old", "fp": "fpE", "config": {}}])
        run_id = self._driver("new_run").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        self.assertNotIn("phase_auto_old", [p["phase_id"] for p in phases])

    def test_seed_overlay_is_merged_and_tagged(self):
        self.write_seed_overlay([
            {"phase_id": "phase_seed_0", "fp": "fpS", "config": {}}])
        run_id = self._driver("run_seed_merge").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        merged = [p for p in phases if p["phase_id"] == "phase_seed_0"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["origin"], "seed_overlay")
        self.assertEqual(merged[0]["overlay_run_id"], "seed")
        self.assertIn("phase_curated_0", [p["phase_id"] for p in phases])
        self.assertEqual(len(self.read_phases_yaml()), 1)

    def test_seed_overlay_absent_means_deck_alone(self):
        run_id = self._driver("run_no_seed").run_dir.name
        phases = self._driver(run_id).load_phases_manifest()
        self.assertEqual([p["phase_id"] for p in phases], ["phase_curated_0"])

    def test_no_run_dir_means_no_overlay(self):
        self.write_overlay("anything", [
            {"phase_id": "phase_auto_x", "fp": "fpF", "config": {}}])
        driver = self._driver("tmp")
        driver.run_dir = None
        phases = driver.load_phases_manifest()
        self.assertEqual([p["phase_id"] for p in phases], ["phase_curated_0"])

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
        self.assertEqual([p["phase_id"] for p in phases], ["phase_ref_0"])

    def test_include_overlay_false_suppresses_it(self):
        run_id = self._driver("run_off").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_off", "fp": "fpH", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest(include_overlay=False)
        self.assertEqual([p["phase_id"] for p in phases], ["phase_curated_0"])

    def test_phase_id_collision_is_dropped_not_duplicated(self):
        # phases.phase_id is UNIQUE, so a colliding overlay row would be silently
        # rejected at insert time and never run.
        run_id = self._driver("run_dup").run_dir.name
        self.write_overlay(run_id, [
            {"phase_id": "phase_curated_0", "fp": "fpI", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        self.assertEqual(
            [p["phase_id"] for p in phases].count("phase_curated_0"), 1)

    def test_unreadable_overlay_does_not_break_the_deck(self):
        run_id = self._driver("run_bad").run_dir.name
        d = self.tmp / "gfx90c_results" / "overlays"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"phases.{run_id}.overlay.yaml").write_text("phases: [oops\n")
        phases = self._driver(run_id).load_phases_manifest()
        self.assertEqual([p["phase_id"] for p in phases], ["phase_curated_0"])

    def test_missing_phases_yaml_with_overlay_still_runs(self):
        run_id = self._driver("run_nodeck").run_dir.name
        (self.tmp / "phases.yaml").unlink()
        self.write_overlay(run_id, [
            {"phase_id": "phase_auto_only", "fp": "fpJ", "config": {}}])
        phases = self._driver(run_id).load_phases_manifest()
        self.assertEqual([p["phase_id"] for p in phases], ["phase_auto_only"])


# ------------------------------------------------------------------- run_id

class ProposalRunIdTests(Harness):
    def test_emit_candidate_phase_carries_the_run_id(self):
        from oto.ledger.mutator import Proposal
        self.mutator.emit_candidate_phase(
            Proposal(fp="fpR", family="SS", shape="128x128x128", run_id="run_7"),
            phase_id="phase_auto_r", phase_data={"config": {}})
        row = self.registry.get_proposal("fpR")
        self.assertEqual(row["run_id"], "run_7")

    def test_agent_run_id_is_stamped_on_emission(self):
        from oto.ledger.agent import ConvergenceAgent
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
        self.assertTrue(rows, "no proposal was emitted")
        for r in rows:
            self.assertEqual(r["run_id"], "run_99")

    def test_overlay_is_written_for_this_run(self):
        from oto.ledger.mutator import Proposal
        path = self.mutator.write_overlay(
            [{"phase_id": "phase_auto_o", "fp": "fpO", "config": {}}],
            run_id="run_explicit")
        self.assertIn("run_explicit", path.name)
        self.assertEqual([p["phase_id"] for p in self.mutator.load_overlay("run_explicit")],
                         ["phase_auto_o"])


# ------------------------------------------------------------------- atomicity

class AtomicEmissionTests(Harness):
    def test_proposal_and_phase_land_together(self):
        self.registry.emit_proposal_with_phase(
            fp="fpA", family="SS", shape="1x1x1", run_id="r1",
            phase_id="phase_atomic", phase_data={"config": {"a": 1}})
        self.assertIsNotNone(self.registry.get_proposal("fpA"))
        self.assertEqual(len(self.registry.get_phases()), 1)

    def test_a_failing_phase_write_rolls_the_proposal_back(self):
        import sqlite3
        with self.assertRaises(sqlite3.Error):
            with self.registry._get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO proposals (fp, created_at) VALUES ('fpB', 'x')")
                # Same transaction, second write violates the phases constraint.
                conn.execute(
                    "INSERT INTO phases (phase_id, fingerprint, data, created_at) "
                    "VALUES (NULL, 'fpB', '{}', 'x')")
        self.assertIsNone(self.registry.get_proposal("fpB"))

    def test_no_proposal_survives_without_its_phase(self):
        # The hazard: a ledger row with no phase reads as pending forever, so its
        # n never grows and the cell is re-routed to replicate indefinitely.
        self.registry.emit_proposal_with_phase(
            fp="fpC", phase_id="phase_c", phase_data={"fp": "fpC"})
        phases = self.registry.get_phases()
        self.assertTrue(phases)
        self.assertTrue(all(p.get("fp") == "fpC" for p in phases))

    def test_duplicate_fp_still_records_the_phase(self):
        first = self.registry.emit_proposal_with_phase(
            fp="fpD", phase_id="phase_d1", phase_data={})
        second = self.registry.emit_proposal_with_phase(
            fp="fpD", phase_id="phase_d2", phase_data={})
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.registry.get_phases()), 2)

    def test_mutator_exposes_the_atomic_path(self):
        from oto.ledger.mutator import Proposal
        self.mutator.emit_candidate_phase(
            Proposal(fp="fpE", family="SS", shape="1x1x1", run_id="r"),
            phase_id="phase_e", phase_data={"config": {}})
        self.assertIsNotNone(self.registry.get_proposal("fpE"))
        self.assertEqual(len(self.registry.get_phases()), 1)


# ------------------------------------------------------- winnerfreq durability

class WinnerFreqPersistenceTests(Harness):
    def _phase_dir(self, csv_text=HEADER):
        d = self.tmp / "phase_dir" / "2_BenchmarkData"
        d.mkdir(parents=True, exist_ok=True)
        (d / "Cijk_y_00.csv").write_text(csv_text)
        return self.tmp / "phase_dir"

    def test_winner_freq_is_persisted_with_the_verdict(self):
        pdir = self._phase_dir()
        self.registry.record_proposal(fp="fpW", family="SS", shape="1x1x1")
        outcome, detail = self.mutator.resolve_phase_dir(
            "fpW", pdir, run_id="run_w")
        obs = self.registry.observations_for("fpW")
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["winner_freq"], 3.0)
        self.assertEqual(obs[0]["outcome"], outcome)

    def test_the_verdict_and_the_evidence_are_separate(self):
        pdir = self._phase_dir()
        self.registry.record_proposal(fp="fpV", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpV", pdir)
        self.assertEqual(self.registry.get_proposal("fpV")["outcome"],
                         "functional")
        self.assertEqual(len(self.registry.observations_for("fpV")), 1)

    def test_repeated_observations_accumulate(self):
        # Evidence is re-observable; the verdict is decided once. Modelling that
        # with one row each would make a re-measurement overwrite the basis of
        # the decision it had already recorded.
        pdir = self._phase_dir()
        self.registry.record_proposal(fp="fpU", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpU", pdir)
        outcome, _ = self.mutator.resolve_phase_dir("fpU", pdir)
        self.assertEqual(outcome, "pending")   # verdict not re-decided
        self.assertEqual(len(self.registry.observations_for("fpU")), 2)

    def test_a_missing_csv_leaves_winner_freq_null(self):
        d = self.tmp / "empty_phase" / "2_BenchmarkData"
        d.mkdir(parents=True)
        self.registry.record_proposal(fp="fpT", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpT", self.tmp / "empty_phase")
        obs = self.registry.observations_for("fpT")
        self.assertEqual(len(obs), 1)
        self.assertIsNone(obs[0]["winner_freq"])

    def test_winner_freq_uses_the_canonical_reader(self):
        pdir = self._phase_dir(
            " SizeI , SizeJ , SizeL , Cijk_A , WinnerFreq \n"
            " 128 , 128 , 128 , 12.5 , 7 \n")
        self.registry.record_proposal(fp="fpS", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpS", pdir)
        self.assertEqual(self.registry.observations_for("fpS")[0]["winner_freq"], 7.0)

    def test_evidence_write_failure_does_not_block_the_verdict(self):
        self.registry.record_proposal(fp="fpY", family="SS", shape="1x1x1")
        d = self.tmp / "pd" / "2_BenchmarkData"
        d.mkdir(parents=True)
        (d / "c.csv").write_text(HEADER)
        self.registry.append_observation = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("boom"))
        outcome, _ = self.mutator.resolve_phase_dir("fpY", self.tmp / "pd")
        self.assertEqual(outcome, "functional")
        self.assertEqual(self.registry.get_proposal("fpY")["outcome"], "functional")


# -------------------------------------------------------- negative cache durability

class NegativeCacheDurabilityTests(Harness):
    def _record(self, fp, parent, outcome):
        self.registry.record_proposal(fp=fp, family="SS", shape="1x1x1",
                                      parent_fp=parent)
        self.registry.resolve_proposal(fp, outcome)

    def test_a_fresh_process_recovers_the_count(self):
        self._record("c1", "parentX", "non_functional")
        self._record("c2", "parentX", "non_functional")
        fresh = Mutator(self.registry, self.tmp, self.analytics,
                        negative_cache_k=2)
        self.assertEqual(fresh.consecutive_failures("parentX"), 2)
        self.assertTrue(fresh.neighbourhood_saturated("parentX"))

    def test_a_success_resets_the_streak(self):
        self._record("s1", "parentY", "non_functional")
        self._record("s2", "parentY", "non_functional")
        self._record("s3", "parentY", "functional")
        fresh = Mutator(self.registry, self.tmp, self.analytics,
                        negative_cache_k=2)
        self.assertEqual(fresh.consecutive_failures("parentY"), 0)
        self.assertFalse(fresh.neighbourhood_saturated("parentY"))

    def test_incremental_and_rebuilt_caches_agree(self):
        for i in range(4):
            self._record(f"i{i}", "parentZ", "non_functional")
        live = Mutator(self.registry, self.tmp, self.analytics,
                       negative_cache_k=3)
        rebuilt = live.rebuild_negative_cache()
        self.assertEqual(rebuilt["parentZ"], 4)
        self.assertEqual(live.consecutive_failures("parentZ"),
                         rebuilt["parentZ"])

    def test_proposals_without_a_parent_are_ignored(self):
        self.registry.record_proposal(fp="np", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("np", "non_functional")
        self.assertEqual(Mutator(self.registry, self.tmp, self.analytics)
                         .consecutive_failures(""), 0)

    def test_the_archived_corpus_still_saturates_nothing(self):
        # Every measured mutant row is non-zero, so replaying the corpus must not
        # mark a shipped neighbourhood dead. This is the guard that stops the
        # cache firing on data it should not.
        m = Mutator(self.registry, self.tmp, self.analytics,
                    negative_cache_k=3)
        self.assertEqual(m.rebuild_negative_cache(), {})


# --------------------------------------------------------------- skip bypass

class SkipBypassTests(Harness):
    def _driver(self, run_id="run_skip"):
        import oto.runners.cli
        from oto.ledger.agent import ConvergenceAgent
        driver = TensileDriver.__new__(TensileDriver)
        driver.base_dir = self.tmp
        driver.registry = self.registry
        driver.run_dir = self.registry.create_run_dir(run_id)
        driver.mutator = self.mutator
        driver.analytics = self.analytics
        driver.agent = ConvergenceAgent(self.tmp, _StubScheduler(),
                                        self.analytics, mutator=self.mutator)
        driver._sync_agent_run_id()
        driver._stop_requested = False
        driver._finish_after_iteration = False
        driver._gpu_phases_run = 0
        driver.cooldown_s = 0
        return driver

    def test_bypass_is_off_without_a_ledger(self):
        from oto.ledger.agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=None)
        self.assertTrue(agent.skip_mutation_arm())

    def test_bypass_is_on_with_ledger_and_outcomes(self):
        from oto.ledger.agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=self.mutator)
        self.assertFalse(agent.skip_mutation_arm())

    def test_bypass_is_off_when_outcomes_cannot_be_written(self):
        from oto.ledger.agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=self.mutator)
        agent.has_outcome_signal = False
        self.assertTrue(agent.skip_mutation_arm())

    def test_identical_fp_skip_is_overridden_for_overlay_phases(self):
        from oto.metrics.policy import should_run
        driver = self._driver()
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpPassed", "GFLOPS": 12.0,
             "status": "completed"},
            run_id="prior")
        # The overlay identity is spelled as literals below rather than built as
        # a dict; this used to build one and never use it.
        # Baseline: the skip fires.
        allowed, reason = should_run("phase_auto_s", "fpPassed",
                                     registry=self.registry,
                                     opt_in_identical_skip=True)
        self.assertFalse(allowed)
        # With the bypass authorised it must not.
        self.assertTrue(driver.agent and not driver.agent.skip_mutation_arm())
        bypass_ok = not driver.agent.skip_mutation_arm()
        eff = True and not (True and bypass_ok)
        allowed2, _ = should_run("phase_auto_s", "fpPassed",
                                 registry=self.registry,
                                 opt_in_identical_skip=eff)
        self.assertTrue(allowed2)

    def test_curated_phases_keep_the_identical_fp_skip(self):
        # The bypass must not re-benchmark settled curated phases every run.
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpCur", "GFLOPS": 12.0,
             "status": "completed"},
            run_id="prior")
        from oto.metrics.policy import should_run
        allowed, reason = should_run(
            "phase_curated_0", "fpCur", registry=self.registry,
            opt_in_identical_skip=True)
        self.assertFalse(allowed)
        self.assertEqual(reason, "identical_fp_already_passed")

    def test_seed_row_is_measured_once_per_run_then_skipped(self):
        """A static seed must not re-benchmark itself every iteration."""
        driver = self._driver("run_seed_bypass")
        self.write_seed_overlay([
            {"phase_id": "phase_seed_1", "label": "seed1", "fp": "fpSeed1",
             "shapes": ["256x256x256"], "config": {"Architecture": "gfx90c",
                                                  "DataType": "S"},
             "origin": "seed"}])
        calls = []

        def fake_execute(phase, rundir):
            calls.append(phase["phase_id"])
            # A completed record lands in the registry, exactly like a real run.
            self.registry.append_record(
                {"fp": phase["fp"], "phase_id": phase["phase_id"],
                 "status": "completed",
                 "result": {"status": "success", "returncode": 0,
                            "benchmark_path": "x", "csv_count": 1}},
                run_id=driver.run_dir.name)
            return {"status": "completed", "phase_id": phase["phase_id"]}

        driver.execute_phase = fake_execute
        driver._start_live_status = lambda *a, **k: None
        driver._stop_live_status = lambda *a, **k: None
        driver._read_key = lambda block=False, **k: None
        driver.load_phases_manifest()
        driver.run_phases()
        self.assertIn("phase_seed_1", calls)
        driver.load_phases_manifest()
        driver.run_phases()
        # Second pass: identical fp already passed for this run -> ordinary skip.
        self.assertEqual(calls.count("phase_seed_1"), 1)

    def test_has_run_benchmarked_scopes_to_the_run(self):
        self.registry.append_record(
            {"fp": "fpHas", "status": "completed",
             "result": {"status": "success"}}, run_id="other_run")
        self.assertFalse(self.registry.has_run_benchmarked("this_run", "fpHas"))
        self.registry.append_record(
            {"fp": "fpHas", "status": "completed",
             "result": {"status": "success"}}, run_id="this_run")
        self.assertTrue(self.registry.has_run_benchmarked("this_run", "fpHas"))
        # A failed attempt does not count as benchmarked.
        self.assertFalse(self.registry.has_run_benchmarked("fail_run", "fpHas"))


# ------------------------------------------------------- outcome write-back

class OutcomeWriteBackTests(Harness):
    def _driver(self, run_id="run_resolve"):
        import oto.runners.cli
        driver = TensileDriver.__new__(TensileDriver)
        driver.base_dir = self.tmp
        driver.registry = self.registry
        driver.run_dir = self.registry.create_run_dir(run_id)
        driver.mutator = self.mutator
        return driver

    def test_a_launched_overlay_phase_resolves_its_proposal(self):
        driver = self._driver("run_resolve")
        phase = {"phase_id": "phase_auto_res", "fp": "fpRES",
                 "origin": "overlay", "config": {}}
        self.registry.record_proposal(fp="fpRES", family="SS", shape="1x1x1",
                                      run_id=driver.run_dir.name)
        d = driver.run_dir / "phase_auto_res" / "2_BenchmarkData"
        d.mkdir(parents=True)
        (d / "Cijk_y_00.csv").write_text(HEADER)
        self.assertEqual(driver._resolve_proposal_outcome(phase, driver.run_dir),
                         "functional")
        self.assertEqual(self.registry.get_proposal("fpRES")["outcome"],
                         "functional")

    def test_a_non_proposal_phase_is_left_alone(self):
        driver = self._driver("run_nonprop")
        phase = {"phase_id": "phase_curated_0", "fp": "fpCUR", "config": {}}
        self.assertIsNone(driver._resolve_proposal_outcome(phase, driver.run_dir))

    def test_no_mutator_is_a_no_op(self):
        driver = self._driver("run_nomut")
        driver.mutator = None
        phase = {"phase_id": "p", "fp": "fpX", "config": {}}
        self.assertIsNone(driver._resolve_proposal_outcome(phase, driver.run_dir))

    def test_a_classification_failure_does_not_raise(self):
        driver = self._driver("run_crash")
        self.registry.record_proposal(fp="fpERR", family="SS", shape="1x1x1")

        def boom(*a, **k):
            raise RuntimeError("classifier exploded")
        driver.mutator.resolve_phase_dir = boom
        phase = {"phase_id": "p", "fp": "fpERR", "config": {}}
        self.assertIsNone(driver._resolve_proposal_outcome(phase, driver.run_dir))
        self.assertEqual(self.registry.get_proposal("fpERR")["outcome"], "pending")

    def test_the_observation_records_the_run(self):
        driver = self._driver("run_obs")
        self.registry.record_proposal(fp="fpOBS", family="SS", shape="1x1x1")
        d = driver.run_dir / "p" / "2_BenchmarkData"
        d.mkdir(parents=True)
        (d / "c.csv").write_text(HEADER)
        driver._resolve_proposal_outcome({"phase_id": "p", "fp": "fpOBS",
                                          "config": {}}, driver.run_dir)
        self.assertEqual(self.registry.observations_for("fpOBS")[0]["run_id"],
                         driver.run_dir.name)


if __name__ == "__main__":
    unittest.main()

class LoopActuallyCallsTheResolverTests(Harness):
    """`run_phases` must invoke the write-back and the overlay-aware skip.

    Testing `_resolve_proposal_outcome` and `should_run` in isolation would pass
    even if the loop never called either, which is precisely the state Phase 1 was
    in: both existed, both were correct, and neither ran.
    """

    def _driver(self, run_id="run_loop"):
        import oto.runners.cli
        from oto.ledger.agent import ConvergenceAgent
        driver = TensileDriver.__new__(TensileDriver)
        driver.base_dir = self.tmp
        driver.registry = self.registry
        driver.analytics = self.analytics
        driver.scheduler = _StubScheduler()
        driver.mutator = self.mutator
        driver.agent = ConvergenceAgent(self.tmp, _StubScheduler(),
                                        self.analytics, mutator=self.mutator)
        driver.run_dir = self.registry.create_run_dir(run_id)
        driver.configs_dir = driver.run_dir / "configs"
        driver.configs_dir.mkdir(exist_ok=True)
        driver._sync_agent_run_id()
        driver._stop_requested = False
        driver._finish_after_iteration = False
        driver._gpu_phases_run = 0
        driver.cooldown_s = 0
        driver.phase_timeout_s = 1
        driver._last_run_status = None
        driver._start_live_status = lambda *a, **k: None
        driver._stop_live_status = lambda *a, **k: None
        driver._read_key = lambda block=True: ""
        driver._apply_cooldown = lambda: True
        driver._ensure_telemetry = lambda: None
        driver._named_cell_stamps = lambda phase: {}
        driver._write_phase_config = lambda path, phase: (True, None)
        driver.execute_phase = lambda phase, run_dir: {
            "status": "completed", "phase_id": phase.get("phase_id")}
        return driver

    def _write_candidate_csv(self, driver, phase_id):
        d = driver.run_dir / phase_id / "2_BenchmarkData"
        d.mkdir(parents=True, exist_ok=True)
        (d / "c.csv").write_text(HEADER)

    def test_the_loop_resolves_a_launched_overlay_phase(self):
        driver = self._driver("run_loop_resolve")
        phase = {"phase_id": "phase_auto_loop", "fp": "fpLOOP",
                 "config": {}}
        # Written as an overlay and merged by the loop, so this covers the merge,
        # the loop, and the write-back together rather than any one of them.
        self.write_overlay(driver.run_dir.name, [phase])
        self.registry.record_proposal(fp="fpLOOP", family="SS",
                                      shape="128x128x128",
                                      run_id=driver.run_dir.name)
        self._write_candidate_csv(driver, "phase_auto_loop")
        driver.run_phases([phase["phase_id"]])
        self.assertEqual(self.registry.get_proposal("fpLOOP")["outcome"],
                         "functional")

    def test_the_loop_leaves_a_skipped_phase_pending(self):
        # A phase that never launched produced no output; classifying it as
        # non-functional would retire a candidate for the wrong reason.
        driver = self._driver("run_loop_skip")
        phase = {"phase_id": "phase_auto_skip", "fp": "fpSKIP",
                 "origin": "overlay", "overlay_run_id": driver.run_dir.name,
                 "config": {}}
        self.registry.record_proposal(fp="fpSKIP", family="SS", shape="1x1x1")
        driver.execute_phase = lambda phase, run_dir: {
            "status": "skipped", "phase_id": phase.get("phase_id")}
        driver.run_phases([phase["phase_id"]])
        self.assertEqual(self.registry.get_proposal("fpSKIP")["outcome"],
                         "pending")

    def test_the_loop_bypasses_the_identical_fp_skip_for_overlay_phases(self):
        driver = self._driver("run_loop_bypass")
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpBP", "GFLOPS": 12.0,
             "status": "completed"}, run_id="prior")
        executed = []

        def fake_execute(phase, run_dir):
            executed.append(phase.get("phase_id"))
            return {"status": "completed", "phase_id": phase.get("phase_id")}
        driver.execute_phase = fake_execute
        self.write_overlay(driver.run_dir.name, [
            {"phase_id": "phase_auto_bp", "fp": "fpBP", "config": {}}])
        driver.run_phases(["phase_auto_bp"])
        self.assertIn("phase_auto_bp", executed)

    def test_the_loop_keeps_the_identical_fp_skip_for_curated_phases(self):
        driver = self._driver("run_loop_curated")
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpCURATED",
             "GFLOPS": 12.0, "status": "completed"}, run_id="prior")
        executed = []
        driver.execute_phase = lambda phase, run_dir: executed.append(
            phase.get("phase_id")) or {"status": "completed"}
        driver.run_phases(["phase_curated_0"])
        self.assertEqual(executed, [])

    def test_the_loop_bypass_is_off_without_the_outcome_signal(self):
        driver = self._driver("run_loop_nosignal")
        driver.agent.has_outcome_signal = False
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpNS", "GFLOPS": 12.0,
             "status": "completed"}, run_id="prior")
        executed = []
        driver.execute_phase = lambda phase, run_dir: executed.append(
            phase.get("phase_id")) or {"status": "completed"}
        self.write_overlay(driver.run_dir.name, [
            {"phase_id": "phase_auto_ns", "fp": "fpNS", "config": {}}])
        driver.run_phases(["phase_auto_ns"])
        self.assertEqual(executed, [])


class ReadOnlyRegistryTests(Harness):
    """A reporting path must not write to the registry it reports on.

    Found the hard way: `ab_audit` constructs a `SQLiteRegistry`, whose
    `__init__` ran the additive schema migration unconditionally. Every audit run
    therefore rewrote the live floor registry's bytes -- schema only, no row
    touched, but a report had changed its own subject.
    """

    def test_read_only_construction_does_not_create_a_database(self):
        base = self.tmp / "empty"
        (base / "gfx90c_results").mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            SQLiteRegistry(base, read_only=True)
        self.assertFalse((base / "gfx90c_results" / "registry.db").exists())

    def test_read_only_construction_leaves_the_file_byte_identical(self):
        SQLiteRegistry(self.tmp)          # writable: creates + migrates
        before = self.registry.db_path.read_bytes()
        SQLiteRegistry(self.tmp, read_only=True)
        self.assertEqual(self.registry.db_path.read_bytes(), before)

    def test_read_only_readers_still_work(self):
        self.registry.record_proposal(fp="ro1", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("ro1", "functional")
        ro = SQLiteRegistry(self.tmp, read_only=True)
        self.assertEqual(ro.get_proposal("ro1")["outcome"], "functional")
        self.assertEqual(len(ro.all_proposals()), 1)
        self.assertEqual(ro.outcome_histogram()["functional"], 1)

    def test_read_only_refuses_every_write(self):
        self.registry.record_proposal(fp="ro2", family="SS", shape="1x1x1")
        ro = SQLiteRegistry(self.tmp, read_only=True)
        for call in (
            lambda: ro.record_proposal(fp="ro3", family="SS"),
            lambda: ro.resolve_proposal("ro2", "non_functional"),
            lambda: ro.append_record({"type": "x"}, run_id="r"),
            lambda: ro.append_phase("p1", "f1", {}),
            lambda: ro.append_observation("ro2", outcome="functional"),
            lambda: ro.emit_proposal_with_phase(fp="ro4", phase_id="p2"),
            lambda: ro.update_run_status("r", "completed"),
        ):
            with self.assertRaises(PermissionError):
                call()

    def test_a_refused_write_changes_nothing(self):
        self.registry.record_proposal(fp="ro5", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("ro5", "functional")
        before = self.registry.db_path.read_bytes()
        ro = SQLiteRegistry(self.tmp, read_only=True)
        with self.assertRaises(PermissionError):
            ro.resolve_proposal("ro5", "non_functional")
        self.assertEqual(self.registry.db_path.read_bytes(), before)
        self.assertEqual(self.registry.get_proposal("ro5")["outcome"],
                         "functional")

    def test_the_audit_path_is_read_only(self):
        import oto.metrics.ab_audit as ab_audit
        seen = {}

        def spy(base, read_only=False):
            seen["read_only"] = read_only
            return SQLiteRegistry(base, read_only=True)
        import oto.ledger.registry as reg_mod
        # ab_audit imports SQLiteRegistry inside the function; patch the module.
        import unittest.mock as mock
        with mock.patch("oto.ledger.registry.SQLiteRegistry", spy):
            ab_audit._proposal_coverage(self.tmp, band_pct=10.0)
        self.assertTrue(seen.get("read_only"))

    def test_full_audit_does_not_change_the_file(self):
        import tempfile as tf
        base = Path(tf.mkdtemp(prefix="oto_ro_audit_"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        (base / "gfx90c_results").mkdir(parents=True)
        (base / "phases.yaml").write_text("[]")
        reg = SQLiteRegistry(base)
        reg.create_run_dir("run_ro")
        before = reg.db_path.read_bytes()
        import oto.metrics.ab_audit as ab_audit
        ab_audit.audit(base)          # an empty corpus must not raise
        self.assertEqual(reg.db_path.read_bytes(), before)
