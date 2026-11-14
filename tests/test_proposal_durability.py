#!/usr/bin/env python3
"""Phase 1 durability regression tests: atomic emission, WinnerFreq persistence and the negative cache.

These paths existed but nothing landed atomically: the proposal and its phase
were two commits, WinnerFreq was parsed by a private reader, and the negative
cache was process-local. See ``tests/support_convergence.py`` for the fixtures.
"""
import pytest
from support_convergence import HEADER, Harness

from oto.ledger.mutator import Mutator


class AtomicEmissionTests(Harness):
    def test_proposal_and_phase_land_together(self):
        self.registry.emit_proposal_with_phase(
            fp="fpA", family="SS", shape="1x1x1", run_id="r1",
            phase_id="phase_atomic", phase_data={"config": {"a": 1}})
        assert self.registry.get_proposal("fpA") is not None
        assert len(self.registry.get_phases()) == 1

    def test_a_failing_phase_write_rolls_the_proposal_back(self):
        import sqlite3
        with pytest.raises(sqlite3.Error), self.registry._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO proposals (fp, created_at) VALUES ('fpB', 'x')")
            # Same transaction, second write violates the phases constraint.
            conn.execute(
                "INSERT INTO phases (phase_id, fingerprint, data, created_at) "
                "VALUES (NULL, 'fpB', '{}', 'x')")
        assert self.registry.get_proposal("fpB") is None

    def test_no_proposal_survives_without_its_phase(self):
        # The hazard: a ledger row with no phase reads as pending forever, so its
        # n never grows and the cell is re-routed to replicate indefinitely.
        self.registry.emit_proposal_with_phase(
            fp="fpC", phase_id="phase_c", phase_data={"fp": "fpC"})
        phases = self.registry.get_phases()
        assert phases
        assert all(p.get("fp") == "fpC" for p in phases)

    def test_duplicate_fp_still_records_the_phase(self):
        first = self.registry.emit_proposal_with_phase(
            fp="fpD", phase_id="phase_d1", phase_data={})
        second = self.registry.emit_proposal_with_phase(
            fp="fpD", phase_id="phase_d2", phase_data={})
        assert first
        assert not second
        assert len(self.registry.get_phases()) == 2

    def test_mutator_exposes_the_atomic_path(self):
        from oto.ledger.mutator import Proposal
        self.mutator.emit_candidate_phase(
            Proposal(fp="fpE", family="SS", shape="1x1x1", run_id="r"),
            phase_id="phase_e", phase_data={"config": {}})
        assert self.registry.get_proposal("fpE") is not None
        assert len(self.registry.get_phases()) == 1


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
        outcome, _detail = self.mutator.resolve_phase_dir(
            "fpW", pdir, run_id="run_w")
        obs = self.registry.observations_for("fpW")
        assert len(obs) == 1
        assert obs[0]["winner_freq"] == 3.0
        assert obs[0]["outcome"] == outcome

    def test_the_verdict_and_the_evidence_are_separate(self):
        pdir = self._phase_dir()
        self.registry.record_proposal(fp="fpV", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpV", pdir)
        assert self.registry.get_proposal("fpV")["outcome"] == "functional"
        assert len(self.registry.observations_for("fpV")) == 1

    def test_repeated_observations_accumulate(self):
        # Evidence is re-observable; the verdict is decided once. Modelling that
        # with one row each would make a re-measurement overwrite the basis of
        # the decision it had already recorded.
        pdir = self._phase_dir()
        self.registry.record_proposal(fp="fpU", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpU", pdir)
        outcome, _ = self.mutator.resolve_phase_dir("fpU", pdir)
        assert outcome == "pending"   # verdict not re-decided
        assert len(self.registry.observations_for("fpU")) == 2

    def test_a_missing_csv_leaves_winner_freq_null(self):
        d = self.tmp / "empty_phase" / "2_BenchmarkData"
        d.mkdir(parents=True)
        self.registry.record_proposal(fp="fpT", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpT", self.tmp / "empty_phase")
        obs = self.registry.observations_for("fpT")
        assert len(obs) == 1
        assert obs[0]["winner_freq"] is None

    def test_winner_freq_uses_the_canonical_reader(self):
        pdir = self._phase_dir(
            " SizeI , SizeJ , SizeL , Cijk_A , WinnerFreq \n"
            " 128 , 128 , 128 , 12.5 , 7 \n")
        self.registry.record_proposal(fp="fpS", family="SS", shape="1x1x1")
        self.mutator.resolve_phase_dir("fpS", pdir)
        assert self.registry.observations_for("fpS")[0]["winner_freq"] == 7.0

    def test_evidence_write_failure_does_not_block_the_verdict(self):
        self.registry.record_proposal(fp="fpY", family="SS", shape="1x1x1")
        d = self.tmp / "pd" / "2_BenchmarkData"
        d.mkdir(parents=True)
        (d / "c.csv").write_text(HEADER)
        self.registry.append_observation = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("boom"))
        outcome, _ = self.mutator.resolve_phase_dir("fpY", self.tmp / "pd")
        assert outcome == "functional"
        assert self.registry.get_proposal("fpY")["outcome"] == "functional"


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
        assert fresh.consecutive_failures("parentX") == 2
        assert fresh.neighbourhood_saturated("parentX")

    def test_a_success_resets_the_streak(self):
        self._record("s1", "parentY", "non_functional")
        self._record("s2", "parentY", "non_functional")
        self._record("s3", "parentY", "functional")
        fresh = Mutator(self.registry, self.tmp, self.analytics,
                        negative_cache_k=2)
        assert fresh.consecutive_failures("parentY") == 0
        assert not fresh.neighbourhood_saturated("parentY")

    def test_incremental_and_rebuilt_caches_agree(self):
        for i in range(4):
            self._record(f"i{i}", "parentZ", "non_functional")
        live = Mutator(self.registry, self.tmp, self.analytics,
                       negative_cache_k=3)
        rebuilt = live.rebuild_negative_cache()
        assert rebuilt["parentZ"] == 4
        assert live.consecutive_failures("parentZ") == rebuilt["parentZ"]

    def test_proposals_without_a_parent_are_ignored(self):
        self.registry.record_proposal(fp="np", family="SS", shape="1x1x1")
        self.registry.resolve_proposal("np", "non_functional")
        assert Mutator(self.registry, self.tmp, self.analytics).consecutive_failures("") == 0

    def test_the_archived_corpus_still_saturates_nothing(self):
        # Every measured mutant row is non-zero, so replaying the corpus must not
        # mark a shipped neighbourhood dead. This is the guard that stops the
        # cache firing on data it should not.
        m = Mutator(self.registry, self.tmp, self.analytics,
                    negative_cache_k=3)
        assert m.rebuild_negative_cache() == {}


# --------------------------------------------------------------- skip bypass
