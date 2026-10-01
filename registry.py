#!/usr/bin/env python3
"""
registry_sqlite.py — SQLite-based registry for oto

Replaces fcntl.flock with proper ACID database for concurrent safety.
All records append-only; database schema supports evolution.
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
from datetime import datetime


class SQLiteRegistry:
    """SQLite-based append-only registry with ACID guarantees."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.results_dir = self.base_dir / "gfx90c_results"
        self.runs_dir = self.base_dir / "gfx90c_runs"
        self._ensure_dirs()
        self.db_path = self.results_dir / "registry.db"
        self._init_db()

    def _ensure_dirs(self):
        """Ensure registry directories exist."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            # Records table (append-only ledger)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    data JSON NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            # Phases table (manifest with deduplication)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS phases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phase_id TEXT UNIQUE NOT NULL,
                    fingerprint TEXT NOT NULL,
                    data JSON NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Runs table (checkpointing)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    metadata JSON,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)

            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_run_id ON records(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_type ON records(record_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phases_fingerprint ON phases(fingerprint)")

            conn.commit()

    @contextmanager
    def _get_conn(self):
        """Context manager for database connection with automatic cleanup."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        with self._get_conn() as conn:
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

    def create_run_dir(self, run_id: Optional[str] = None) -> Path:
        """
        Create a new run directory and checkpoint it.

        Args:
            run_id: Optional custom run ID

        Returns:
            Path to the new run directory
        """
        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        run_path = self.runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        # Checkpoint in database
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, status, metadata, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, "started", json.dumps({}), datetime.now().isoformat())
            )

        return run_path

    def update_run_status(self, run_id: str, status: str, metadata: Optional[Dict] = None) -> None:
        """
        Update run status and metadata.

        Args:
            run_id: Run identifier
            status: New status
            metadata: Optional metadata dict
        """
        with self._get_conn() as conn:
            if metadata:
                conn.execute(
                    """
                    UPDATE runs SET status = ?, metadata = ?, completed_at = ?
                    WHERE run_id = ?
                    """,
                    (status, json.dumps(metadata), datetime.now().isoformat(), run_id)
                )
            else:
                conn.execute(
                    """
                    UPDATE runs SET status = ?, completed_at = ?
                    WHERE run_id = ?
                    """,
                    (status, datetime.now().isoformat(), run_id)
                )

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
        with self._get_conn() as conn:
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
        records = self.read_records()
        for r in records:
            if r.get("fp") == fp:
                if r.get("status") in ["PASS", "completed", "success"] or (
                    isinstance(r.get("result"), dict) and r.get("result", {}).get("status") in ["PASS", "completed", "success"]
                ):
                    return True
        return False


    def cleanup_stale_runs(self) -> int:
        """
        Mark any 'started' runs as 'interrupted' (orphans from prior crash/Ctrl+C).

        Returns:
            Number of runs cleaned up
        """
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE runs SET status = 'interrupted', completed_at = ?
                WHERE status = 'started'
                """,
                (datetime.now().isoformat(),)
            )
            return cursor.rowcount


def fingerprint_config(config: Dict[str, Any]) -> str:
    """
    Generate a canonical fingerprint for a Tensile config.

    Uses JSON with sorted keys for deterministic output.

    Args:
        config: Tensile config dictionary

    Returns:
        SHA256 hex digest
    """
    import hashlib
    canonical = json.dumps(config, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
