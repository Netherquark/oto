#!/usr/bin/env python3
"""A/B record loading: the canonical (native, floor) inputs.

Owns: ``phase_records`` / ``arm_records`` / ``arm_record_sets`` (every caller's
inputs, computed once) and ``_registry_records`` (registry-only records for
merged and draft runs, with the comparison form marked unknown rather than
invented).
Does NOT own: the identity they carry (oto.metrics.ab_identity), the band
measured from them (oto.metrics.ab_band) or the audit (oto.metrics.ab_audit).
Public API: phase_records, arm_records, arm_record_sets, _registry_records,
phase_family, BASE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

from oto.metrics.ab_identity import (AbIdentityMixin, _driver,
                                        _pair_key, _resolved_config,
                                        norm_config)
from oto.metrics.analytics import extract_family_from_phase_id
from oto.device.peaks import cell_key, kernel_key
from oto.metrics.policy import aggregate_cell
from oto.tensile.shape_order import ordered_shapes

#: The project root, resolved from this module's location.
BASE = Path(__file__).resolve().parents[2]

def phase_family(phase_id: str) -> str:
    """Which Tensile generator produced a phase: ``auto``, ``deck`` or ``unknown``.

    The distinction that matters is Tensile's AutoTuner versus a deck-driven
    sweep. Everything named ``phase_auto_*`` is AutoTuner; every other phase is
    a deck sweep, whichever prefix the deck happened to use (``phase_ss_*`` for
    the floor's pooled phases, ``phase_<cell>_*`` for the live deck). Keying on
    the raw prefix instead would call those two the same generator by accident
    and the floor's deck sweeps an unknown one.

    Invocation form and generator are confounded: the single-shape population
    is overwhelmingly ``auto`` while the multi-shape population is entirely
    deck sweeps, and the two executed in disjoint halves of the same run, so
    thermal state is confounded on top of that.
    """
    pid = phase_id or ""
    if not pid:
        return "unknown"
    return "auto" if pid.startswith("phase_auto") else "deck"

def _phase_csv_records(driver, csv_file: Path, phase: Optional[Dict[str, Any]],
                       phase_id: str, force_arm: str,
                       declared: List[str], run_name: str) -> List[Dict[str, Any]]:
    """Records for one phase's benchmark CSV, keyed by (dtype, shape, fp, family).

    Typecode-first cell attribution (the §13.2 rule) via
    ``aggregate_by_cell_typecode`` -- the same resolver
    ``reporting._ab_records_from_csv`` uses. Keying WITHOUT the family dimension
    is what silently folded every HH_HPA / HS_HPA kernel into the plain HH cells
    and left the eight HPA contract cells with no arm at all: their kernel
    typecode reads 'HH', so only the explicit HPA family stamp keeps them apart.
    That must not depend on which code path built the records.
    """
    # The phase's family (HPA included), not its dtype.
    phase_fam = extract_family_from_phase_id(phase_id)
    cell_map = driver.analytics.aggregate_by_cell_typecode(
        driver.analytics.load_benchmark_csv(csv_file),
        phase_family=phase_fam,
    )
    if not cell_map:
        return []

    # The phase's own resolved YAML wins over phases.yaml: floor phases are
    # not in the deck at all, and a deck entry can drift from what Tensile
    # actually ran.
    resolved = _resolved_config(csv_file.parent)
    config = resolved or dict((phase or {}).get("config") or {})
    stamps_phase = phase or {"config": config, "family": ""}

    # Measured shapes are authoritative: a phase can emit fewer shapes than
    # it declared if Tensile rejected one.
    measured = ordered_shapes({shape for (_d, shape, _f, _fam) in cell_map})

    out: List[Dict[str, Any]] = []
    for (cell_dtype, shape, fp, family), seeds in cell_map.items():
        rec = {
            "DataType": cell_dtype,
            "ProblemType": shape,
            "fingerprint": fp,
            "family": family,
            "kernel_key": kernel_key(config),
            "norm_config": norm_config(config, fp),
            "config": config,
            "GFLOPS": aggregate_cell(seeds).median,
            "phase_id": phase_id,
            "phase_family": phase_family(phase_id),
            "arm": force_arm,
            "source_run": run_name,
            "shapes": measured,
            "shapes_per_phase": len(measured),
            "declared_shapes": declared,
            "n_seeds": len(seeds),
        }
        rec.update(driver._named_cell_stamps(
            {**stamps_phase, "shapes": measured, "family": family.lower()},
            arm=force_arm))
        out.append(rec)
    return out


def phase_records(driver, run_dir: Path, force_arm: str) -> List[Dict[str, Any]]:
    """Per-(cell, config) records for one run, via the canonical loader.

    One record per (dtype, shape, config fingerprint) per phase, carrying the
    phase's median and the invocation form it was measured under. Walks phases
    itself rather than calling ``_ab_records_from_csv`` because the form has to
    stay attached to the phase it came from.
    """
    out: List[Dict[str, Any]] = []
    if not run_dir.is_dir():
        return out
    manifest = {str(p.get("phase_id", "")): p
                for p in driver.load_phases_manifest()}
    for csv_file in sorted(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
        phase_id = csv_file.parent.parent.name
        phase = manifest.get(phase_id)
        declared = [str(s) for s in (phase or {}).get("shapes", []) or []]
        out.extend(_phase_csv_records(driver, csv_file, phase, phase_id,
                                      force_arm, declared, run_dir.name))
    return out


def arm_records(driver, runs: Iterable[str], arm: str,
                base: Path = BASE) -> List[Dict[str, Any]]:
    """Records for a set of runs, classified wholly as one arm."""
    recs: List[Dict[str, Any]] = []
    for run in runs:
        recs.extend(phase_records(driver, base / "gfx90c_runs" / run, arm))
    return recs

def arm_record_sets(base: Path = BASE) -> Tuple[List[Dict[str, Any]],
                                                List[Dict[str, Any]],
                                                List[str]]:
    """The canonical ``(native, floor, chain)`` inputs, for every caller.

    `native` is the whole native corpus (every `run_*` directory plus every
    registry `benchmark_result` row) and `floor` is the recalled gfx900 reference
    chain, matching how `report.py` scopes its own comparison.

    Factored out so the measured band has exactly one definition: a coverage
    report that recomputed its own inputs from a different subset would grade
    against a band the audit never used.
    """
    driver = _driver(base)
    native = arm_records(
        driver,
        [d.name for d in sorted((base / "gfx90c_runs").glob("run_*")) if d.is_dir()],
        "native", base)
    native += _registry_records(driver, base, want_arm="native")
    chain = [r for r in driver._reference_floor_runs(None)
             if (base / "gfx90c_runs" / r).is_dir()]
    floor = arm_records(driver, chain, "spoof", base)
    floor += _registry_records(driver, base, want_arm="spoof")
    return native, floor, chain

def _registry_records(driver, base: Path, want_arm: str) -> List[Dict[str, Any]]:
    """Registry-only records (draft/merged runs whose GFLOPS live in the DB).

    Mirrors `TensileDriver._native_records_all_runs`, but records the invocation
    form as unknown rather than guessing it: a registry row stores the shape, not
    the phase's shape list, so these cannot be matched or mismatched honestly.
    They are kept because they carry real measurements that no run directory has.
    """
    try:
        rows = driver.registry.read_records(record_type="benchmark_result")
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if str(r.get("arm") or "") != want_arm:
            continue
        gf = float(r.get("GFLOPS") or r.get("median_gflops") or 0.0)
        if gf <= 0:
            continue
        shape = str(r.get("shape", ""))
        rec = {
            "DataType": str(r.get("dtype", "")),
            "ProblemType": shape,
            "fingerprint": str(r.get("fp", "")),
            "GFLOPS": gf,
            "phase_id": str(r.get("phase_id", "")),
            "phase_family": phase_family(str(r.get("phase_id", ""))),
            "arm": want_arm,
            "source_run": str(r.get("run_id") or r.get("source_run") or ""),
            "shapes": [shape] if shape else [],
            "shapes_per_phase": 0,   # 0 == unknown, never asserted either way
            "declared_shapes": [],
            "n_seeds": 1,
            "cell_key": r.get("cell_key") or "",
            "kernel_key": r.get("kernel_key", ""),
            "norm_config": "",
            "config": {},
            "from_registry": True,
        }
        out.append(rec)
    return out
