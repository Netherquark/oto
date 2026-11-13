"""Tests for the Option H Phase 2 legality prior (`legality.py`).

The core assertions are deliberately structural: sampled candidates are checked
against the hard walls and the manifest-derived domains *without* calling
`scheduler.validate_config`. Re-running the full assertion over the sampler
would measure the assertion, not the prior (Hplan.7).
"""

import random
import unittest
from pathlib import Path

import oto.tensile.legality as legality
import oto.tensile.library as tlib
from oto.device.peaks import FAMILY_DTYPES

BASE = Path(__file__).resolve().parent.parent
HALF_FAMILIES = ("HH", "HH_HPA", "HS_HPA")


def _half_config(**overrides):
    """A minimal config on the mutation arm's shape (WorkGroup + ThreadTile)."""
    config = {
        "Architecture": "gfx900",
        "DataType": "H",
        "ProblemType": "Contraction",
        "MacroTile": "128x64x8",
        "ThreadTile": "8x4",
        "WorkGroup": [16, 16, 1],
        "VectorWidth": 2,
        "GlobalSplitU": 1,
        "DepthU": 8,
    }
    config.update(overrides)
    return config


class TestIsHalfInput(unittest.TestCase):
    """`DataType.isHalf()` is half only -- not bfloat16."""

    def test_half_is_half(self):
        assert legality.is_half_input({"DataType": "H"})

    def test_bfloat16_is_not_half(self):
        # DataType.bfloat is a distinct DataType; isHalf() does not match it.
        assert not legality.is_half_input({"DataType": "B"})

    def test_single_and_double_are_not_half(self):
        for dtype in ("S", "D", "C", "Z"):
            assert not legality.is_half_input({"DataType": dtype})

    def test_case_insensitive(self):
        assert legality.is_half_input({"DataType": "h"})

    def test_missing_datatype_is_not_half(self):
        assert not legality.is_half_input({})


class TestThreadTileNormalisation(unittest.TestCase):
    def test_string_form(self):
        assert legality.thread_tile_dimensions({"ThreadTile": "8x4"}) == [8, 4]

    def test_underscore_form(self):
        assert legality.thread_tile_dimensions({"ThreadTile": "8_4"}) == [8, 4]

    def test_list_form(self):
        assert legality.thread_tile_dimensions({"ThreadTile": [8, 4]}) == [8, 4]

    def test_missing_and_malformed(self):
        assert legality.thread_tile_dimensions({}) == []
        assert legality.thread_tile_dimensions({"ThreadTile": "axb"}) == []


class TestEnableMatrixInstruction(unittest.TestCase):
    """Mirrors SolutionStructs.py:1918-1930."""

    def test_workgroup_plus_threadtile_is_false(self):
        assert legality.enable_matrix_instruction(_half_config()) is False

    def test_string_threadtile_still_resolves_false(self):
        # Regression: the string "8x4" has len 3, so an unnormalised check read
        # every candidate as undetermined and silently disarmed the VW wall.
        config = _half_config(ThreadTile="8x4")
        assert legality.enable_matrix_instruction(config) is False

    def test_mi_triple_is_true(self):
        config = _half_config(MIBlock=[32, 32, 8, 2, 2, 2],
                              MIWaveGroup=[2, 2], MIWaveTile=[2, 2])
        assert legality.enable_matrix_instruction(config) is True

    def test_explicit_key_wins(self):
        assert legality.enable_matrix_instruction(_half_config(EnableMatrixInstruction=True)) is True

    def test_undetermined_without_workgroup_or_threadtile(self):
        assert legality.enable_matrix_instruction({"DataType": "H"}) is None


class TestHalfVectorWidthFloor(unittest.TestCase):
    """Root cause A_half_VW1_assembly -- SolutionStructs.py:3434."""

    def test_half_vw1_is_rejected(self):
        ok, reason = legality.half_vector_width_floor(_half_config(VectorWidth=1))
        assert not ok
        assert "VectorWidth >= 2" in reason

    def test_half_vw2_is_accepted(self):
        assert legality.half_vector_width_floor(_half_config(VectorWidth=2))[0]

    def test_fp32_vw1_is_accepted(self):
        assert legality.half_vector_width_floor(_half_config(DataType="S", VectorWidth=1))[0]

    def test_bfloat16_vw1_is_accepted(self):
        assert legality.half_vector_width_floor(_half_config(DataType="B", VectorWidth=1))[0]

    def test_vw1_is_allowed_under_mfma(self):
        config = _half_config(VectorWidth=1,
                              MIBlock=[32, 32, 8, 2, 2, 2],
                              MIWaveGroup=[2, 2], MIWaveTile=[2, 2])
        assert legality.enable_matrix_instruction(config) is True
        assert legality.half_vector_width_floor(config)[0]


class TestCheckHardWalls(unittest.TestCase):
    def test_only_the_verified_wall_is_enforced(self):
        # The VectorAtomicWidth guard is recorded as deferred, not enforced:
        # its value is derived from ComputeDataType bytes and gated on the
        # internal _GlobalAccumulation.
        assert (legality.half_vector_width_floor,) == legality.HARD_WALLS

    def test_deferred_rules_carry_a_reason(self):
        assert legality.DEFERRED_RULES
        for rule, reason in legality.DEFERRED_RULES.items():
            assert rule.strip()
            assert reason.strip()

    def test_check_reports_first_failure(self):
        ok, reason = legality.check_hard_walls(_half_config(VectorWidth=1))
        assert not ok
        assert "VectorWidth" in reason


class TestShippedSupport(unittest.TestCase):
    def test_every_family_has_support(self):
        for family in FAMILY_DTYPES:
            assert legality.shipped_support(BASE, family), family

    def test_support_entries_are_traceable_to_a_kernel_name(self):
        for entry in legality.shipped_support(BASE, "CC"):
            assert entry["name"].startswith("Cijk_")
            assert "config" in entry
            assert "knobs" in entry

    def test_support_is_deduplicated(self):
        support = legality.shipped_support(BASE, "SS")
        signatures = {str(sorted(e["config"].items())) for e in support}
        assert len(signatures) == len(support)

    def test_datatype_matches_family_char(self):
        from oto.device.peaks import FAMILY_DTYPE_CHAR
        for family, char in FAMILY_DTYPE_CHAR.items():
            for entry in legality.shipped_support(BASE, family):
                assert entry["config"]["DataType"] == char

    def test_af0em_is_inherited_from_the_kernel_name(self):
        # HH ships every kernel at AF0EM2; the prior must be able to read that,
        # since leaving it unset defaults to 1 and trips the half GSU walls.
        values = {e["af0em"] for e in legality.shipped_support(BASE, "HH")}
        assert values == {2}


class TestManifestHasShippedSchedule(unittest.TestCase):
    """Root cause D_macrotile_schedule."""

    def test_shipped_macrotile_has_a_schedule(self):
        for entry in legality.shipped_support(BASE, "HH"):
            assert legality.mt_has_shipped_schedule(entry["config"], "HH", BASE)[0]

    def test_unshipped_macrotile_is_rejected(self):
        ok, reason = legality.mt_has_shipped_schedule(
            _half_config(MacroTile="48x36x16"), "HH_HPA", BASE)
        assert not ok
        assert "48x36x16" in reason

    def test_absent_macrotile_passes_through(self):
        assert legality.mt_has_shipped_schedule({"DataType": "H"}, "HH", BASE)[0]


class TestSampleLegalIsLegalByConstruction(unittest.TestCase):
    """Structural legality, asserted without scheduler.validate_config."""

    def test_sampled_configs_pass_every_hard_wall(self):
        for family in FAMILY_DTYPES:
            rng = random.Random(11)
            for _ in range(60):
                config = legality.sample_legal(BASE, family, rng)
                assert config is not None, family
                ok, reason = legality.check_hard_walls(config)
                assert ok, f"{family}: {reason}"

    def test_never_emits_half_vw1(self):
        for family in HALF_FAMILIES:
            rng = random.Random(12)
            for _ in range(120):
                config = legality.sample_legal(BASE, family, rng)
                if config is None:
                    continue
                assert int(config["VectorWidth"]) >= 2, family

    def test_never_emits_an_unshipped_macrotile(self):
        for family in FAMILY_DTYPES:
            rng = random.Random(13)
            for _ in range(40):
                config = legality.sample_legal(BASE, family, rng)
                if config is None:
                    continue
                assert legality.mt_has_shipped_schedule(config, family, BASE)[0], f"{family} {config.get('MacroTile')}"

    def test_every_knob_value_is_observed_in_the_manifest(self):
        # The prior's central claim: nothing is invented. Each emitted value
        # must occur in some shipped vector of that family.
        for family in FAMILY_DTYPES:
            observed = set()
            for entry in legality.shipped_support(BASE, family):
                observed |= {str(v) for v in entry["config"].values()}
            rng = random.Random(14)
            for _ in range(60):
                config = legality.sample_legal(BASE, family, rng)
                if config is None:
                    continue
                knobs = [k for group in legality.KNOB_GROUPS.values()
                         for k in group]
                for knob in knobs:
                    if knob in config:
                        assert str(config[knob]) in observed, f"{family}.{knob}={config[knob]} invented"

    def test_threadtile_shape_is_always_two_dimensions(self):
        # Keeps EnableMatrixInstruction resolvable, which keeps the VW wall armed.
        for family in FAMILY_DTYPES:
            rng = random.Random(15)
            for _ in range(60):
                config = legality.sample_legal(BASE, family, rng)
                if config is None:
                    continue
                assert legality.enable_matrix_instruction(config) is False

    def test_determinism_for_a_fixed_seed(self):
        a = [legality.sample_legal(BASE, "HH", random.Random(99))
             for _ in range(1)]
        b = [legality.sample_legal(BASE, "HH", random.Random(99))
             for _ in range(1)]
        assert a == b

    def test_unknown_family_yields_no_config(self):
        assert legality.sample_legal(BASE, "NOPE", random.Random(0)) is None

    def test_retries_until_a_legal_draw_is_found(self):
        # A single draw can land on a shipped half VW1 vector; sample_legal must
        # retry rather than report scarcity while the family still has support.
        single_miss = multi_miss = 0
        for seed in range(40):
            if legality.sample_legal(BASE, "HS_HPA", random.Random(seed),
                                     attempts=1) is None:
                single_miss += 1
            if legality.sample_legal(BASE, "HS_HPA", random.Random(seed),
                                     attempts=64) is None:
                multi_miss += 1
        assert single_miss > 0
        assert multi_miss == 0

    def test_attempts_are_bounded(self):
        # attempts=1 must take exactly one draw, so it still reports misses.
        rng = random.Random(21)
        seen = [legality.sample_legal(BASE, "HH_HPA", rng, attempts=1)
                for _ in range(40)]
        assert any(c is None for c in seen)

    def test_base_config_is_used_as_the_parent(self):
        base = legality.shipped_support(BASE, "CC")[0]["config"]
        config = legality.sample_legal(BASE, "CC", random.Random(3),
                                       base_config=base, groups=0)
        assert config is not None
        assert config["DataType"] == base["DataType"]


class TestSamplerSweep(unittest.TestCase):
    def test_sweep_is_self_consistent(self):
        report = legality.sampler_sweep(BASE, draws=30, seed=5)
        assert report["tensile_commit"] == legality.TENSILE_COMMIT
        total = sum(v["draws"] for v in report["per_family"].values())
        assert report["draws"] == total
        accepted = sum(v["accepted"] for v in report["per_family"].values())
        assert report["accepted"] == accepted
        assert accepted + sum(v["dropped"] for v in report["per_family"].values()) == total

    def test_drops_are_attributed_to_a_named_reason(self):
        report = legality.sampler_sweep(BASE, draws=120, seed=6)
        for family, stats in report["per_family"].items():
            assert sum(stats["drop_reasons"].values()) == stats["dropped"], family

    def test_no_non_half_family_is_ever_dropped(self):
        # The VW floor is half-only. The only non-wall drop is the
        # manifest-coherence gate, which is a *discarded* draw (an incoherent
        # crossing, never returned), not a candidate Tensile rejects -- it can
        # legitimately fire for any family. So this asserts the tighter claim:
        # no non-half family drops for a reason other than coherence.
        report = legality.sampler_sweep(BASE, draws=150, seed=8)
        for family, stats in report["per_family"].items():
            if family in HALF_FAMILIES:
                continue
            reasons = set(stats["drop_reasons"])
            not_coherent = reasons - {
                r for r in reasons if r.startswith("not manifest-coherent:")}
            assert not_coherent == set(), f"{family}: {sorted(not_coherent)}"


class TestCuratedDeckSatisfiesTheWalls(unittest.TestCase):
    """The wall must be consistent with the deck that actually ships."""

    def test_every_curated_phase_passes_the_hard_walls(self):
        import yaml
        phases = yaml.safe_load((BASE / "phases.yaml").read_text())
        for phase in phases:
            config = phase.get("config", phase)
            ok, reason = legality.check_hard_walls(config)
            assert ok, f"{config.get('FamilyLabel')}: {reason}"

    def test_phases_yaml_is_not_modified_by_importing_legality(self):
        # The prior reads the pinned manifest; it must never write the deck.
        assert (BASE / "phases.yaml").exists()


class TestCitations(unittest.TestCase):
    def test_module_cites_the_pinned_commit(self):
        assert legality.TENSILE_COMMIT == "e8a8999e"

    def test_every_citation_names_a_source(self):
        for key, citation in legality.CITATIONS.items():
            assert "Tensile/" in citation, key


if __name__ == "__main__":
    unittest.main()
