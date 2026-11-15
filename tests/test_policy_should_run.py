"""policy.should_run — the complete gate matrix (audit checklist §3).

Locks the four branches the audit demands: scope allowlist, tier-1
(fp-less phase) retirement, tier-2 (phase, fp) retirement, identical-fp skip,
plus the no-registry passthrough.
"""


from oto.metrics.cell_policy import should_run


class _FakeRegistry:
    def __init__(self, phase_retired=False, config_retired=False, fp_passed=False):
        self.phase_retired = phase_retired
        self.config_retired = config_retired
        self.fp_passed = fp_passed

    def is_phase_retired(self, phase_id):
        return self.phase_retired

    def is_config_retired(self, phase_id, fp):
        return self.config_retired

    def has_fp_passed(self, fp):
        return self.fp_passed


class TestShouldRunMatrix:
    def test_no_registry_runs(self):
        ok, reason = should_run("phase_x", "fp", registry=None)
        assert ok and reason == "approved"

    def test_scope_miss_refuses(self):
        ok, reason = should_run("phase_a", "fp", registry=None,
                                phase_scope=["phase_b"])
        assert not ok and reason == "not_in_phase_scope"

    def test_scope_hit_runs_without_registry(self):
        ok, reason = should_run("phase_a", "fp", registry=None,
                                phase_scope=["phase_a"])
        assert ok and reason == "approved"

    def test_tier1_phase_retired_refuses(self):
        ok, reason = should_run("phase_a", "fp",
                                registry=_FakeRegistry(phase_retired=True))
        assert not ok and reason == "tier1_phase_retired"

    def test_tier2_config_retired_refuses(self):
        ok, reason = should_run("phase_a", "fp",
                                registry=_FakeRegistry(config_retired=True))
        assert not ok and reason == "tier2_config_retired"

    def test_tier1_beats_tier2(self):
        ok, reason = should_run("phase_a", "fp",
                                registry=_FakeRegistry(phase_retired=True,
                                                      config_retired=True))
        assert not ok and reason == "tier1_phase_retired"

    def test_identical_fp_skip_refuses_when_opt_in(self):
        ok, reason = should_run("phase_a", "fp",
                                registry=_FakeRegistry(fp_passed=True),
                                opt_in_identical_skip=True)
        assert not ok and reason == "identical_fp_already_passed"

    def test_identical_fp_skip_is_a_skip_not_a_verdict(self):
        # fp-passed is only a *skip*, not a verdict: may run when opted out
        ok, _reason = should_run("phase_a", "fp",
                                 registry=_FakeRegistry(fp_passed=True),
                                 opt_in_identical_skip=False)
        assert ok

    def test_retired_never_means_skip_when_scope_or_registry_absent(self):
        ok, reason = should_run("phase_a", "fp", registry=None,
                                opt_in_identical_skip=True)
        assert ok and reason == "approved"
