#!/usr/bin/env python3
"""
registry_sqlite.py — SQLite-based registry for oto

Replaces fcntl.flock with proper ACID database for concurrent safety.
All records append-only; database schema supports evolution.
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager
from datetime import datetime

# Run-terminal statuses that imply benchmark data may have landed and the
# kernel_db cache should be refreshed. `skipped` / `smoke` / `failed`
# (gfx900-ref with zero executions) produce no new corpus, so they do not
# trigger a rebuild.
_KERNEL_DB_REBUILD_STATUSES = {"completed", "interrupted"}


class SQLiteRegistry:
    """SQLite-based append-only registry with ACID guarantees."""

    def __init__(self, base_dir: Path, read_only: bool = False,
                 auto_rebuild_kernel_db: bool = True):
        self.base_dir = Path(base_dir)
        self.results_dir = self.base_dir / "gfx90c_results"
        self.runs_dir = self.base_dir / "gfx90c_runs"
        self.read_only = read_only
        # Refresh gfx90c_results/analysis/kernel_db.json automatically when a
        # run reaches a terminal data-producing status, so any later mutation /
        # regression_matrix / resolve_cells read always sees the freshest
        # corpus. Tests pass False; `OTO_NO_AUTO_KERNEL_DB_REBUILD=1` disables
        # it for seq runners that manage their own timing.
        self.auto_rebuild_kernel_db = auto_rebuild_kernel_db
        self._ensure_dirs()
        self.db_path = self.results_dir / "registry.db"
        if read_only:
            # A reporting path must not touch the database file. `__init__` used
            # to run `_init_db` unconditionally, so every `ab_audit` run silently
            # applied the additive schema migration to the live floor registry --
            # a report changing the thing it reports on. Missing tables now
            # surface as the caller's own error, which is the honest behaviour for
            # a reader.
            self._require_db()
        else:
            self._init_db()

    def _require_db(self) -> None:
        """Fail clearly if the database is absent, without creating anything."""
        if not self.db_path.exists():
            raise FileNotFoundError(
                f"registry not found: {self.db_path} "
                "(read_only=True will not create one)")
        try:
            with self._get_conn() as conn:
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.DatabaseError as e:
            raise sqlite3.DatabaseError(
                f"{self.db_path} is not a readable database: {e}") from e

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

            # Proposals ledger (Option H Phase 1). Append-only: rows are never
            # deleted and never rewritten, and `outcome` only advances
            # pending -> terminal. A monotonic status column is not a mutation
            # of history (knowledge_base.md §10), which is why the write-back is
            # an UPDATE guarded on outcome='pending' rather than a new row.
            #
            # Created here, alongside the other tables, so a fresh registry has
            # the ledger from birth. Existing databases pick it up on the next
            # SQLiteRegistry(...) construction: this is additive and never
            # rewrites an existing table or row.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposals (
                    fp          TEXT PRIMARY KEY,
                    family      TEXT,
                    shape       TEXT,
                    parent_fp   TEXT,
                    origin      TEXT NOT NULL DEFAULT 'novel',
                    iteration   INTEGER,
                    run_id      TEXT,
                    created_at  TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    outcome     TEXT NOT NULL DEFAULT 'pending',
                    build_class TEXT,
                    updated_at  TEXT
                )
            """)

            # Per-proposal observations (Option H Phase 1 integration). The
            # `proposals` row carries the *verdict*; this table carries the
            # *evidence* for it -- including WinnerFreq, which H.3.8 requires to
            # be recorded alongside the verdict but which is a property of the
            # measurement rather than of the verdict.
            #
            # Separate append-only table rather than more columns on `proposals`,
            # because a proposal's evidence is re-observable (a re-measurement
            # produces a new observation) while its verdict is decided once. Adding
            # columns to `proposals` would invite overwriting the evidence the
            # verdict was based on.
            #
            # Additive and created on construction, exactly like `proposals`: an
            # existing registry picks it up without rewriting a table or row.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proposal_observations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    fp         TEXT NOT NULL,
                    run_id     TEXT,
                    phase_dir  TEXT,
                    outcome    TEXT,
                    csv_count     INTEGER,
                    record_count  INTEGER,
                    row_count     INTEGER,
                    max_gflops    REAL,
                    median_gflops REAL,
                    winner_freq   REAL,
                    detail     JSON,
                    observed_at TEXT NOT NULL
                )
            """)

            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_run_id ON records(run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_records_type ON records(record_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_phases_fingerprint ON phases(fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_family_shape "
                         "ON proposals(family, shape)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_outcome "
                         "ON proposals(outcome)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_parent "
                         "ON proposals(parent_fp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_fp "
                         "ON proposal_observations(fp)")

            # Expression index on the fingerprint inside records.data JSON.
            # has_fp_passed() has always scanned every record because fp is buried
            # in a JSON blob; this makes that lookup an index seek without changing
            # its semantics. The index is built incrementally, so it is correct on
            # creation and maintained by SQLite from then on -- it deliberately
            # does NOT rewrite existing rows to 'backfill' anything.
            try:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_records_fp "
                    "ON records(json_extract(data, '$.fp'))"
                )
            except sqlite3.OperationalError:
                # No JSON1 (SQLite built without it): novelty still works, it just
                # scans. Never fatal -- the ledger must not be unbuildable because
                # an optional optimisation is unavailable.
                pass

            conn.commit()

    @contextmanager
    def _writing(self):
        """Guard every mutating entry point.

        A read-only registry that can still write is worse than one that raises:
        the caller believes it is reading the floor while it is editing it.
        """
        if self.read_only:
            raise PermissionError(
                f"registry opened read_only; refusing to write {self.db_path}")
        with self._get_conn() as conn:
            yield conn

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

    def create_run_dir(self, run_id: Optional[str] = None,
                        allow_existing: bool = False) -> Path:
        """
        Create a new run directory and checkpoint it.

        Never silently reuses a populated directory. The run directory is the
        only place a phase's CSVs, resolved YAML and stdout/stderr land, and the
        phase writer truncates those files, so reusing a populated run_id would
        destroy a previous run's measurements in place. A collision raises
        instead; callers that genuinely mean to continue an existing run must
        say so with allow_existing.

        Args:
            run_id: Optional custom run ID
            allow_existing: permit reuse of an existing directory

        Returns:
            Path to the new run directory
        """
        if run_id is None:
            run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        run_path = self.runs_dir / run_id
        if run_path.exists() and not allow_existing:
            populated = any(run_path.iterdir())
            if populated:
                raise FileExistsError(
                    f"run directory {run_path} already exists and is not empty; "
                    f"refusing to overwrite its measurements. Choose a new "
                    f"run_id, or pass allow_existing=True to continue it "
                    f"deliberately.")
        run_path.mkdir(parents=True, exist_ok=True)

        # Checkpoint in database. Deliberate continuation of an existing run_id
        # refreshes the row rather than colliding on the UNIQUE constraint; an
        # accidental collision is already refused above.
        with self._writing() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, status, metadata, started_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    started_at = excluded.started_at
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
        with self._writing() as conn:
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
        if self._should_rebuild_kernel_db(status):
            self._rebuild_kernel_db_after_run(run_id, status)

    def _should_rebuild_kernel_db(self, status: str) -> bool:
        """True when a terminal status implies fresh corpus data and the
        auto-rebuild is enabled (constructor flag, env opt-out)."""
        if self.read_only or not self.auto_rebuild_kernel_db:
            return False
        if os.environ.get("OTO_NO_AUTO_KERNEL_DB_REBUILD") == "1":
            return False
        return status in _KERNEL_DB_REBUILD_STATUSES

    def _rebuild_kernel_db_after_run(self, run_id: str, status: str) -> None:
        """Refresh gfx90c_results/analysis/kernel_db.json from the run dirs.

        Best-effort: a cache refresh must never fail a run finalisation, so any
        exception is logged (stderr) and swallowed. Rebuild is ~seconds and is
        idempotent — later reads (mutations, regression_matrix, resolve_cells)
        then always see the freshest corpus, including resumed/interrupted
        partial data.
        """
        try:
            base = str(self.base_dir)
            if base not in sys.path:
                sys.path.insert(0, base)
            # Lazy import: harness.kernel_db imports gfx90c_common only, so
            # there is no cycle back into registry/port_tensile.
            from harness.kernel_db import load_kernel_db
            cache = str(self.results_dir / "analysis" / "kernel_db.json")
            db = load_kernel_db(cache, base_dir=base, rebuild=True, quiet=True)
            n_runs = sum(1 for v in db.values() if v)
            n_rows = sum(len(v) for v in db.values())
            sys.stderr.write(
                f"[kernel_db] auto-rebuilt after {run_id} ({status}): "
                f"{n_runs} runs, {n_rows} rows -> {cache}\n")
        except Exception as exc:  # never break run finalisation
            sys.stderr.write(
                f"[kernel_db] auto-rebuild after {run_id} FAILED "
                f"(cached kernel_db.json untouched): {exc}\n")

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

    # ------------------------------------------------------------------
    # Proposals ledger (Option H Phase 1)
    #
    # Append-only. There is deliberately no delete method, and resolve_proposal
    # refuses to rewrite a row that already has a terminal outcome. See
    # proposal.md §H.3.1 / §H.3.2 for why the ledger lives here and not in a
    # sidecar file.
    # ------------------------------------------------------------------

    def emit_proposal_with_phase(
        self,
        fp: str,
        family: Optional[str] = None,
        shape: Optional[str] = None,
        parent_fp: Optional[str] = None,
        origin: str = "novel",
        iteration: Optional[int] = None,
        run_id: Optional[str] = None,
        phase_id: Optional[str] = None,
        phase_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record a proposal *and* the phase that will run it, in one transaction.

        These were two independent calls, which is a real hazard rather than a
        stylistic one: a crash between them leaves a proposal in the ledger with
        no phase that ever ran it. The candidate then reads as `pending` forever
        and its `n` never grows, so the cell is routed to `replicate` on the next
        pass -- indistinguishable from "measured and unstable". One transaction
        means the row and the phase exist together or neither does.

        Returns True iff the proposal row was newly inserted. A duplicate fp still
        records the phase (the phase is what actually runs) but returns False, so
        novelty and phase registration stay independently observable.
        """
        if not fp:
            return False
        now = datetime.now().isoformat()
        with self._writing() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO proposals
                    (fp, family, shape, parent_fp, origin, iteration, run_id,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fp, family, shape, parent_fp, origin, iteration, run_id, now)
            )
            inserted = bool(cur.rowcount)

            if phase_id:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO phases
                        (phase_id, fingerprint, data, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (phase_id, fp,
                     json.dumps(phase_data or {}), now)
                )
            return inserted

    def append_observation(
        self,
        fp: str,
        outcome: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        phase_dir: Optional[str] = None,
    ) -> int:
        """Persist one proposal's measurement evidence, append-only.

        H.3.8 asks for WinnerFreq alongside the verdict. WinnerFreq cannot live
        on the `proposals` row without overwriting the evidence the verdict was
        derived from, so it lands here instead, one row per observation.
        """
        if not fp:
            return 0
        d = detail or {}
        with self._writing() as conn:
            cur = conn.execute(
                """
                INSERT INTO proposal_observations
                    (fp, run_id, phase_dir, outcome, csv_count, record_count,
                     row_count, max_gflops, median_gflops, winner_freq, detail,
                     observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fp, run_id, phase_dir, outcome, d.get("csv_count"),
                 d.get("record_count"), d.get("row_count"), d.get("max_gflops"),
                 d.get("median_gflops"), d.get("winner_freq"),
                 json.dumps(d), datetime.now().isoformat())
            )
            return cur.lastrowid or 0

    def observations_for(self, fp: str) -> List[Dict[str, Any]]:
        """Every observation recorded for one fp, oldest first."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM proposal_observations WHERE fp = ? ORDER BY id ASC",
                (fp,)
            ).fetchall()
        return [dict(r) for r in rows]

    def _outcome_stream(self) -> List[Tuple[str, str, str]]:
        """`(parent_fp, fp, outcome)` for decided proposals, oldest first.

        `consecutive` is a claim about sequence, so the ordering matters:
        two failures then a success is not three consecutive failures. Ordered by
        `updated_at` then `fp` to break ties deterministically.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT parent_fp, fp, outcome, updated_at
                  FROM proposals
                 WHERE parent_fp IS NOT NULL AND parent_fp != ''
                   AND outcome != 'pending'
                 ORDER BY updated_at ASC, fp ASC
                """
            ).fetchall()
        return [(r["parent_fp"], r["fp"], r["outcome"]) for r in rows]

    def record_proposal(
        self,
        fp: str,
        family: Optional[str] = None,
        shape: Optional[str] = None,
        parent_fp: Optional[str] = None,
        origin: str = "novel",
        iteration: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> bool:
        """Record one emitted candidate in the ledger.

        Returns True if the row was inserted, False if this fp was already
        present. Re-emitting a known fp is not an error: the caller asked
        whether it was novel first, and the answer is simply "no, and here's the
        evidence".
        """
        if not fp:
            return False
        now = datetime.now().isoformat()
        with self._writing() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO proposals
                    (fp, family, shape, parent_fp, origin, iteration, run_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (fp, family, shape, parent_fp, origin, iteration, run_id, now)
            )
            return bool(cur.rowcount)

    def resolve_proposal(
        self,
        fp: str,
        outcome: str,
        build_class: Optional[str] = None,
    ) -> bool:
        """Advance one proposal's outcome, at most once.

        The guard `outcome='pending'` is what makes the ledger append-only in
        spirit: the first terminal verdict is permanent, and any later attempt is
        a silent no-op rather than an overwrite. Returns True if this call is the
        one that resolved the row.

        Callers must not treat a False return as an error to retry -- it means the
        outcome was already decided, which is the intended behaviour.
        """
        if not fp or not outcome or outcome == "pending":
            return False
        now = datetime.now().isoformat()
        with self._writing() as conn:
            cur = conn.execute(
                """
                UPDATE proposals
                   SET outcome = ?, status = 'resolved', build_class = ?, updated_at = ?
                 WHERE fp = ? AND outcome = 'pending'
                """,
                (outcome, build_class, now, fp)
            )
            return bool(cur.rowcount)

    def get_proposal(self, fp: str) -> Optional[Dict[str, Any]]:
        """One ledger row as a dict, or None if this fp was never proposed."""
        if not fp:
            return None
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE fp = ?", (fp,)
            ).fetchone()
        return dict(row) if row else None

    def proposed_fps(self) -> set:
        """Every fp ever entered in the ledger.

        A set of strings, deliberately untyped in shape: callers must not assume
        these were ever measured, only that they were emitted.
        """
        with self._get_conn() as conn:
            rows = conn.execute("SELECT fp FROM proposals").fetchall()
        return {r["fp"] for r in rows if r["fp"]}

    def decided_fps(self) -> set:
        """Every fp the registry holds a record for, whatever that record says.

        Deliberately broader than `has_fp_passed`, and the two answer different
        questions:

          decided_fps    "have we seen this config at all?" -- includes a row
                         whose status is `started`, which is what an interrupted
                         or policy-skipped run leaves behind.
          has_fp_passed  "did this config pass?" -- the narrower historical
                         status set (PASS / completed / success).

        Novelty uses this one, because re-proposing something the registry has
        already run is the D2 rediscovery defect whether or not it passed. The
        asymmetry is intentional and is pinned by a test, so it cannot drift
        into accidental agreement.
        """
        with self._get_conn() as conn:
            try:
                rows = conn.execute(
                    "SELECT DISTINCT json_extract(data, '$.fp') AS fp FROM records "
                    "WHERE json_extract(data, '$.fp') IS NOT NULL"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = [{"fp": json.loads(r["data"]).get("fp")}
                        for r in conn.execute("SELECT data FROM records").fetchall()]
        return {r["fp"] for r in rows if r["fp"]}

    def is_novel(self, fp: str) -> bool:
        """True iff fp is absent from both the ledger and the decided set.

        Uses `decided_fps` (any record at all), not `has_fp_passed` (passed
        only): a config that was started or skipped has still been run, and
        re-proposing it is the D2 rediscovery defect. See `decided_fps`.
        """
        if not fp:
            return False
        return fp not in self.proposed_fps() and fp not in self.decided_fps()

    def pending_proposals(self) -> List[Dict[str, Any]]:
        """Emitted candidates still awaiting an outcome.

        Non-empty after any crash is itself the signal: these are the rows that
        never got a verdict, i.e. exactly the candidates the loop could not learn
        from.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM proposals WHERE outcome = 'pending' ORDER BY rowid ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def all_proposals(self) -> List[Dict[str, Any]]:
        """Every proposal row, oldest first.

        The ordered form `decided_fps()` and friends deliberately do not provide:
        coverage needs the family/shape/outcome columns, and it needs them
        attached to each row rather than inferred from a fingerprint set.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT fp, family, shape, parent_fp, origin, iteration,
                       run_id, status, outcome, build_class
                  FROM proposals
                 ORDER BY iteration ASC, fp ASC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def outcome_histogram(self) -> Dict[str, int]:
        """Outcome counts, read live.

        Never a transcribed constant: callers (reports, tests) must read the
        distribution from here so a corpus change cannot leave a stale number in
        the docs or in a fixture.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT outcome, COUNT(*) AS n FROM proposals GROUP BY outcome"
            ).fetchall()
        return {r["outcome"]: r["n"] for r in rows}

    def coverage_view(self) -> List[Dict[str, Any]]:
        """Per (family, shape): proposed count and outcome breakdown.

        Cells with no candidate are absent here rather than represented as
        zero-valued rows -- absence is the signal a sampler needs to know where
        to explore, so it must not be flattened into a fake observation.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(family, '?') AS family,
                       COALESCE(shape, '?')  AS shape,
                       COUNT(*)                             AS n_proposed,
                       COUNT(DISTINCT iteration)           AS iterations,
                       SUM(outcome = 'pending')            AS n_pending,
                       SUM(outcome = 'functional')         AS n_functional,
                       SUM(outcome = 'non_functional')     AS n_non_functional,
                       SUM(outcome = 'legal_rejected')     AS n_legal_rejected,
                       SUM(outcome = 'legal_slow')         AS n_legal_slow
                  FROM proposals
                 GROUP BY family, shape
                 ORDER BY family, shape
                """
            ).fetchall()
        return [dict(r) for r in rows]


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
