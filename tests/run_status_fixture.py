#!/usr/bin/env python3
"""Shared scaffolding for the run_status regression tests.

Owns: the throwaway registry builder (``StatusFixture``) and the three
synthetic record helpers (``_phase``, ``_deck``, ``_record``) used by every
``Test*`` class in ``tests/test_run_status_report.py`` and
``tests/test_run_status_live.py``. The suite stubs the shipped manifests with
a tiny synthetic deck, so no Tensile artifacts or GPU exist here.
Does NOT own: production code; everything here is test-local.
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

# This file lives in tests/, so the repo root is one level up. ROOT is both the
# import root and the data root, and both are the repo root -- the harness
# modules are imported flat, so they sit beside this file's parent.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import oto.metrics.run_status as rs
import oto.tensile.shipped_manifest as tl
from oto.runners.paths import results_rel


def _phase(tag: str, kernel: str) -> dict:
    """A synthetic emitted phase with a stable tag suffix in its phase_id."""
    return {
        "phase_id": f"phase_ss_gfx900_Ailk_Bjlk_mt32-tt4-vw4-du16-gsu1-{tag}",
        "kernel": kernel,
    }


def _deck() -> list:
    """5 cells: 2 ILLEGAL, 2 UNDER-SPECIFIED, 1 UNREPRODUCIBLE."""
    phases = [_phase("aaa111", "k_aaa"), _phase("bbb222", "k_bbb"),
              _phase("ccc333", "k_ccc"), _phase("ddd444", "k_ddd"),
              _phase("eee555", "k_eee")]
    for i, p in enumerate(phases):
        p["_tier"] = (tl.TIER_FIRST if i < 2 else
                      tl.TIER_HELD if i < 4 else tl.TIER_DROP)
    return phases


def _record(run_id: str, phase: dict, status: str, result: str | None = None,
            *, with_key: bool = True, timestamp: str | None = None) -> dict:
    rec = {
        "type": "general",
        "phase_id": phase["phase_id"],
        "status": status,
        "result": {"status": result} if result is not None else {},
    }
    if with_key:
        rec["phase_key"] = tl.phase_key(phase)
    return rec


class StatusFixture(unittest.TestCase):
    """Builds a temp registry + a stubbed deck, then runs build_report."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        # build_report reads the registry at <base>/<codename>_results/registry.db
        self.db = self.base / results_rel("registry.db")
        self.db.parent.mkdir(parents=True)
        self.phases = _deck()
        self.tiers = {tl.phase_key(p): p["_tier"] for p in self.phases}
        self.keys = [tl.phase_key(p) for p in self.phases]
        self._init_db()

    def tearDown(self):
        self._tmp.cleanup()

    def _init_db(self):
        """Mirror registry.SQLiteRegistry._init_db, minus the side effects."""
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " run_id TEXT NOT NULL, record_type TEXT NOT NULL,"
                " data JSON NOT NULL, timestamp TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " run_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL,"
                " metadata JSON, started_at TEXT NOT NULL, completed_at TEXT)")
            conn.execute("CREATE INDEX idx_records_run_id ON records(run_id)")

    def add_run(self, run_id: str, status: str, records, *,
                resume_of: str | None = None, started: str | None = None,
                completed: str | None = None):
        meta = {"resume_of": resume_of} if resume_of else None
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO runs (run_id, status, metadata, started_at,"
                " completed_at) VALUES (?,?,?,?,?)",
                (run_id, status, json.dumps(meta) if meta else None,
                 started or "2026-09-25T10:00:00",
                 completed or ("2026-09-25T12:00:00"
                               if status == "completed" else None)))
            for rec in records:
                conn.execute(
                    "INSERT INTO records (run_id, record_type, data, timestamp)"
                    " VALUES (?,?,?,?)",
                    (run_id, "general", json.dumps(rec),
                     "2026-09-25T11:00:00"))

    def report(self, plan: rs.RunPlan = None, now=None):
        tiers = self.tiers

        def fake_emit(shipped, arch="gfx900", schedule="vega10"):
            return [{k: v for k, v in p.items() if k != "_tier"}
                    for p in self.phases]

        def fake_tier(phase, manifest):
            return tiers[tl.phase_key(phase)]

        with mock.patch.object(tl, "load_shipped_manifest",
                               return_value={"solutions": []}), \
             mock.patch.object(tl, "emit_spoof_phases", side_effect=fake_emit), \
             mock.patch.object(tl, "tier_for", side_effect=fake_tier), \
             mock.patch.object(rs.tlib, "load_rerun_manifest", return_value={}):
            return rs.build_report(self.base, None,
                                   plan or rs.RunPlan(rerun_illegal=True),
                                   now=now)
