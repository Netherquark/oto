#!/usr/bin/env python3
"""test_corpus_census.py — the corpus-history read on a synthetic database.

Pins the model, not a live corpus count:

* a row's statistic is its seed median, never its best seed (``gflops_best``);
* an axis census counts each distinct value and reports the best median at it,
  skipping missing/zero placeholders instead of inventing a value;
* a geometry census collapses repeated measurement of one geometry and ranks
  by the best median, not by row count or best seed;
* a cell history is per-geometry (replication is not a new candidate), is
  restricted to cube shapes, and carries the floor reference;
* the CLI's ``--cell``, ``--knob`` and ``--json`` paths produce the documented
  sections from a database file.

Run: python3 -m pytest -q tests/test_corpus_census.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.harness import corpus_census as cc  # noqa: E402

GEOM_A = {"MacroTile": "[128, 128]", "ThreadTile": "[8, 8]", "DepthU": "8",
          "VectorWidth": "4", "GlobalSplitU": "1", "WorkGroup": "[16, 16, 1]"}
GEOM_B = {"MacroTile": "[64, 64]", "ThreadTile": "[4, 4]", "DepthU": "16",
          "VectorWidth": "2", "GlobalSplitU": "1", "WorkGroup": "[8, 8, 1]"}


def _row(shape="1024x1024x1024", median=0.0, best=0.0, family="SS",
         typecode="SB", phase="phase_a", **geometry):
    return {"phase": phase, "shape": shape, "family": family,
            "typecode": typecode, "gflops_median": median,
            "gflops_best": best, "n_seeds": 16, **geometry}


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "kernel_db.json"
    path.write_text(json.dumps({
        "run_a": [
            _row(median=1000.0, best=1300.0, phase="p1", **GEOM_A),
            _row(median=1100.0, best=1200.0, phase="p2", **GEOM_A),
            _row(median=900.0, best=5000.0, phase="p3", **GEOM_B),
            _row(median=0.0, best=0.0, phase="p4",
                 **{**GEOM_A, "DepthU": "0"}),
            _row(shape="32x4096x1", median=800.0, best=1400.0, phase="p5",
                 **GEOM_B),
        ],
        "gfx900_ref_locked_x": [
            _row(median=950.0, best=990.0, family="SS", typecode="SB",
                 phase="floor", **GEOM_B),
        ],
    }))
    return str(path)


def test_load_rows_splits_native_and_floor(database):
    native = cc.load_rows(database)
    assert {row["side"] for row in native} == {"native"}
    assert len(native) == 5
    every = cc.load_rows(database, side="all")
    assert {row["side"] for row in every} == {"native", "floor"}
    assert len(every) == 6
    with pytest.raises(ValueError):
        cc.load_rows(database, side="bogus")


def test_axis_census_uses_median_and_skips_placeholders(database):
    rows = cc.load_rows(database)
    census = {(r["axis"], r["value"]): r for r in cc.axis_census(rows)}
    # two rows at DepthU 8: the best median is 1100, never the 1300 best seed
    assert census[("DepthU", "8")]["n"] == 2
    assert census[("DepthU", "8")]["best"] == 1100.0
    # "0" is a placeholder, not a measured DepthU
    assert ("DepthU", "0") not in census
    # GEOM_B's best seed is 5000, but its median is what the census reports
    assert census[("DepthU", "16")]["best"] == 900.0


def test_geometry_census_collapses_one_geometry(database):
    rows = cc.load_rows(database)
    census = [r for r in cc.geometry_census(rows) if r["typecode"] == "SB"]
    assert len(census) == 2
    by_tile = {r["macro_tile"]: r for r in census}
    assert by_tile["[128, 128]"]["n"] == 2
    assert by_tile["[128, 128]"]["best"] == 1100.0
    assert by_tile["[64, 64]"]["best"] == 900.0


def test_cell_history_is_per_geometry_and_includes_floor(database):
    rows = cc.load_rows(database, side="all")
    history = cc.cell_history(rows, "SS", 1024)
    assert history["n_attempts"] == 3      # p4 (DepthU 0) and p5 (non-cube) out
    assert history["n_geometries"] == 2
    assert history["geometries"][0]["macro_tile"] == "[128, 128]"
    assert history["geometries"][0]["n"] == 2
    assert history["geometries"][0]["gflops"] == 1100.0
    assert history["floor_best"]["gflops"] == 950.0
    assert cc.cell_history(rows, "SS", 1024, top=1)["geometries"][0]["n"] == 2
    assert len(cc.cell_history(rows, "SS", 1024, top=1)["geometries"]) == 1


def test_cli_cell_knob_and_json(database, capsys, tmp_path):
    out = tmp_path / "census.json"
    assert cc.main(["--db", database, "--cell", "SS:1024", "--top", "1"]) == 0
    assert "floor best" in capsys.readouterr().out

    assert cc.main(["--db", database, "--knob", "DepthU", "--family", "SS"]) == 0
    text = capsys.readouterr().out
    assert "DepthU" in text and "MacroTile" not in text

    assert cc.main(["--db", database, "--family", "SS", "--json", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["meta"]["family"] == "SS"
    assert {r["axis"] for r in payload["axes"]} == set(cc.AXES)
    assert len(payload["geometries"]) == 2
