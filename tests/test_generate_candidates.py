"""CPU-only tests for harness/generate_candidates.py (proposal D4).

Covers the structural invariants of the generated candidate pool:

* one row per config (fp is shape-independent) with unique phase_ids + fps;
* every row addresses a cell inside the shipped grid (§6.1: no contraction,
  no extension);
* no fp collision with the committed deck or the curated seed rows.
* beat-the-spoof invariants (2026-10-09): banned families never carry GSU>1,
  the decided PLAN_BATCH rows emit (pads / PGR / PLR / NLCA / CC WGM8), and
  the HH/DD targets span side 256 (§14.5 Group A).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "harness"))

import pytest
import yaml

from oto.device import loader as _loader
from oto.harness.generate_candidates import (
    _round_robin_prune,
    _strip_not_forwarded,
    _write_overlay,
    iter_candidates,
)


def _rows():
    return list(iter_candidates())


def _grid_cells():
    return {f: {f"{s}x{s}x{s}" for s in ss} for f, ss in _loader.current_profile().family_shapes.items()}


class TestPoolInvariants:
    def test_unique_phase_ids_and_fps(self):
        rows = _rows()
        ids = [r["phase_id"] for r in rows]
        fps = [r["fp"] for r in rows]
        assert len(ids) == len(set(ids))
        assert len(fps) == len(set(fps))

    def test_rows_carry_required_writer_fields(self):
        for r in _rows():
            for key in ("phase_id", "label", "dtype", "shapes", "config", "fp",
                        "ScheduleName", "NumBenchmarks", "tier"):
                assert key in r, (r["phase_id"], key)
            assert r["shapes"], r["phase_id"]

    def test_problem_sizes_are_numerically_ordered(self):
        """No candidate may scramble its ProblemSizes sweep order.

        Tensile runs a phase's ProblemSizes in deck order and each size's median
        absorbs the clock state the previous size left (claude.md 2.0.3). Sorting
        the shape *strings* produced ``1024, 192, 2048, 256, 512`` — 256^3 right
        after the slowest 2048^3 kernel, measured at ~1/3 clock (~55 vs ~210
        GFLOPS) and never eligible as its cell's winner. The deck and
        _loader.current_profile().family_shapes are numerically ascending; a candidate must match.
        """
        for r in _rows():
            sides = [int(s.split("x")[0]) for s in r["shapes"]]
            assert sides == sorted(sides), (r["phase_id"], r["shapes"])

    def test_problem_sizes_follow_family_shape_order(self):
        for r in _rows():
            fam = str(r["config"].get("FamilyLabel", "")).upper()
            sides = [int(s.split("x")[0]) for s in r["shapes"]]
            expected = [s for s in _loader.current_profile().family_shapes[fam] if s in set(sides)]
            assert sides == expected, (r["phase_id"], sides, expected)

    def test_every_row_only_addresses_in_grid_cells(self):
        grid = _grid_cells()
        for r in _rows():
            fam = str(r["config"].get("FamilyLabel", "")).upper()
            for shape in r["shapes"]:
                assert shape in grid[fam], (r["phase_id"], shape)

    def test_every_target_cell_is_covered(self):
        from oto.harness.generate_candidates import TARGET_CELLS
        found = set()
        for r in _rows():
            fam = str(r["config"].get("FamilyLabel", "")).upper()
            for shape in r["shapes"]:
                found.add((fam, int(shape.split("x")[0])))
        for fam, sides in TARGET_CELLS.items():
            for side in sides:
                assert (fam, side) in found, f"no row covers {fam}:{side}"

    def test_no_fp_collision_with_deck(self):
        deck = yaml.safe_load((REPO / "phases.yaml").read_text())
        deck_fps = {str(p["fp"]) for p in deck}
        assert not ({r["fp"] for r in _rows()} & deck_fps)

    def test_no_fp_collision_with_curated_seed(self):
        overlay = REPO / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"
        if not overlay.is_file():
            pytest.skip("phases.seed.overlay.yaml absent (gitignored artifact)")
        doc = yaml.safe_load(overlay.read_text())
        seed_fps = {
            str(p["fp"]) for p in doc["phases"]
            if not str(p.get("origin", "")).startswith("generated_")
        }
        assert not ({r["fp"] for r in _rows()} & seed_fps)


class TestShapeOrderingHelpers:
    """The two call sites that build a row's ``shapes`` list must order it
    numerically. A bare ``sorted`` here re-breaks the deck order and poisons the
    sweep (`results.md` 13.4)."""

    def test_shape_list_is_numeric(self):
        from oto.harness.candidate_pool import _shape_list
        assert _shape_list((256, 192, 2048)) == [
            "192x192x192", "256x256x256", "2048x2048x2048"]

    def test_merge_shapes_is_numeric(self):
        from oto.harness.candidate_pool import _merge_shapes
        assert _merge_shapes(["1024x1024x1024", "192x192x192"], (256,)) == [
            "192x192x192", "256x256x256", "1024x1024x1024"]


class TestNarrowRowMerge:
    """`_narrow_row_gen` adds a cell to an existing row instead of emitting a
    duplicate config. That merge is the third string-sort site; it must stay
    numeric even when the row it merges into is already scrambled."""

    def test_merge_into_existing_row_is_numeric(self, monkeypatch):
        import oto.harness.candidate_pool as cp

        configs = []
        real_fp = cp._fingerprint
        monkeypatch.setattr(
            cp, "_fingerprint",
            lambda cfg: (configs.append(cfg), real_fp(cfg))[1])

        def offer(fam, tier, pattern, knobs, sides, note=""):
            return {"phase_id": "offered", "fp": "offered",
                    "shapes": [f"{sides[0]}x{sides[0]}x{sides[0]}"]}

        # First pass, empty pool: learn every CC neighbour fingerprint.
        list(cp._narrow_row_gen(None, "CC", (256, 512), set(), {}, offer))
        assert configs, "expected CC narrow neighbours"

        poisoned = ["1024x1024x1024", "192x192x192"]
        pool = {real_fp(cfg): {"shapes": list(poisoned)} for cfg in configs}

        offered = []

        def offer2(fam, tier, pattern, knobs, sides, note=""):
            offered.append(tuple(sides))
            return {"phase_id": "offered2", "fp": "offered2",
                    "shapes": [f"{sides[0]}x{sides[0]}x{sides[0]}"]}

        list(cp._narrow_row_gen(None, "CC", (256, 512), set(), pool, offer2))

        # Every neighbour was already a pool row, so nothing was re-offered --
        # each row was instead extended in place.
        assert offered == []
        assert any(len(r["shapes"]) > 2 for r in pool.values())
        for fp, row in pool.items():
            sides = [int(s.split("x")[0]) for s in row["shapes"]]
            assert sides == sorted(sides), (fp, row["shapes"])


class TestStripNotForwarded:
    def test_group_c_knobs_are_kept(self):
        # Group C (2026-10-09): LdsPadA/B, AF0EM, StaggerUStride and
        # StoreCInUnroll are forwarded by write_phase_config behind the
        # ldspad_feasible gate, so the generator keeps them on the candidate.
        cfg, dropped = _strip_not_forwarded(
            {"MacroTile": "128x128x8", "LdsPadA": 1, "LdsPadB": 2,
             "StaggerUStride": 1, "StoreCInUnroll": 1,
             "AssertFree0ElementMultiple": 1})
        assert cfg == {"MacroTile": "128x128x8", "LdsPadA": 1, "LdsPadB": 2,
                       "StaggerUStride": 1, "StoreCInUnroll": 1,
                       "AssertFree0ElementMultiple": 1}
        assert not dropped

    def test_forwarded_knobs_are_kept(self):
        src = {"MacroTile": "128x128x8", "ThreadTile": "8x8",
               "DepthU": 8, "GlobalSplitU": 2, "WorkGroupMapping": 4}
        cfg, dropped = _strip_not_forwarded(dict(src))
        assert cfg == src
        assert not dropped


class TestWriteOverlayScoping:
    """`_write_overlay` counts only the rows not already scheduled in the seed."""

    def _row(self, tag, fp):
        return {"phase_id": f"phase_cand_zz_{tag}", "fp": fp}

    def test_dry_run_counts_only_new_rows(self, tmp_path, monkeypatch):
        import oto.harness.generate_candidates as gen
        seed = tmp_path / "phases.seed.overlay.yaml"
        seed.write_text(
            "phases:\n- phase_id: phase_cand_zz_old\n  fp: z\n")
        monkeypatch.setattr(gen, "OVERLAY_PATH", seed)
        fresh = [self._row("g1", "a"), self._row("g2", "b")]
        assert _write_overlay(fresh, dry_run=True) == 2
        # a row already present (by phase_id or fp) is not re-counted; the
        # dry run above did not persist anything, so only `old/z` is in the seed
        mixed = [self._row("old", "z"), self._row("g3", "c")]
        assert _write_overlay(mixed, dry_run=True) == 1


class TestPruneCandidatesFromSeed:
    """--prune-candidates strips phase_cand_* rows, archives them first, and
    keeps probe_*/accepted rows. The seed must never silently lose state."""

    def _seed(self, tmp_path):
        import yaml
        p = tmp_path / "phases.seed.overlay.yaml"
        p.write_text(yaml.safe_dump({"phases": [
            {"phase_id": "phase_cand_ss_1", "fp": "a"},
            {"phase_id": "phase_cand_hh_hpa_2", "fp": "b"},
            {"phase_id": "probe_N1_SS_64x64x8_8x8_vw4", "fp": "c"},
            {"phase_id": "phase_accepted_cc_192_1", "fp": "d"},
        ]}))
        return p

    def test_dry_run_counts_only(self, tmp_path, monkeypatch):
        import oto.harness.generate_candidates as gen
        monkeypatch.setattr(gen, "OVERLAY_PATH", self._seed(tmp_path))
        stripped, kept = gen._prune_candidates_from_seed(dry_run=True)
        assert (stripped, kept) == (2, 2)

    def test_strip_archives_and_keeps_rest(self, tmp_path, monkeypatch):
        import yaml

        import oto.harness.generate_candidates as gen
        seed = self._seed(tmp_path)
        monkeypatch.setattr(gen, "OVERLAY_PATH", seed)
        stripped, kept = gen._prune_candidates_from_seed(dry_run=False)
        assert (stripped, kept) == (2, 2)
        after = yaml.safe_load(seed.read_text())["phases"]
        assert [p["phase_id"] for p in after] == [
            "probe_N1_SS_64x64x8_8x8_vw4", "phase_accepted_cc_192_1"]
        archives = list(tmp_path.glob("phases.cand_archive.*.overlay.yaml"))
        assert len(archives) == 1
        archived = yaml.safe_load(archives[0].read_text())["phases"]
        assert len(archived) == 2
        assert all(
            p["phase_id"].startswith("phase_cand_") for p in archived)

    def test_noop_when_nothing_to_strip(self, tmp_path, monkeypatch):
        import yaml

        import oto.harness.generate_candidates as gen
        seed = tmp_path / "phases.seed.overlay.yaml"
        seed.write_text(yaml.safe_dump({"phases": [
            {"phase_id": "probe_N1_SS_64x64x8", "fp": "c"}]}))
        monkeypatch.setattr(gen, "OVERLAY_PATH", seed)
        assert gen._prune_candidates_from_seed(dry_run=False) == (0, 1)


class TestRoundRobinPrune:
    def test_cap_respected_and_fair(self):
        def row(tag, fam, tier, side):
            return {"phase_id": tag, "fp": tag, "tier": tier,
                    "config": {"FamilyLabel": fam}, "shapes": [f"{side}x{side}x{side}"]}

        rows = ([row(f"a{i}", "SS", "wide", 256) for i in range(20)] +
                [row(f"b{i}", "ZZ", "wide", 128) for i in range(20)])
        kept = _round_robin_prune(rows, 10)
        assert len(kept) == 10
        fams = [r["config"]["FamilyLabel"] for r in kept]
        assert fams.count("SS") == fams.count("ZZ") == 5

    def test_noop_below_cap(self):
        rows = list(iter_candidates())
        assert _round_robin_prune(rows, 10000) is rows

    def test_none_cap_keeps_the_whole_pool(self):
        rows = list(iter_candidates())
        assert _round_robin_prune(rows, None) is rows


class TestBeatTheSpoofInvariants:
    """2026-10-09 decided-config batch: banned rows stay out, decided rows
    actually emit (see potential_configs.md §14.5 and the PLAN_BATCH comment)."""

    def test_banned_families_never_carry_gsu(self):
        gsu_rows = [r for r in _rows()
                    if r.get("config", {}).get("GlobalSplitU", 1) != 1]
        fams = {str(r["config"].get("FamilyLabel", "")).upper() for r in gsu_rows}
        assert not (fams & {"HH", "CC", "ZZ", "HH_HPA", "HS_HPA"}), fams

    def test_ss_gsu4_wave_fill_emits(self):
        g4 = [r for r in _rows()
              if r["config"].get("FamilyLabel") == "SS"
              and r["config"].get("GlobalSplitU") == 4]
        assert g4, "SS GSU4 wave-fill rows must emit (§14.5 item 2)"

    def test_plan_batch_pad_rows_emit(self):
        pads = [r for r in _rows()
                if r["config"].get("LdsPadA") == 2 or r["config"].get("LdsPadB") == 2]
        fams = {str(r["config"].get("FamilyLabel", "")).upper() for r in pads}
        assert {"CC", "ZZ"} <= fams, fams

    def test_virgin_knob_rows_emit(self):
        rows = _rows()
        assert any(r["config"].get("LdsPadA") == 1 or r["config"].get("LdsPadB") == 1
                   for r in rows), "LdsPad=1 rows must emit (§R45)"
        assert any(r["config"].get("NLCA") == -1 for r in rows), "NLCA=-1 rows must emit"
        assert any(r["config"].get("MaxOccupancy") in (16, 32) for r in rows)
        assert any(r["config"].get("NonTemporalC") in (1, 2, 3) for r in rows)
        assert any(r["config"].get("PrefetchGlobalRead") == 2 for r in rows)
        assert any(r["config"].get("StaggerUMapping") in (1, 2) for r in rows)

    def test_plan_batch_residency_rows_emit(self):
        pgr = [r for r in _rows() if r["config"].get("PrefetchGlobalRead") == 0]
        plr = [r for r in _rows() if r["config"].get("PrefetchLocalRead") == 0]
        nlca = [r for r in _rows() if r["config"].get("NLCA") == 3]
        wgm8_cc = [r for r in _rows()
                   if r["config"].get("FamilyLabel") == "CC"
                   and r["config"].get("WorkGroupMapping") == 8]
        assert pgr and plr, "PGR/PLR residency rows must emit (§14.3/§14.5)"
        assert nlca, "NLCA=3 rows must emit on the 3-load 96x96 tile"
        assert wgm8_cc, "CC WGM8 steal-adapt rows must emit (§14.5 item 3)"

    def test_hh_and_dd_targets_span_256(self):
        hh = [r for r in _rows() if r["config"].get("FamilyLabel") == "HH"]
        dd = [r for r in _rows() if r["config"].get("FamilyLabel") == "DD"]
        assert any("256x256x256" in r["shapes"] for r in hh)
        assert any("256x256x256" in r["shapes"] for r in dd)

    def test_knob_variants_get_distinct_phase_ids(self):
        """Pads/PGR/NLCA variants share every id-encoded knob; the fp tail must
        keep their phase_ids unique (regression for the 2026-10-09 batch)."""
        target = [
            r for r in _rows()
            if r["config"].get("FamilyLabel") == "CC"
            and r["config"].get("MacroTile") == "64x64x8"
            and (r["config"].get("LdsPadA") or r["config"].get("LdsPadB")
                 or r["config"].get("PrefetchGlobalRead") == 0
                 or r["config"].get("WorkGroupMapping") == 8)
        ]
        assert len(target) >= 2, "expected several CC steal-adapt variants"
        ids = [r["phase_id"] for r in target]
        fps = [r["fp"] for r in target]
        assert len(ids) == len(set(ids)) == len(target)
        assert len(fps) == len(set(fps)) == len(target)


class TestEveryDeckRowIsGenerative:
    """No deck, ladder or batch row may be refused by the generator gate.

    The 2026-10-18 §R24/§R27 review found the same dead wide-complex tiles
    duplicated across three tables (`decks.FAMILY_DECKS`, `candidate_rows.LADDER`
    and `candidate_rows.PLAN_BATCH`): CC 128x128x8 (the accumulators alone fill
    the 64K register file -> Tensile error 4), ZZ 128x64/64x128 at 4x2/2x4
    threads (GLVW does not divide the packed access), SS/HH 32x32x16/2x2 at
    VW4/VW8 (a 2-wide thread tile cannot be a multiple of a 4/8-wide load), and
    an SS 128x128x16 LSU-2 tie-adapt row (131072 B of LDS reduction buffer
    against the 65536 ceiling). A row the gate refuses is a wasted draw, so this
    pins that each table is gate-clean under every contraction pattern it is
    instantiated with.

    It is a *pin on the tables*, not on the gate: if the gate is calibrated to
    accept a row that is genuinely legal, that row must be allowed here, which is
    why the assertion is "no row refused", not an exact set.
    """

    PATTERNS = ("Ailk_Bljk", "Ailk_Bjlk", "Alik_Bljk", "Alik_Bjlk")

    @staticmethod
    def _template(family: str, pattern: str) -> dict:
        return {"Architecture": "gfx90c",
                "DataType": _loader.current_profile().family_dtype_char[family],
                "ContractionPattern": pattern,
                "ScheduleName": "isa", "FamilyLabel": family}

    def _is_refused(self, family, pattern, knobs):
        from oto.tensile.candidate import CandidateGenerator
        gen = CandidateGenerator(REPO)
        cfg = {**self._template(family, pattern), **knobs}
        return not gen.validate_config(cfg)[0]

    def test_family_decks_are_gate_clean(self):
        from oto.tensile.decks import FAMILY_DECKS
        bad = []
        for family, rows in FAMILY_DECKS.items():
            # Legal under *some* pattern is enough: the generator emits the
            # row for whichever patterns accept it.
            bad.extend((family, knobs) for knobs in rows
                       if all(self._is_refused(family, p, knobs)
                              for p in self.PATTERNS))
        assert bad == [], f"gate refuses all patterns for: {bad}"

    def test_ladder_is_gate_clean(self):
        from oto.harness.candidate_rows import LADDER
        bad = []
        for family, rows in LADDER.items():
            bad.extend((family, knobs) for knobs in rows
                       if all(self._is_refused(family, p, knobs)
                              for p in self.PATTERNS))
        assert bad == [], f"ladder rows refused by the gate: {bad}"

    def test_plan_batch_is_gate_clean(self):
        from oto.harness.candidate_rows import PLAN_BATCH
        bad = [(e["fam"], e.get("note"))
               for e in PLAN_BATCH
               if self._is_refused(
                   e["fam"], e["pattern"],
                   {k: v for k, v in e.items()
                    if k not in ("fam", "pattern", "note")})]
        assert bad == [], f"PLAN_BATCH rows refused by the gate: {bad}"


class TestDeckLoader:
    def test_accepts_a_deck_list_and_a_seed_overlay(self, tmp_path):
        """The preflight must be able to check the launch set, not just the deck."""
        from oto.checks.candidates import load_deck
        row = {"phase_id": "phase_x", "config": {}}
        deck = tmp_path / "deck.yaml"
        deck.write_text(yaml.safe_dump([row]))
        overlay = tmp_path / "overlay.yaml"
        overlay.write_text(yaml.safe_dump({"run_id": "seed", "phases": [row]}))
        assert load_deck(deck) == [row]
        assert load_deck(overlay) == [row]


class TestLdsPadPrefetchGate:
    def test_pgr2_is_gated_by_doubled_lds(self):
        from oto.tensile.gates.occupancy import ldspad_feasible
        base = {"Architecture": "gfx90c", "DataType": "S", "FamilyLabel": "SS",
                "MacroTile": "128x128x8", "ThreadTile": "8x8", "VectorWidth": 4,
                "DepthU": 16, "PrefetchGlobalRead": 2}
        ok_small, _ = ldspad_feasible(base)
        assert not ok_small
        base2 = {"Architecture": "gfx90c", "DataType": "S", "FamilyLabel": "SS",
                 "MacroTile": "32x32x8", "ThreadTile": "4x4", "VectorWidth": 4,
                 "DepthU": 4, "PrefetchGlobalRead": 2}
        ok2, _ = ldspad_feasible(base2)
        assert ok2
