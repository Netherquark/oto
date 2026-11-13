#!/usr/bin/env python3
"""The candidate overlay: what is written, pruned and mirrored.

Owns: ``_write_overlay`` (merge rows into the seed overlay, mirror the prunable phase_ids), ``_prune_candidates_from_seed`` (strip ``phase_cand_*`` rows while keeping winners, accepted rows and ``probe_*`` rows -- with a timestamped archive copy so the action is reversible), ``_round_robin_prune`` and ``_summarise``.
Does NOT own: the rows being written (oto.harness.candidate_rows) or their generation (oto.harness.candidate_pool).
Public API: _write_overlay, _prune_candidates_from_seed, _round_robin_prune, _summarise, OVERLAY_PATH."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# `yaml` is imported lazily, inside the functions that use it, so that
# importing this module does not pull in the parser.

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import oto.device.peaks as _peaks
from oto.harness.candidate_pool import __yaml_load
from oto.runners.paths import results_dir as _results_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = _results_dir(REPO_ROOT, _peaks.CODENAME) / "overlays" / "phases.seed.overlay.yaml"



def _overlay_path() -> Path:
    """The seed overlay path, resolved at call time.

    Read through the CLI module's binding so a caller that rebinds
    ``generate_candidates.OVERLAY_PATH`` is honoured rather than shadowed by
    this module's own copy. The tests use exactly that seam.
    """
    import oto.harness.generate_candidates as cli
    return cli.OVERLAY_PATH


def _illegal_rows(phases: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """The rows the launch gate would refuse, as (phase_id, reason).

    The overlay is the deck the next run executes, so a row in it that the
    gate refuses is a phase that burns a launch slot to be told it is illegal.
    The gate is the same one the launch boundary uses, so this is exactly the
    set of rows that would come back as "skipped_illegal".
    """
    import contextlib
    import io

    from oto.tensile.config_writer import _launch_gate_refusal

    out: list[tuple[str, str]] = []
    for phase in phases:
        with contextlib.redirect_stdout(io.StringIO()):
            reason = _launch_gate_refusal(None, phase)
        if reason:
            out.append((str(phase.get("phase_id", "")), reason))
    return out


def _drop_illegal_stored(payload: dict[str, Any]
                         ) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Remove the stored rows the launch gate refuses; report what went.

    A row in the overlay that the gate refuses is a launch slot spent to be
    told the config is illegal, and a manifest that claims a config ran when
    it was refused. The gate's verdicts move as the rules are corrected, so
    the stored deck is re-checked against the *current* gate, not just the
    pool.
    """
    stored = list(payload.get("phases", []))
    illegal = _illegal_rows(stored)
    if illegal:
        refused = {i for i, _ in illegal}
        stored = [p for p in stored if str(p.get("phase_id", "")) not in refused]
        payload["phases"] = stored
        print(f"dropped {len(illegal)} stored row(s) the launch gate refuses: "
              f"{', '.join(i for i, _ in illegal[:6])}"
              f"{' ...' if len(illegal) > 6 else ''}")
    return stored, illegal


def _write_overlay(rows: list[dict[str, Any]], dry_run: bool) -> int:
    """Append in-grid candidate rows to the persistent seed overlay.

    Every generated row addresses a shipped-grid cell (the §6.1 parity rule,
    tests/test_library_parity.py: no contraction, no extension), so the whole
    pool is safe to merge. Rows already scheduled (by phase_id or fp) are
    skipped.

    Rows the launch gate refuses are dropped -- both the new ones and any
    already stored. A deck row that cannot launch is a wasted slot and a
    misleading manifest ("this config was run" when it was refused), and the
    gate's verdicts change as the rules are corrected (2026-10-21: the
    per-thread occupancy limit retired three SS frontier rows and the swizzle
    rule un-retired the no-swizzle arm), so the stored deck has to be
    re-checked against the current gate, not just against the pool.
    """
    payload = __yaml_load(_overlay_path(), fallback={"phases": []})
    if not isinstance(payload, dict):
        payload = {"phases": []}
    stored, stored_illegal = _drop_illegal_stored(payload)
    rows = [r for r in rows if not _illegal_rows([r])]
    existing_ids = {str(p.get("phase_id", "")) for p in stored}
    existing_fps = {str(p.get("fp", "")) for p in stored}
    added = [r for r in rows
             if r["phase_id"] not in existing_ids and r["fp"] not in existing_fps]
    if dry_run:
        return len(added)
    if not added and not stored_illegal:
        return 0
    if added:
        payload.setdefault("phases", []).extend(added)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload["note"] = (payload.get("note", "") +
                       f"\nAppended {len(added)} generated candidates at "
                       f"{stamp} by oto.harness.generate_candidates"
                       + (f"\nDropped {len(stored_illegal)} stored row(s) the "
                          f"launch gate refuses at {stamp}" if stored_illegal else ""))
    import yaml
    with open(_overlay_path(), "w") as f:
        yaml.safe_dump(payload, f, sort_keys=False, default_flow_style=False)
    # Timestamped standalone mirror (provenance / easy seed-file pruning).
    mirror = _overlay_path().parent / f"phases.candidates.{stamp}.overlay.yaml"
    mirror_payload = {
        "run_id": f"candidates-{stamp}",
        "created_at": stamp,
        "note": ("Candidate pool emitted by oto.harness.generate_candidates; "
                 "every row addresses a shipped-grid cell. Safe to load as a "
                 "run overlay, or archive after the run and strip these "
                 "phase_ids from phases.seed.overlay.yaml to keep future runs "
                 "light."),
        "phases": added,
    }
    with open(mirror, "w") as f:
        yaml.safe_dump(mirror_payload, f, sort_keys=False, default_flow_style=False)
    print(f"mirror written: {mirror.relative_to(_overlay_path().parent.parent.parent)}")
    return len(added)


def _prune_candidates_from_seed(dry_run: bool = False) -> tuple[int, int]:
    """Strip `phase_cand_*` rows from the persistent seed overlay (todo hygiene).

    The mirror note already instructs this after every candidate run: candidate
    pools grow without bound under `--auto` and their knob-encoded ids can drift
    from the `config` that is ground truth. Proven winners / accepted rows and
    `probe_*` rows are kept. State is preserved into a timestamped archive copy
    of the seed before stripping, so the action is reversible by diffing the two
    files. Returns (stripped, kept)."""
    payload = __yaml_load(_overlay_path(), fallback={"phases": []})
    if not isinstance(payload, dict):
        payload = {"phases": []}
    kept, stripped = [], []
    for p in payload.get("phases", []):
        if str(p.get("phase_id", "")).startswith("phase_cand_"):
            stripped.append(p)
        else:
            kept.append(p)
    if not stripped:
        return 0, len(kept)
    if dry_run:
        return len(stripped), len(kept)
    import yaml
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = _overlay_path().parent / f"phases.cand_archive.{stamp}.overlay.yaml"
    yaml.safe_dump({"note": f"phase_cand_* rows stripped from the seed by "
                            f"--prune-candidates at {stamp}",
                    "phases": stripped},
                   open(archive, "w"), sort_keys=False, default_flow_style=False)
    payload["phases"] = kept
    payload["note"] = (payload.get("note", "") +
                       f"\nStripped {len(stripped)} phase_cand_* rows "
                       f"(archived: {archive.name}) at {stamp}")
    yaml.safe_dump(payload, open(_overlay_path(), "w"),
                   sort_keys=False, default_flow_style=False)
    return len(stripped), len(kept)


def _round_robin_prune(rows: list[dict[str, Any]],
                       cap: int | None) -> list[dict[str, Any]]:
    """Keep a fair (family, cell) share when the pool overshoots a given cap.

    ``cap=None`` means no cap: the whole pool is kept unchanged. Otherwise
    round-robin across buckets so the biggest family (SS) cannot starve the HPA
    families at the cap; removes the least-valuable rows (narrow -> wide, per
    bucket) first.
    """
    if cap is None or len(rows) <= cap:
        return rows
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for r in rows:
        fam = str(r["config"].get("FamilyLabel", "")).upper() or "?"
        side = int(r["shapes"][0].split("x")[0])
        buckets.setdefault((fam, side), []).append(r)
    for lst in buckets.values():
        lst.sort(key=lambda r: {"narrow": 1, "auto": 0, "wide": 2}.get(r["tier"], 3))
    kept: list[dict[str, Any]] = []
    keys = list(buckets)
    while len(kept) < cap and buckets:
        for k in keys:
            if not buckets[k]:
                continue
            kept.append(buckets[k].pop(0))
            if len(kept) >= cap:
                break
    return kept


def _summarise(rows: list[dict[str, Any]]) -> None:
    by_family: dict[str, dict[str, int]] = {}
    for r in rows:
        fam = str(r["config"].get("FamilyLabel", "")).upper() or "?"
        by_family.setdefault(fam, {}).setdefault(r["tier"], 0)
        by_family[fam][r["tier"]] += 1
    total = [0]
    for fam in sorted(by_family):
        counts = by_family[fam]
        line = "  " + fam.ljust(8) + " " + "  ".join(
            f"{k}={counts[k]}" for k in sorted(counts))
        print(line)
        total[0] += sum(counts.values())
    print(f"  TOTAL  candidates={total[0]}")
