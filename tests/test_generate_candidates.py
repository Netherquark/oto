"""CPU-only tests for harness/generate_candidates.py (proposal D4).

Covers the structural invariants of the generated candidate pool:

* one row per config (fp is shape-independent) with unique phase_ids + fps;
* graded (in-grid) rows only address cells inside the shipped grid;
* off-grid probe rows are graded False and structurally disjoint from the
  in-grid pool;
* the probe pool never leaks into the persistent seed overlay unless
  `--with-probes` is passed (the §6.1 parity rule pins overlay rows to the
  shipped grid);
* no fp collision with the committed deck or the curated seed rows.
* beat-the-spoof invariants (2026-10-09): banned families never carry GSU>1,
  the decided PLAN_BATCH rows emit (pads / PGR / PLR / NLCA / CC WGM8), and
  the HH/DD targets span side 256 (§14.5 Group A).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "harness"))

import yaml  # noqa: E402

from gfx90c_common import FAMILY_SHAPES  # noqa: E402
from generate_candidates import (  # noqa: E402
    _round_robin_prune,
    _strip_not_forwarded,
    _write_overlay,
    iter_candidates,
)


def _rows():
    return list(iter_candidates())


def _grid_cells():
    return {f: set(f"{s}x{s}x{s}" for s in ss) for f, ss in FAMILY_SHAPES.items()}


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
                        "ScheduleName", "NumBenchmarks", "tier", "graded"):
                assert key in r, (r["phase_id"], key)
            assert r["shapes"], r["phase_id"]

    def test_graded_rows_only_address_in_grid_cells(self):
        grid = _grid_cells()
        for r in _rows():
            if not r["graded"]:
                continue
            fam = str(r["config"].get("FamilyLabel", "")).upper()
            for shape in r["shapes"]:
                assert shape in grid[fam], (r["phase_id"], shape)

    def test_probe_rows_are_off_grid_and_unshipped(self):
        grid = _grid_cells()
        probes = [r for r in _rows() if not r["graded"]]
        assert probes
        for r in probes:
            assert r["phase_id"].startswith("probe_C")
            for shape in r["shapes"]:
                assert shape not in grid[
                    str(r["config"].get("FamilyLabel", "")).upper()]

    def test_graded_and_probe_pools_are_fp_disjoint(self):
        rows = _rows()
        graded = {r["fp"] for r in rows if r["graded"]}
        probes = {r["fp"] for r in rows if not r["graded"]}
        assert not (graded & probes)

    def test_every_target_and_probe_cell_is_covered(self):
        from generate_candidates import PROBE_CELLS, TARGET_CELLS
        found = {}
        for r in _rows():
            fam = str(r["config"].get("FamilyLabel", "")).upper()
            for shape in r["shapes"]:
                found.setdefault((fam, int(shape.split("x")[0])), 0)
                found[(fam, int(shape.split("x")[0]))] += 1
        for fam, sides in {**TARGET_CELLS, **PROBE_CELLS}.items():
            for side in sides:
                assert (fam, side) in found, f"no row covers {fam}:{side}"

    def test_no_fp_collision_with_deck(self):
        deck = yaml.safe_load((REPO / "phases.yaml").read_text())
        deck_fps = {str(p["fp"]) for p in deck}
        assert not ({r["fp"] for r in _rows()} & deck_fps)

    def test_no_fp_collision_with_curated_seed(self):
        doc = yaml.safe_load(
            (REPO / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml").read_text())
        seed_fps = {
            str(p["fp"]) for p in doc["phases"]
            if not str(p.get("origin", "")).startswith("generated_")
        }
        assert not ({r["fp"] for r in _rows()} & seed_fps)


class TestStripNotForwarded:
    def test_group_c_knobs_are_kept(self):
        # Group C (2026-10-09): LdsPadA/B, AF0EM, StaggerUStride and
        # StoreCInUnroll are forwarded by _write_phase_config behind the
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
    """Probe rows must stay out of the seed overlay unless opted in."""

    def _row(self, tag, fp):
        return {"phase_id": f"phase_cand_zz_{tag}", "fp": fp}

    def test_dry_run_default_excludes_probes(self):
        grid = [self._row("g1", "a"), self._row("g2", "b")]
        probes = [self._row("p", "c")]
        assert _write_overlay(grid, probes, dry_run=True) == 2

    def test_with_probes_includes_them(self):
        grid = [self._row("g1", "a"), self._row("g2", "b")]
        probes = [self._row("p", "c")]
        assert _write_overlay(grid, probes, dry_run=True, with_probes=True) == 3


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
        import harness.generate_candidates as gen
        monkeypatch.setattr(gen, "OVERLAY_PATH", self._seed(tmp_path))
        stripped, kept = gen._prune_candidates_from_seed(dry_run=True)
        assert (stripped, kept) == (2, 2)

    def test_strip_archives_and_keeps_rest(self, tmp_path, monkeypatch):
        import harness.generate_candidates as gen
        import yaml
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
        assert len(archived) == 2 and all(
            p["phase_id"].startswith("phase_cand_") for p in archived)

    def test_noop_when_nothing_to_strip(self, tmp_path, monkeypatch):
        import harness.generate_candidates as gen
        import yaml
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