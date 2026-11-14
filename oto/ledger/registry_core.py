#!/usr/bin/env python3
"""The ledger engine: connection, schema, transactions and run writes.

Owns: ``RegistryCore`` -- the SQLite connection, the schema, the transaction guard
that makes a read-only registry refuse to write, the run-row write path
(create_run_dir, update_run_status) and the kernel-DB rebuild a terminal
status triggers.

Does NOT own: the registry's read side (oto.ledger.queries), the Option-H proposal ledger
(oto.ledger.proposals), or the cell policy (oto.metrics.policy).

Code prohibitions the driver must not reintroduce (moved here from
adversarial_review.md §2):
  * No hardcoded retirement lists -- the retirement model is evidence-only
    (registry rows); no PHASE_RETIRE-style reserved set compiled into code, and
    spoof/peak are never a retire signal (gfx900 = floor).
  * No hwmon parent-glob -- read `hwmon[0-9]*` paths via pathlib, never
    `find -name 'hwmon*'`: the parent directory would match first, yielding
    all-NA rows while `gpu_busy_percent` still worked and masking the failure.
  * No `.hdr` sidecar -- the telemetry header is written inside telemetry.csv;
    the v1 sidecar was never consumed by any reader.
  * No `power1_average`-only -- the fallback order is `power1_input` then
    `power1_average`; Cezanne hwmon4 exposes `power1_input` only.

Public API: RegistryCore, fingerprint_config, _KERNEL_DB_REBUILD_STATUSES.
"""


import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from oto.device import loader as _loader
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import runs_dir as _runs_dir

# Run-terminal statuses that imply benchmark data may have landed and the
# kernel_db cache should be refreshed. `skipped` / `smoke` / `failed`
# (gfx900-ref with zero executions) produce no new corpus, so they do not
# trigger a rebuild.
_KERNEL_DB_REBUILD_STATUSES = {"completed", "interrupted"}

#: Table DDL, in creation order (tables before their indexes). Extracted so the
#: schema reads as data rather than as a 120-line method body.
_SCHEMA_DDL = (
    """
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        record_type TEXT NOT NULL,
        data JSON NOT NULL,
        timestamp TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS phases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phase_id TEXT UNIQUE NOT NULL,
        fingerprint TEXT NOT NULL,
        data JSON NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL,
        metadata JSON,
        started_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    # Proposals ledger (Option H Phase 1). Append-only: rows are never deleted
    # and never rewritten, and `outcome` only advances pending -> terminal. A
    # monotonic status column is not a mutation of history (knowledge_base.md
    # §10), which is why the write-back is an UPDATE guarded on
    # outcome='pending' rather than a new row. Created here, alongside the other
    # tables, so a fresh registry has the ledger from birth; existing databases
    # pick it up on the next SQLiteRegistry(...) construction, additively.
    """
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
    """,
    # Per-proposal observations (Option H Phase 1 integration). The `proposals`
    # row carries the *verdict*; this table carries the *evidence* for it --
    # including WinnerFreq, which H.3.8 requires be recorded alongside the verdict
    # but which is a property of the measurement rather than of the verdict.
    # Separate append-only table rather than more columns on `proposals`, because
    # a proposal's evidence is re-observable while its verdict is decided once.
    """
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
    """,
)

#: Plain indexes, created after every table exists.
_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_records_run_id ON records(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_records_type ON records(record_type)",
    "CREATE INDEX IF NOT EXISTS idx_phases_fingerprint ON phases(fingerprint)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_family_shape "
    "ON proposals(family, shape)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_outcome ON proposals(outcome)",
    "CREATE INDEX IF NOT EXISTS idx_proposals_parent ON proposals(parent_fp)",
    "CREATE INDEX IF NOT EXISTS idx_obs_fp ON proposal_observations(fp)",
)

#: Expression index on the fingerprint inside records.data JSON. has_fp_passed()
#: has always scanned every record because fp is buried in a JSON blob; this makes
#: that lookup an index seek without changing its semantics. Built incrementally,
#: so it is correct on creation and maintained from then on -- it deliberately
#: does NOT rewrite existing rows to 'backfill' anything. Optional: a SQLite
#: built without JSON1 raises OperationalError, which the caller swallows
#: (novelty still works, it just scans).
_EXPRESSION_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_records_fp "
    "ON records(json_extract(data, '$.fp'))",
)


class RegistryCore:
    """The append-only ledger engine: connection, schema, transactions, runs."""


# -- engine: connection, schema, transaction guarding -----------------------

    def __init__(self, base_dir: Path, read_only: bool = False,
                 auto_rebuild_kernel_db: bool = True):
        self.base_dir = Path(base_dir)
        self.results_dir = _results_dir(self.base_dir, _loader.current_profile().codename)
        self.runs_dir = _runs_dir(self.base_dir, _loader.current_profile().codename)
        self.read_only = read_only
        # Refresh <codename>_results/analysis/kernel_db.json automatically when a
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
    def _init_db(self):
        """Initialize database schema.

        Idempotent and additive: every statement is ``IF NOT EXISTS``, so this
        runs on every construction and only ever adds tables/indexes to a
        pre-existing database -- it never rewrites an existing table or row. The
        DDL itself lives in the module-level ``_*_DDL`` constants (schema as
        data); the rationale for each table is documented there.
        """
        with self._get_conn() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(ddl)
            for ddl in _INDEX_DDL:
                conn.execute(ddl)
            try:
                for ddl in _EXPRESSION_INDEX_DDL:
                    conn.execute(ddl)
            except sqlite3.OperationalError:
                # No JSON1 (SQLite built without it): novelty still works, it just
                # scans. Never fatal -- the ledger must not be unbuildable because
                # an optional optimisation is unavailable.
                pass

            conn.commit()
    def create_run_dir(self, run_id: str | None = None,
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
    def update_run_status(self, run_id: str, status: str, metadata: dict | None = None) -> None:
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
        """Refresh <codename>_results/analysis/kernel_db.json from the run dirs.

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
            # Lazy import: harness.kernel_db imports oto.device.vocabulary only, so
            # there is no cycle back into registry/runners.
            from oto.harness.kernel_db import load_kernel_db
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



def fingerprint_config(config: dict[str, Any]) -> str:
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
