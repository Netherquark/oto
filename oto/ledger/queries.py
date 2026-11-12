#!/usr/bin/env python3
"""The registry's read side: records, phases and run lookups.

Owns: every query an operator or a caller makes of the ledger -- one run
row, the record log with its run/type filters, the phase table, the newest
run id, the retirement and novelty lookups, and the stale-run sweep.
Does NOT own: the write side (oto.ledger.registry_core) or the Option-H
proposal ledger (oto.ledger.proposals).
Public API: QueryMixin."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional



class QueryMixin:
    """The registry's read side: records, phases and run lookups, mixed into SQLiteRegistry."""


    def run_row(self, run_id: str) -> Optional[sqlite3.Row]:
        """One run's registry row, or None.

        Read helper for consumers that need run lifecycle timestamps
        (started_at / completed_at) -- e.g. the acceptance report's execution
        time. Returns None for an unknown run_id so callers do not have to
        distinguish "no such run" from "no value in the column".
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchall()
        return rows[0] if rows else None
    def append_record(self, record: Dict[str, Any], run_id: str = "default") -> int:
        """
        Append a single record to the ledger.

        Args:
            record: Dictionary to serialize as JSON
            run_id: Run identifier

        Returns:
            Record ID
        """
        record_type = record.get("type", "general")
        with self._writing() as conn:
            cursor = conn.execute(
                """
                INSERT INTO records (run_id, record_type, data, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, record_type, json.dumps(record), datetime.now().isoformat())
            )
            return cursor.lastrowid
    def read_records(
        self,
        run_id: Optional[str] = None,
        record_type: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Read records with optional filtering.

        Args:
            run_id: Optional run ID filter
            record_type: Optional record type filter
            limit: Optional result limit

        Returns:
            List of parsed dictionaries
        """
        with self._get_conn() as conn:
            query = "SELECT data FROM records WHERE 1=1"
            params = []

            if run_id:
                query += " AND run_id = ?"
                params.append(run_id)

            if record_type:
                query += " AND record_type = ?"
                params.append(record_type)

            query += " ORDER BY id ASC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor = conn.execute(query, params)
            return [json.loads(row["data"]) for row in cursor]
    def append_phase(self, phase_id: str, fingerprint: str, phase_data: Dict[str, Any]) -> int:
        """
        Append a phase with deduplication by fingerprint.

        Args:
            phase_id: Phase identifier
            fingerprint: Config fingerprint
            phase_data: Phase configuration

        Returns:
            Phase ID (or existing ID if duplicate)
        """
        with self._writing() as conn:
            # Check for existing phase with same fingerprint or phase_id
            cursor = conn.execute(
                "SELECT id FROM phases WHERE fingerprint = ? OR phase_id = ?",
                (fingerprint, phase_id)
            )
            existing = cursor.fetchone()

            if existing:
                return existing["id"]

            # Insert new phase with OR IGNORE safeguard
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO phases (phase_id, fingerprint, data, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (phase_id, fingerprint, json.dumps(phase_data), datetime.now().isoformat())
            )
            if cursor.lastrowid:
                return cursor.lastrowid
            
            # If ignored due to race, fetch existing
            cursor = conn.execute("SELECT id FROM phases WHERE phase_id = ?", (phase_id,))
            row = cursor.fetchone()
            return row["id"] if row else 0
    def get_phases(self) -> List[Dict[str, Any]]:
        """Get all phases from database."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT data FROM phases ORDER BY id ASC")
            return [json.loads(row["data"]) for row in cursor]
    def latest_run_id(self, arm: Optional[str] = None) -> Optional[str]:
        """Return the most recently registered run id (from the runs table).

        arm='native' restricts to non-reference runs. The A/B subject must be a
        native run: the newest row overall is usually the gfx900 reference
        floor, and scoring that as the subject makes _reference_floor_runs
        exclude it from its own floor chain (it excludes the subject when the
        subject is a gfx900_ref run). The floor then gets compared against
        itself minus its own head, which halves the spoof kernel count and
        silently moves verdicts -- CC:1024 LOSS->TIE, HH_HPA:4096 LOSS->WIN,
        HS_HPA:4096 TIE->WIN on the current corpus.
        """
        query = "SELECT run_id FROM runs"
        params: tuple = ()
        if arm == "native":
            query += " WHERE run_id NOT LIKE 'gfx900_ref_%'"
        query += " ORDER BY id DESC LIMIT 1"
        with self._get_conn() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return row["run_id"] if row else None
    def is_phase_retired(self, phase_id: str) -> bool:
        """Check if a phase is retired at Tier 1 (fp-less)."""
        clean_id = str(phase_id).replace("phase_", "")
        records = self.read_records(record_type="retire")
        for r in records:
            r_phase = str(r.get("phase_id", "")).replace("phase_", "")
            if r_phase == clean_id and not r.get("fp"):
                return True
        return False
    def is_config_retired(self, phase_id: str, fp: str) -> bool:
        """Check if a (phase, fp) pair is retired at Tier 2."""
        clean_id = str(phase_id).replace("phase_", "")
        records = self.read_records(record_type="retire")
        for r in records:
            r_phase = str(r.get("phase_id", "")).replace("phase_", "")
            r_fp = r.get("fp", "")
            if r_phase == clean_id and r_fp == fp:
                return True
        return False
    def has_fp_passed(self, fp: str) -> bool:
        """Check if a config fp has ever had a PASS / completed record."""
        if not fp:
            return False
        # Narrow with SQL first (indexed on json_extract(data,'$.fp')) rather
        # than pulling every record's JSON into Python and filtering there. The
        # verdict rule is unchanged: same status set, same nested-result check.
        # Only the cost changed.
        with self._get_conn() as conn:
            try:
                rows = conn.execute(
                    "SELECT data FROM records WHERE json_extract(data, '$.fp') = ?",
                    (fp,)
                ).fetchall()
            except sqlite3.OperationalError:
                # No JSON1: fall back to the original full scan rather than
                # changing the answer.
                rows = conn.execute("SELECT data FROM records").fetchall()
        for row in rows:
            r = json.loads(row["data"])
            if r.get("status") in ["PASS", "completed", "success"] or (
                isinstance(r.get("result"), dict)
                and r.get("result", {}).get("status") in ["PASS", "completed", "success"]
            ):
                return True
        return False
    def has_run_benchmarked(self, run_id: str, fp: str) -> bool:
        """Check if a specific run already produced a completed record for fp.

        Scoped to the seed-overlay semantics: a seed phase is measured once per
        run and then stays out of the identical-fp bypass for the rest of that
        run (a static seed must not re-benchmark itself on every iteration). A
        failed/interrupted attempt does not count as passed, so it retries.
        """
        if not fp or not run_id:
            return False
        with self._get_conn() as conn:
            try:
                rows = conn.execute(
                    "SELECT data FROM records WHERE run_id = ? "
                    "AND json_extract(data, '$.fp') = ?",
                    (run_id, fp)
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT data FROM records WHERE run_id = ?",
                    (run_id,)
                ).fetchall()
        for row in rows:
            r = json.loads(row["data"])
            if r.get("status") in ["PASS", "completed", "success"] or (
                isinstance(r.get("result"), dict)
                and r.get("result", {}).get("status") in ["PASS", "completed", "success"]
            ):
                return True
        return False
    def cleanup_stale_runs(self) -> int:
        """
        Mark any 'started' runs as 'interrupted' (orphans from prior crash/Ctrl+C).

        Returns:
            Number of runs cleaned up
        """
        with self._writing() as conn:
            cursor = conn.execute(
                """
                UPDATE runs SET status = 'interrupted', completed_at = ?
                WHERE status = 'started'
                """,
                (datetime.now().isoformat(),)
            )
            cleaned = cursor.rowcount
        # A hard-crashed run (SIGKILL / power loss) never reached the SIGINT
        # finaliser, so its on-disk data is folded into the cache only here —
        # refresh once so the run that follows starts from a fresh kernel_db.
        if cleaned and self._should_rebuild_kernel_db("interrupted"):
            self._rebuild_kernel_db_after_run(
                f"{cleaned} stale run(s)", "interrupted")
        return cleaned
