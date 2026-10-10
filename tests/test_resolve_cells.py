#!/usr/bin/env python3
"""
test_resolve_cells.py — harness.resolve_cells per-cell winner resolution.

Regression guards for the 38-cell evidence generator (potential_configs.md §2,
the authoritative source for per-family triage / spoof-steal candidate work):

  * exactly the shipped deck — (family, shape) equals shipped_cell_set()
    (knowledge_base.md §6.1), no added/absent cells;
  * verdicts + native/floor values match acceptance_report.json field-for-field;
  * every cell that has a native winner phase resolves a FULL structural config
    (MacroTile present) from the winner run's configs/*.yaml or the registry —
    the "winner-run-first" resolution ordering;
  * HPA floor cells (whose shipped floor rows are unresolved, verdict '?')
    degrade to an empty spoof config instead of crashing;
  * meta provenance counts are self-consistent (n_cells, resolver keys ≥ yamls).

Run: python3 -m pytest -q tests/test_resolve_cells.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from gfx90c_common import shipped_cell_set  # noqa: E402
from harness import resolve_cells  # noqa: E402


@pytest.fixture(scope="module")
def evidence():
    cells, meta = resolve_cells.build(str(BASE))
    return cells, meta


def test_deck_is_exactly_the_shipped_grid(evidence):
    cells, _ = evidence
    got = {(c["family"], c["shape"]) for c in cells}
    assert got == shipped_cell_set()
    assert len(cells) == 38


def test_verdicts_and_values_match_acceptance_report(evidence):
    cells, _ = evidence
    report = json.load(open(BASE / "gfx90c_results" / "acceptance_report.json"))
    by_cell = {c["family"] + ":" + c["shape"]: c for c in cells}
    for v in report["per_cell_verdicts"]:
        c = by_cell[v["family"] + ":" + v["shape"]]
        assert c["verdict"] == v["verdict"]
        assert c["native_value"] == v.get("native_value")
        assert c["spoof_value"] == v.get("spoof_value")
        assert c["native_winner_phase"] == (v.get("native_winner_phase") or "")
        assert c["native_winner_run"] == (v.get("native_winner_run") or "")
    assert {c["verdict"] for c in cells} <= {"WIN", "TIE", "LOSS", "?"}


def test_every_native_winner_resolves_full_config(evidence):
    cells, _ = evidence
    unresolved = [
        (c["family"], c["shape"], c["native_winner_phase"])
        for c in cells
        if c["native_winner_phase"] and not c["native_config"].get("MacroTile")
    ]
    assert unresolved == [], f"winner configs failed to resolve: {unresolved}"
    # the deck's hardest cells must resolve to the documented winner knobs
    by = {(c["family"], c["shape"]): c for c in cells}
    # CC:512 resolver-final winner: MT64x64/4x4/VW2/DU8/WGM4+NLCA1 (not WGM8)
    assert by[("CC", "512x512x512")]["native_config"]["WorkGroupMapping"] == 4
    assert by[("CC", "512x512x512")]["native_config"]["NumLoadsCoalescedA"] == 1
    assert by[("ZZ", "1024x1024x1024")]["native_config"]["DepthU"] == 16
    assert by[("HH", "256x256x256")]["native_config"]["MacroTile"] == [32, 64]


def test_unresolved_hpa_floor_rows_are_tolerated(evidence):
    cells, _ = evidence
    for c in cells:
        if c["family"] in ("HH_HPA", "HS_HPA"):
            assert c["spoof_config"] == {} or c["spoof_config"].get("MacroTile")
            # never a crash, never a phantom floor winner
            assert isinstance(c["spoof_config"], dict)


def test_meta_provenance_is_consistent(evidence):
    _, meta = evidence
    assert meta["n_cells"] == 38
    assert meta["sources"]["run_config_yamls"] >= 6000
    assert meta["sources"]["resolver_keys"] >= meta["sources"]["run_config_yamls"]
    assert meta["sources"]["registry_phases"] >= 1000
    assert meta["acceptance_run_id"] == "run_20261009_205427"


def test_table_and_tsv_render(evidence):
    cells, _ = evidence
    t = resolve_cells._table(cells)
    assert t.count("\n") == len(cells)          # header + one row per cell
    assert "NATIVE WINNER CONFIG" in t
    s = resolve_cells._tsv(cells).split("\n")
    assert s[0].startswith("family\tshape")
    assert len(s) == len(cells) + 1