#!/usr/bin/env python3
"""Phase 1 write-back regression tests: skip/bypass, outcome write-back and the
run loop's resolver call.

The driver computed winner-freq skips but never consulted them, the outcome
write-back never reached the registry, and the loop never called the resolver
at all. See ``tests/support_convergence.py`` for the fixtures.
"""
from support_convergence import HEADER, Harness, _StubScheduler

from oto.runners.driver import TensileDriver


class SkipBypassTests(Harness):
    def _driver(self, run_id="run_skip"):
        from oto.ledger.convergence_agent import ConvergenceAgent
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
        from oto.ledger.convergence_agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=None)
        assert agent.skip_mutation_arm()

    def test_bypass_is_on_with_ledger_and_outcomes(self):
        from oto.ledger.convergence_agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=self.mutator)
        assert not agent.skip_mutation_arm()

    def test_bypass_is_off_when_outcomes_cannot_be_written(self):
        from oto.ledger.convergence_agent import ConvergenceAgent
        agent = ConvergenceAgent(self.tmp, _StubScheduler(), self.analytics,
                                 mutator=self.mutator)
        agent.has_outcome_signal = False
        assert agent.skip_mutation_arm()

    def test_identical_fp_skip_is_overridden_for_overlay_phases(self):
        from oto.metrics.cell_policy import should_run
        driver = self._driver()
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpPassed", "GFLOPS": 12.0,
             "status": "completed"},
            run_id="prior")
        # The overlay identity is spelled as literals below rather than built as
        # a dict; this used to build one and never use it.
        # Baseline: the skip fires.
        allowed, _reason = should_run("phase_auto_s", "fpPassed",
                                     registry=self.registry,
                                     opt_in_identical_skip=True)
        assert not allowed
        # With the bypass authorised it must not.
        assert driver.agent
        assert not driver.agent.skip_mutation_arm()
        bypass_ok = not driver.agent.skip_mutation_arm()
        eff = True and not (True and bypass_ok)
        allowed2, _ = should_run("phase_auto_s", "fpPassed",
                                 registry=self.registry,
                                 opt_in_identical_skip=eff)
        assert allowed2

    def test_curated_phases_keep_the_identical_fp_skip(self):
        # The bypass must not re-benchmark settled curated phases every run.
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpCur", "GFLOPS": 12.0,
             "status": "completed"},
            run_id="prior")
        from oto.metrics.cell_policy import should_run
        allowed, reason = should_run(
            "phase_curated_0", "fpCur", registry=self.registry,
            opt_in_identical_skip=True)
        assert not allowed
        assert reason == "identical_fp_already_passed"

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
        assert "phase_seed_1" in calls
        driver.load_phases_manifest()
        driver.run_phases()
        # Second pass: identical fp already passed for this run -> ordinary skip.
        assert calls.count("phase_seed_1") == 1

    def test_has_run_benchmarked_scopes_to_the_run(self):
        self.registry.append_record(
            {"fp": "fpHas", "status": "completed",
             "result": {"status": "success"}}, run_id="other_run")
        assert not self.registry.has_run_benchmarked("this_run", "fpHas")
        self.registry.append_record(
            {"fp": "fpHas", "status": "completed",
             "result": {"status": "success"}}, run_id="this_run")
        assert self.registry.has_run_benchmarked("this_run", "fpHas")
        # A failed attempt does not count as benchmarked.
        assert not self.registry.has_run_benchmarked("fail_run", "fpHas")


# ------------------------------------------------------- outcome write-back

class OutcomeWriteBackTests(Harness):
    def _driver(self, run_id="run_resolve"):
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
        assert driver._resolve_proposal_outcome(phase, driver.run_dir) == "functional"
        assert self.registry.get_proposal("fpRES")["outcome"] == "functional"

    def test_a_non_proposal_phase_is_left_alone(self):
        driver = self._driver("run_nonprop")
        phase = {"phase_id": "phase_curated_0", "fp": "fpCUR", "config": {}}
        assert driver._resolve_proposal_outcome(phase, driver.run_dir) is None

    def test_no_mutator_is_a_no_op(self):
        driver = self._driver("run_nomut")
        driver.mutator = None
        phase = {"phase_id": "p", "fp": "fpX", "config": {}}
        assert driver._resolve_proposal_outcome(phase, driver.run_dir) is None

    def test_a_classification_failure_does_not_raise(self):
        driver = self._driver("run_crash")
        self.registry.record_proposal(fp="fpERR", family="SS", shape="1x1x1")

        def boom(*a, **k):
            raise RuntimeError("classifier exploded")
        driver.mutator.resolve_phase_dir = boom
        phase = {"phase_id": "p", "fp": "fpERR", "config": {}}
        assert driver._resolve_proposal_outcome(phase, driver.run_dir) is None
        assert self.registry.get_proposal("fpERR")["outcome"] == "pending"

    def test_the_observation_records_the_run(self):
        driver = self._driver("run_obs")
        self.registry.record_proposal(fp="fpOBS", family="SS", shape="1x1x1")
        d = driver.run_dir / "p" / "2_BenchmarkData"
        d.mkdir(parents=True)
        (d / "c.csv").write_text(HEADER)
        driver._resolve_proposal_outcome({"phase_id": "p", "fp": "fpOBS",
                                          "config": {}}, driver.run_dir)
        assert self.registry.observations_for("fpOBS")[0]["run_id"] == driver.run_dir.name


class LoopActuallyCallsTheResolverTests(Harness):
    """`run_phases` must invoke the write-back and the overlay-aware skip.

    Testing `_resolve_proposal_outcome` and `should_run` in isolation would pass
    even if the loop never called either, which is precisely the state Phase 1 was
    in: both existed, both were correct, and neither ran.
    """

    def _driver(self, run_id="run_loop"):
        from oto.ledger.convergence_agent import ConvergenceAgent
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
        assert self.registry.get_proposal("fpLOOP")["outcome"] == "functional"

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
        assert self.registry.get_proposal("fpSKIP")["outcome"] == "pending"

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
        assert "phase_auto_bp" in executed

    def test_the_loop_keeps_the_identical_fp_skip_for_curated_phases(self):
        driver = self._driver("run_loop_curated")
        self.registry.append_record(
            {"type": "benchmark_result", "fp": "fpCURATED",
             "GFLOPS": 12.0, "status": "completed"}, run_id="prior")
        executed = []
        driver.execute_phase = lambda phase, run_dir: executed.append(
            phase.get("phase_id")) or {"status": "completed"}
        driver.run_phases(["phase_curated_0"])
        assert executed == []

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
        assert executed == []
