#!/usr/bin/env python3
"""The Option-H proposal ledger: emitted candidates and their measured outcomes.

Owns: one row per emitted candidate and at most one outcome per row -- the
durable state that makes "novel" and "replicate" decidable. The only place a
proposal is written or advanced.

Does NOT own: the record log (`oto.ledger.registry_queries`), the engine that opens the db
(`oto.ledger.registry_core`), or the samplers that call it
(`oto.ledger.mutator` / `oto.tensile.synthesis`).

Public API: ProposalMixin.
"""


from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


class ProposalMixin:
    """The Option-H proposal ledger: emitted candidates and their measured outcomes, mixed into SQLiteRegistry."""


    # ------------------------------------------------------------------
    # Proposals ledger. Append-only: rows are never deleted
    #
    # Append-only. There is deliberately no delete method, and resolve_proposal
    # refuses to rewrite a row that already has a terminal outcome. See
    # proposal.md §H.3.1 / §H.3.2 for why the ledger lives here and not in a
    # sidecar file.
    # ------------------------------------------------------------------

    def emit_proposal_with_phase(
        self,
        fp: str,
        family: str | None = None,
        shape: str | None = None,
        parent_fp: str | None = None,
        origin: str = "novel",
        iteration: int | None = None,
        run_id: str | None = None,
        phase_id: str | None = None,
        phase_data: dict[str, Any] | None = None,
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
        outcome: str | None = None,
        detail: dict[str, Any] | None = None,
        run_id: str | None = None,
        phase_dir: str | None = None,
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
    def observations_for(self, fp: str) -> list[dict[str, Any]]:
        """Every observation recorded for one fp, oldest first."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM proposal_observations WHERE fp = ? ORDER BY id ASC",
                (fp,)
            ).fetchall()
        return [dict(r) for r in rows]
    def _outcome_stream(self) -> list[tuple[str, str, str]]:
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
        family: str | None = None,
        shape: str | None = None,
        parent_fp: str | None = None,
        origin: str = "novel",
        iteration: int | None = None,
        run_id: str | None = None,
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
        build_class: str | None = None,
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
    def get_proposal(self, fp: str) -> dict[str, Any] | None:
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
    def pending_proposals(self) -> list[dict[str, Any]]:
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
    def all_proposals(self) -> list[dict[str, Any]]:
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
    def outcome_histogram(self) -> dict[str, int]:
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
    def coverage_view(self) -> list[dict[str, Any]]:
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
