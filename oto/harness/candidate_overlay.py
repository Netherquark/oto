#!/usr/bin/env python3
"""The candidate overlay: what is written, pruned and mirrored.

Owns: ``_write_overlay`` (merge rows into the seed overlay, mirror the prunable phase_ids), ``_prune_candidates_from_seed`` (strip ``phase_cand_*`` rows while keeping winners, accepted rows and ``probe_*`` rows -- with a timestamped archive copy so the action is reversible), ``_round_robin_prune`` and ``_summarise``.
Does NOT own: the rows being written (oto.harness.candidate_rows) or their generation (oto.harness.candidate_pool).
Public API: _write_overlay, _prune_candidates_from_seed, _round_robin_prune, _summarise, OVERLAY_PATH."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from oto.harness.candidate_pool import __yaml_load  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY_PATH = REPO_ROOT / "gfx90c_results" / "overlays" / "phases.seed.overlay.yaml"


def _overlay_path() -> Path:
    """The seed overlay path, resolved at call time.

    Read through the CLI module's binding so a caller that rebinds
    ``generate_candidates.OVERLAY_PATH`` is honoured rather than shadowed by
    this module's own copy. The tests use exactly that seam.
    """
    import oto.harness.generate_candidates as cli
    return cli.OVERLAY_PATH


def _write_overlay(rows: List[Dict[str, Any]], dry_run: bool) -> int:
    """Append in-grid candidate rows to the persistent seed overlay.

    Every generated row addresses a shipped-grid cell (the §6.1 parity rule,
    tests/test_library_parity.py: no contraction, no extension), so the whole
    pool is safe to merge. Rows already scheduled (by phase_id or fp) are
    skipped.
    """
    payload = __yaml_load(_overlay_path(), fallback={"phases": []})
    if not isinstance(payload, dict):
        payload = {"phases": []}
    existing_ids = {str(p.get("phase_id", "")) for p in payload.get("phases", [])}
    existing_fps = {str(p.get("fp", "")) for p in payload.get("phases", [])}
    added = [r for r in rows
             if r["phase_id"] not in existing_ids and r["fp"] not in existing_fps]
    if dry_run:
        return len(added)
    if not added:
        return 0
    payload.setdefault("phases", []).extend(added)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload["note"] = (payload.get("note", "") +
                       f"\nAppended {len(added)} generated candidates at "
                       f"{stamp} by oto.harness.generate_candidates")
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


def _prune_candidates_from_seed(dry_run: bool = False) -> Tuple[int, int]:
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


def _round_robin_prune(rows: List[Dict[str, Any]],
                       cap: Optional[int]) -> List[Dict[str, Any]]:
    """Keep a fair (family, cell) share when the pool overshoots a given cap.

    ``cap=None`` means no cap: the whole pool is kept unchanged. Otherwise
    round-robin across buckets so the biggest family (SS) cannot starve the HPA
    families at the cap; removes the least-valuable rows (narrow -> wide, per
    bucket) first.
    """
    if cap is None or len(rows) <= cap:
        return rows
    buckets: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for r in rows:
        fam = str(r["config"].get("FamilyLabel", "")).upper() or "?"
        side = int(r["shapes"][0].split("x")[0])
        buckets.setdefault((fam, side), []).append(r)
    for lst in buckets.values():
        lst.sort(key=lambda r: {"narrow": 1, "auto": 0, "wide": 2}.get(r["tier"], 3))
    kept: List[Dict[str, Any]] = []
    keys = list(buckets)
    while len(kept) < cap and buckets:
        for k in keys:
            if not buckets[k]:
                continue
            kept.append(buckets[k].pop(0))
            if len(kept) >= cap:
                break
    return kept


def _summarise(rows: List[Dict[str, Any]]) -> None:
    by_family: Dict[str, Dict[str, int]] = {}
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
