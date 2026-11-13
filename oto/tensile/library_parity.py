"""The coverage-parity rule: what the produced TensileLibrary may address.

Owns: the single implementation of the rule -- the produced
``tensilelibrary.dat`` must address exactly the (family, shape) cells the shipped
gfx900 library addresses, no contraction and no extension.

Does NOT own: the CLI that grades an external deck (oto.checks.library_parity),
the driver's non-fatal ``--preflight`` check (oto.runners.driver), or the
install-time refusal (oto.tools.consolidate_install).

Public API: phase_family, phase_cells, phases_cells, load_pipeline_phases,
parity_report. (The CLI ``main`` lives in oto.checks.library_parity.)

The rule, canonically stated in ``knowledge_base.md`` §6.1:

  * **no contraction** -- every shipped cell must have at least one device phase;
  * **no extension** -- no phase may address a cell outside the shipped grid.

* :func:`phase_family` resolves a phase's family. The config ``FamilyLabel`` is
  canonical; the ``phase_id`` token fallback keeps pre-FamilyLabel rows and
  overlay probes resolvable.
* :func:`phase_cells` / :func:`phases_cells` give the (family, shape) cells a
  phase / a manifest addresses. Non-cube shapes (GEMV probes such as
  ``32x4096x1``) have no cell by design and are reported separately, never counted
  as cells.
* :func:`parity_report` is the missing / extra / non-cube report.
* :func:`load_pipeline_phases` merges deck plus overlays in the same order the
  driver does, so preflight and the ``oto check library-parity`` command
  measure the same set.

Enforcement points, all CPU-only: the ``python3 -m oto check library-parity`` command (exit 1 on
divergence), the ``--preflight`` check, and ``consolidate.py all --commit``, which
refuses to install a deck that breaks parity. Tests: ``tests/test_library_parity.py``.
"""


from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

import oto.device.peaks as _peaks
from oto.device.peaks import (
    FAMILY_SHAPES,
    cube_side,
    shipped_cell_set,
)
from oto.runners.paths import results_dir as _results_dir

#: Family-name normalisation for the `phase_id` fallback path.
_FAMILY_ALIASES = {
    "ss": "SS",
    "dd": "DD",
    "hh": "HH",
    "cc": "CC",
    "zz": "ZZ",
    "hh_hpa": "HH_HPA",
    "hs_hpa": "HS_HPA",
}


def _family_from_tokens(phase_id: str) -> str:
    """Token-scan fallback: longest known family token, case-insensitive.

    Not delegated to `analytics.extract_family_from_phase_id` because that
    resolver is token-case-sensitive ('SS' != 'ss'), so overlay probes named
    `probe_N1_SS_...` resolve to '' there. Both hooks converge on the same
    FAMILY_SHAPES keys; the config `FamilyLabel` (canonical) needs neither.
    """
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", str(phase_id)) if p]
    for fam, canonical in sorted(_FAMILY_ALIASES.items(), key=lambda kv: -len(kv[0])):
        tokens = fam.split("_")
        for i in range(len(parts) - len(tokens) + 1):
            if [p.lower() for p in parts[i:i + len(tokens)]] == tokens:
                return canonical
    return ""


def phase_family(phase: dict[str, Any]) -> str:
    """Resolve a phase's canonical family name ('' when unresolvable).

    ``config.FamilyLabel`` is the authoritative identity (stamped at emit time,
    so HH / HH_HPA / HS_HPA never collapse — see `oto.device.peaks.cell_key`).
    Fall back to a case-insensitive `phase_id` token scan for pre-FamilyLabel
    rows and overlay probes.
    """
    cfg = phase.get("config")
    if isinstance(cfg, dict):
        label = cfg.get("FamilyLabel")
        if label in FAMILY_SHAPES:
            return label
        up = str(label or "").upper()
        if up in FAMILY_SHAPES:
            return up
    return _family_from_tokens(str(phase.get("phase_id") or ""))


def phase_cells(phase: dict[str, Any]) -> set[tuple[str, str]]:
    """The (family, cube-shape) cells one phase addresses, as shipped-grid keys.

    Non-cube shapes are not cells and are dropped here (they surface in
    :func:`parity_report` under ``non_cube_shapes``). A phase whose family
    cannot be resolved contributes nothing and appears in ``unresolved``.
    """
    fam = phase_family(phase)
    out: set[tuple[str, str]] = set()
    for shape in phase.get("shapes") or ():
        side = cube_side(shape)
        if side is None:
            continue
        if fam:
            out.add((fam, f"{side}x{side}x{side}"))
    return out


def phases_cells(phases: Iterable[dict[str, Any]]) -> set[tuple[str, str]]:
    """Union of :func:`phase_cells` over a manifest."""
    out: set[tuple[str, str]] = set()
    for phase in phases:
        out |= phase_cells(phase)
    return out


def parity_report(phases: Sequence[dict[str, Any]],
                  grid: set[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Missing / extra cells of `phases` vs the shipped grid.

    Returns a dict with `parity_ok` (True only when missing and extra are both
    empty), `shipped_cells`, `deck_cells`, `missing`, `extra`,
    `non_cube_shapes`, and `unresolved` ph-id families.
    """
    grid = grid if grid is not None else shipped_cell_set()
    covered = phases_cells(phases)
    missing = sorted(grid - covered, key=lambda c: c[0] + c[1])
    extra = sorted(covered - grid, key=lambda c: c[0] + c[1])

    non_cube: set[str] = set()
    unresolved: set[str] = set()
    for phase in phases:
        fam = phase_family(phase)
        if not fam:
            unresolved.add(str(phase.get("phase_id") or "?"))
        for shape in phase.get("shapes") or ():
            try:
                a, b, cc = str(shape).split("x")
                if int(a) != int(b) or int(b) != int(cc):
                    non_cube.add(f"{phase.get('phase_id', '?')} ({shape})")
            except ValueError:
                non_cube.add(f"{phase.get('phase_id', '?')} ({shape})")
    return {
        "parity_ok": not missing and not extra,
        "shipped_cells": len(grid),
        "deck_cells": len(covered),
        "missing": missing,
        "extra": extra,
        "non_cube_shapes": sorted(non_cube),
        "unresolved_families": sorted(unresolved),
    }


def load_pipeline_phases(base_dir: str | None = None,
                         run_id: str | None = None,
                         include_seed: bool = True) -> list[dict[str, Any]]:
    """Deck + current overlays, merged in the manifest order the run uses.

    Mirrors `oto.runners.phases.load_phases_manifest`'s merge order (deck, then the
    live run's overlay when one is active, then the persistent seed overlay)
    so a preflight parity verdict covers the exact manifest a run would build.
    Reads only files, never the registry or a GPU. Pass `run_id` to also fold
    in that run's per-run overlay (phases.<run_id>.overlay.yaml).
    """

    from pathlib import Path

    from oto import yamlio as _yamlio

    base = Path(base_dir or Path(__file__).resolve().parents[2])
    deck: list[dict[str, Any]] = []
    deck_path = base / "phases.yaml"
    if deck_path.exists():
        deck = _yamlio.load_yaml(deck_path) or []

    merged: list[dict[str, Any]] = list(deck)

    if run_id:
        for ov_path in sorted((_results_dir(base, _peaks.CODENAME) / "overlays").glob(f"phases.{run_id}.overlay.yaml")):
            _merge(merged, _yamlio.load_yaml_text(_read(ov_path)), f"run_overlay:{run_id}")

    if include_seed:
        seed_path = _results_dir(base, _peaks.CODENAME) / "overlays" / "phases.seed.overlay.yaml"
        if seed_path.exists():
            doc = _yamlio.load_yaml(seed_path)
            _merge(merged, doc, "seed_overlay")
    return merged


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


def _merge(into: list[dict[str, Any]],
           doc: dict[str, Any] | None,
           src: str) -> None:
    if not isinstance(doc, dict):
        return
    entries = doc.get("phases")
    if isinstance(entries, dict):
        entries = list(entries.values())
    if not isinstance(entries, list):
        return
    seen = {p.get("phase_id") for p in into}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("phase_id") in seen:
            continue
        entry = dict(entry)
        entry["_origin"] = src
        into.append(entry)
        seen.add(entry.get("phase_id"))
