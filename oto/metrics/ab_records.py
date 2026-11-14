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

import contextlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import kernel_key
from oto.metrics.ab_identity import _driver, _resolved_config, norm_config
from oto.metrics.benchmark_analytics import extract_family_from_phase_id
from oto.metrics.cell_policy import aggregate_cell
from oto.metrics.measurement_protocol import UNKNOWN, classify
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import runs_dir as _runs_dir
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

def _phase_cell_map(driver, csv_files: list[Path], phase_id: str
                    ) -> dict[tuple[str, str, str, str], Any]:
    """One phase's seed lists keyed (dtype, shape, fp, family), CSVs merged.

    Typecode-first cell attribution (the §13.2 rule) via
    ``aggregate_by_cell_typecode`` -- the same resolver
    ``reporting._ab_records_from_csv`` uses. Keying WITHOUT the family dimension
    is what silently folded every HH_HPA / HS_HPA kernel into the plain HH cells
    and left the eight HPA contract cells with no arm at all: their kernel
    typecode reads 'HH', so only the explicit HPA family stamp keeps them apart.
    That must not depend on which code path built the records. A phase that
    wrote more than one benchmark CSV still carries ONE invocation form, so its
    seeds merge across the CSVs before aggregation.
    """
    phase_fam = extract_family_from_phase_id(phase_id)
    cell_map: dict[tuple[str, str, str, str], Any] = {}
    for csv_file in csv_files:
        cm = driver.analytics.aggregate_by_cell_typecode(
            driver.analytics.load_benchmark_csv(csv_file),
            phase_family=phase_fam,
        )
        for key, seeds in (cm or {}).items():
            cell_map.setdefault(key, []).extend(seeds)
    return cell_map


def _phase_csv_records(driver, csv_files: list[Path],
                       phase: dict[str, Any] | None,
                       phase_id: str, force_arm: str,
                       declared: list[str], run_name: str) -> list[dict[str, Any]]:
    """Records for one phase's benchmark CSVs, keyed by (dtype, shape, fp, family).

    One record per (dtype, shape, config fingerprint), carrying the phase's
    median, its resolved config and the invocation form stamp (§R56.3) it was
    measured under.
    """
    cell_map = _phase_cell_map(driver, csv_files, phase_id)
    if not cell_map:
        return []

    # The phase's own resolved YAML wins over phases.yaml: floor phases are
    # not in the deck at all, and a deck entry can drift from what Tensile
    # actually ran.
    resolved = _resolved_config(csv_files[0].parent)
    config = resolved or dict((phase or {}).get("config") or {})
    stamps_phase = phase or {"config": config, "family": ""}

    # Measured shapes are authoritative: a phase can emit fewer shapes than
    # it declared if Tensile rejected one. The classifier runs once per phase;
    # every record it produced shares the stamp.
    measured = ordered_shapes({shape for (_d, shape, _f, _fam) in cell_map})
    protocol = classify(extract_family_from_phase_id(phase_id),
                        measured, declared)

    return [_one_csv_record(driver, cell_dtype, shape, fp, family, seeds,
                            config, stamps_phase, phase_id, force_arm,
                            run_name, measured, declared, protocol)
            for (cell_dtype, shape, fp, family), seeds in cell_map.items()]


def _one_csv_record(driver: Any, cell_dtype: str, shape: str, fp: str, family: str,
                    seeds: list[Any], config: dict[str, Any],
                    stamps_phase: dict[str, Any], phase_id: str,
                    force_arm: str, run_name: str, measured: list[str],
                    declared: list[str], protocol: str) -> dict[str, Any]:
    """One (cell, config) record out of an aggregated phase cell-map."""
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
        "protocol": protocol,
        "n_seeds": len(seeds),
    }
    if driver is not None and hasattr(driver, "_named_cell_stamps"):
        with contextlib.suppress(Exception):
            rec.update(driver._named_cell_stamps(
                {**stamps_phase, "shapes": measured, "family": family.lower()},
                arm=force_arm))
    return rec


def _phase_csv_files(run_dir: Path) -> Iterable[tuple[str, list[Path]]]:
    """(phase_id, csv files) grouped per phase directory (ISOform, one each)."""
    groups: dict[str, list[Path]] = {}
    for csv_file in sorted(run_dir.glob("phase_*/2_BenchmarkData/*.csv")):
        groups.setdefault(csv_file.parent.parent.name, []).append(csv_file)
    return sorted(groups.items())


def phase_records(driver, run_dir: Path, force_arm: str) -> list[dict[str, Any]]:
    """Per-(cell, config) records for one run, via the canonical loader.

    One record per (dtype, shape, config fingerprint) per phase, carrying the
    phase's median and the invocation form it was measured under. Walks phases
    itself rather than calling ``_ab_records_from_csv`` because the form has to
    stay attached to the phase it came from.
    """
    out: list[dict[str, Any]] = []
    if not run_dir.is_dir():
        return out
    manifest = {str(p.get("phase_id", "")): p
                for p in driver.load_phases_manifest()}
    for phase_id, csv_files in _phase_csv_files(run_dir):
        phase = manifest.get(phase_id)
        declared = [str(s) for s in (phase or {}).get("shapes", []) or []]
        out.extend(_phase_csv_records(driver, csv_files, phase, phase_id,
                                      force_arm, declared, run_dir.name))
    return out


def arm_records(driver, runs: Iterable[str], arm: str,
                base: Path = BASE, profile=None) -> list[dict[str, Any]]:
    """Records for a set of runs, classified wholly as one arm.

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    recs: list[dict[str, Any]] = []
    for run in runs:
        recs.extend(phase_records(driver, _runs_dir(base, _loader.resolve_profile(profile,).codename) / run, arm))
    return recs

#: The last computed record sets, keyed by the corpus stamp. The corpus walk
#: reads every run directory's benchmark CSVs plus the registry: ~76 s, and
#: five coverage tests each wanted it. The corpus does not change inside a
#: session, so the sets are memoised on a stamp that *does* change when it
#: does (a new run directory, or a registry write).
_RECORD_SETS_CACHE: dict[tuple[Any, ...], tuple[list[dict[str, Any]],
                                               list[dict[str, Any]],
                                               list[str]]] = {}


def _corpus_stamp(base: Path, profile=None) -> tuple[Any, ...]:
    """A cheap key that changes whenever the corpus changes.

    Returns:
        (base, run count, newest run mtime, registry size and mtime).
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    runs = [d for d in (_runs_dir(base, _loader.resolve_profile(profile,).codename)).glob("run_*") if d.is_dir()]
    newest = 0.0
    for run in runs:
        try:
            newest = max(newest, run.stat().st_mtime)
        except OSError:
            continue
    db = _results_dir(base, _loader.resolve_profile(profile,).codename) / "registry.db"
    try:
        stat = db.stat()
        db_stamp: tuple[Any, ...] = (stat.st_size, stat.st_mtime)
    except OSError:
        db_stamp = (0, 0.0)
    return (str(base), len(runs), newest, db_stamp)


def arm_record_sets(base: Path = BASE, profile=None) -> tuple[list[dict[str, Any]],
                                                list[dict[str, Any]],
                                                list[str]]:
    """The canonical ``(native, floor, chain)`` inputs, for every caller.

    `native` is the whole native corpus (every `run_*` directory plus every
    registry `benchmark_result` row) and `floor` is the recalled gfx900 reference
    chain, matching how `report.py` scopes its own comparison.

    Factored out so the measured band has exactly one definition: a coverage
    report that recomputed its own inputs from a different subset would grade
    against a band the audit never used.

    The result is memoised on the corpus stamp (see :func:`_corpus_stamp`):
    the walk costs ~76 s and every caller wants the same records. The returned
    lists are shared, so a caller must treat them as read-only.
    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    key = _corpus_stamp(base, profile=profile,)
    cached = _RECORD_SETS_CACHE.get(key,)
    if cached is not None:
        return cached
    driver = _driver(base)
    native = arm_records(
        driver,
        [d.name for d in sorted((_runs_dir(base, _loader.resolve_profile(profile,).codename)).glob("run_*")) if d.is_dir()],
        "native", base, profile=profile,)
    native += _registry_records(driver, base, want_arm="native")
    chain = [r for r in driver._reference_floor_runs(None,)
             if (_runs_dir(base, _loader.resolve_profile(profile,).codename) / r).is_dir()]
    floor = arm_records(driver, chain, "spoof", base, profile=profile,)
    floor += _registry_records(driver, base, want_arm="spoof")
    if len(_RECORD_SETS_CACHE) > 4:
        _RECORD_SETS_CACHE.clear()
    _RECORD_SETS_CACHE[key] = (native, floor, chain)
    return native, floor, chain

def _registry_records(driver, base: Path, want_arm: str) -> list[dict[str, Any]]:
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
    out: list[dict[str, Any]] = []
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
            "protocol": UNKNOWN,     # never asserted into a graded basis
            "n_seeds": 1,
            "cell_key": r.get("cell_key") or "",
            "kernel_key": r.get("kernel_key", ""),
            "norm_config": "",
            "config": {},
            "from_registry": True,
        }
        out.append(rec)
    return out
