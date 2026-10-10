"""Cross-arm cell audit built on the canonical loader.

Answers one question per workload cell: which arm wins, by how much, and how
much of that margin is reproducible. It exists because the acceptance report
answers a different question -- it picks the best native candidate against the
best floor candidate without recording whether the two were measured the same
way.

Two things it adds over `report.py`:

* **Invocation form is carried on every record.** A phase that times one problem
  size and a phase that sweeps the family's sizes produce records that look
  identical downstream, so pool-mixing silently compares them. Every record here
  carries `shapes_per_phase` and the phase's `shapes`, making matched and
  mismatched comparisons separable by construction instead of by re-derivation.
* **The tie band is measured, not assumed.** `TIE_BAND_PCT` is the shipped
  default; `reproducible_band()` returns the band implied by cells where the
  *same configuration* was measured in both arms, which is the noise floor any
  verdict has to clear.

CSV parsing is not reimplemented here. `2_BenchmarkData` has three traps (the
throughput column is the last ``Cijk_*`` column, the first ``GFlops`` field is
zero, and ``SizeL`` carries K) and they stay encoded in
`AnalyticsEngine.load_benchmark_csv`, which this module calls. See
`knowledge_base.md` §8.

    python3 ab_audit.py                     # tables to stdout
    python3 ab_audit.py --json out.json     # machine-readable
    python3 ab_audit.py --arm-classes       # band per invocation form
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import yaml
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from oto.metrics.analytics import extract_family_from_phase_id
from oto.device.peaks import cell_key, kernel_key
from oto.metrics.policy import aggregate_cell

BASE = Path(__file__).resolve().parents[2]

# Shipped tie band. Reproducible-band measurement supersedes it where the corpus
# supports one; see reproducible_band().
TIE_BAND_PCT = 5.0

# Percentile span reported as the reproducible envelope.
BAND_LO, BAND_HI = 10, 90


def _driver(base: Path = BASE):
    """Driver for reading only.

    ``create_run=False`` is essential and not optional: TensileDriver's default
    constructor registers a run row and creates a run directory, so an audit tool
    that instantiates it normally writes to the corpus it is auditing. That
    happened -- 19 empty 'interrupted' runs accumulated in registry.db before
    this was caught.
    """
    from oto.runners.driver import TensileDriver
    return TensileDriver(base_dir=base, create_run=False)


def _resolved_config(phase_dir: Path) -> Dict[str, Any]:
    """Merge the config out of a phase's own resolved ``2_BenchmarkData/*.yaml``.

    Tensile writes that file as a list of documents -- a version stamp, a
    ProblemSizes list, then the solution config -- so the config is the entry
    carrying ``MacroTile``. Reading it here is what lets floor phases, which are
    absent from ``phases.yaml``, be paired against native phases on real config
    identity instead of on the solution name alone.
    """
    out: Dict[str, Any] = {}
    for yml in sorted(phase_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(yml.read_text(errors="ignore"))
        except Exception:
            continue
        entries = doc if isinstance(doc, list) else [doc]
        for entry in entries:
            if isinstance(entry, dict) and "MacroTile" in entry:
                out.update(entry)
    return out


_CP_RE = re.compile(r"Cijk_(.+?)_(?:SB|CB)_")


def _norm_macro_tile(cfg: Dict[str, Any]) -> str:
    """MacroTile as 'MxNxDU' whichever way Tensile wrote it.

    Native phases write ``MacroTile: 128x128x16`` (depth folded in); floor
    phases write ``MacroTile: [128, 64]`` with a separate ``DepthU``. Comparing
    those two spellings directly is how a config comes to look unmatched to
    itself.
    """
    mt = cfg.get("MacroTile")
    if isinstance(mt, (list, tuple)):
        parts = [str(x) for x in mt]
    elif mt:
        parts = str(mt).split("x")
    else:
        parts = [str(cfg.get("MT0", "")), str(cfg.get("MT1", ""))]
    depth = cfg.get("DepthU")
    if len(parts) >= 3 and parts[2]:
        depth = parts[2] if depth is None else depth
        parts = parts[:2]
    return f"{parts[0] if parts else ''}x{parts[1] if len(parts) > 1 else ''}x{depth if depth is not None else ''}"


def norm_config(cfg: Dict[str, Any], fingerprint: str = "") -> str:
    """Canonical config identity, comparable across the two arms.

    Built from resolved-Tensile knobs rather than the solution name because the
    solution name omits knobs that change the config (``WorkGroupMapping`` and
    ``GlobalSplitU`` variants emit the same ``Cijk_*`` name), and pairing on it
    would report two different kernels as one.
    """
    cfg = cfg or {}
    cp = cfg.get("ContractionPattern") or cfg.get("contraction_pattern") or ""
    if not cp:
        m = _CP_RE.search(fingerprint or "")
        cp = m.group(1) if m else ""
    tt = cfg.get("ThreadTile")
    tt = "x".join(str(x) for x in tt) if isinstance(tt, (list, tuple)) else \
        (str(tt) if tt else f"{cfg.get('TT0', '')}x{cfg.get('TT1', '')}")
    return "|".join((
        f"CP={cp}",
        f"MT={_norm_macro_tile(cfg)}",
        f"TT={tt}",
        f"VW={cfg.get('VectorWidth')}",
        f"GSU={cfg.get('GlobalSplitU')}",
        f"WGM={cfg.get('WorkGroupMapping')}",
    ))


def _pair_key(rec: Dict[str, Any]) -> Tuple[str, str, str]:
    """Identity used to pair a native record with a floor record."""
    return (rec["DataType"], rec["ProblemType"],
            rec.get("norm_config") or norm_config(rec.get("config") or {},
                                                  rec.get("fingerprint", "")))


def phase_family(phase_id: str) -> str:
    """Which Tensile generator produced a phase: ``auto``, ``deck`` or ``unknown``.

    The distinction that matters is Tensile's AutoTuner versus a deck-driven
    sweep. Everything named ``phase_auto_*`` is AutoTuner; every other phase is
    a deck sweep, whichever prefix the deck happened to use (``phase_ss_*`` for
    the floor's pooled phases, ``phase_<cell>_*`` for the live deck). Keying on
    the raw prefix instead would call those two the same generator by accident
    and the floor's deck sweeps an unknown one.

    On this corpus the single-shape population is ~94% ``auto`` and the
    multi-shape population is entirely deck sweeps, so invocation form and
    generator are confounded. The two also executed in disjoint halves of
    ``run_20260920_235815`` (``ss`` 00:00-06:44, ``auto`` 06:58-09:28), so
    thermal state is confounded on top of that.
    """
    pid = phase_id or ""
    if not pid:
        return "unknown"
    return "auto" if pid.startswith("phase_auto") else "deck"


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
        dtype = driver.analytics.extract_dtype_from_phase_id(phase_id)
        cell_map = driver.analytics.aggregate_by_cell(
            driver.analytics.load_benchmark_csv(csv_file),
            dtype_override=dtype,
        )
        if not cell_map:
            continue
        # The phase's own resolved YAML wins over phases.yaml: floor phases are
        # not in the deck at all, and a deck entry can drift from what Tensile
        # actually ran.
        resolved = _resolved_config(csv_file.parent)
        config = resolved or dict((phase or {}).get("config") or {})
        # Measured shapes are authoritative: a phase can emit fewer shapes than
        # it declared if Tensile rejected one.
        measured = sorted({shape for (_d, shape, _f) in cell_map})
        for (cell_dtype, shape, fp), seeds in cell_map.items():
            rec = {
                "DataType": cell_dtype,
                "ProblemType": shape,
                "fingerprint": fp,
                "kernel_key": kernel_key(config),
                "norm_config": norm_config(config, fp),
                "config": config,
                "GFLOPS": aggregate_cell(seeds).median,
                "phase_id": phase_id,
                "phase_family": phase_family(phase_id),
                "arm": force_arm,
                "source_run": run_dir.name,
                "shapes": measured,
                "shapes_per_phase": len(measured),
                "declared_shapes": declared,
                "n_seeds": len(seeds),
            }
            rec.update(driver._named_cell_stamps(
                phase or {"config": config, "shapes": measured, "family": ""},
                arm=force_arm))
            out.append(rec)
    return out


def arm_records(driver, runs: Iterable[str], arm: str,
                base: Path = BASE) -> List[Dict[str, Any]]:
    """Records for a set of runs, classified wholly as one arm."""
    recs: List[Dict[str, Any]] = []
    for run in runs:
        recs.extend(phase_records(driver, base / "gfx90c_runs" / run, arm))
    return recs


def _pct(values: List[float], p: float) -> float:
    return sorted(values)[min(len(values) - 1, int(p / 100.0 * len(values)))]


def reproducible_band(native: List[Dict[str, Any]],
                      floor: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Noise floor implied by configurations measured in *both* arms.

    Keyed on (dtype, shape, fingerprint), so a configuration that appears in the
    native arm and the floor arm at the same cell contributes the ratio of its
    two measurements. Nothing about kernel quality can move that ratio, so its
    spread is pure measurement disagreement plus any real difference between the
    two arms' protocols. Restricted to cells where both sides agree on
    invocation form, because otherwise the spread measures the protocol rather
    than the noise.
    """
    def index(recs):
        out = defaultdict(list)
        for r in recs:
            out[_pair_key(r)].append(r)
        return out

    nidx, fidx = index(native), index(floor)
    matched, mismatched = [], []
    for key, nrecs in nidx.items():
        frecs = fidx.get(key)
        if not frecs:
            continue
        nr = statistics.median([r["GFLOPS"] for r in nrecs])
        fr = statistics.median([r["GFLOPS"] for r in frecs])
        if fr <= 0:
            continue
        ratio = nr / fr
        same_form = (nrecs[0]["shapes_per_phase"] == frecs[0]["shapes_per_phase"])
        (matched if same_form else mismatched).append(ratio)

    def summarise(vals: List[float]) -> Dict[str, Any]:
        if not vals:
            return {"n": 0}
        return {
            "n": len(vals),
            "median_ratio": statistics.median(vals),
            "p10_ratio": _pct(vals, BAND_LO),
            "p90_ratio": _pct(vals, BAND_HI),
            "band_pct": max(abs(1 - _pct(vals, BAND_LO)),
                            abs(_pct(vals, BAND_HI) - 1)) * 100.0,
            "share_within_shipped_band": sum(
                1 for v in vals if abs(v - 1) <= TIE_BAND_PCT / 100.0)
            / len(vals),
        }

    return {"protocol_matched": summarise(matched),
            "protocol_mismatched": summarise(mismatched)}


def repeat_dispersion(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Spread of repeated measurements of one config under one form.

    Groups by (run, dtype, shape, kernel_key, form) -- everything a legitimate
    repeat is allowed to share -- and reports the distribution of within-group
    coefficient of variation. This is the real noise floor, and it is far above
    the shipped default: repeats of an identical kernel at an identical shape
    reach 36% CV for single-shape phases and 65% for multi-shape ones. A verdict
    whose margin sits inside that tail is not evidence.
    """
    groups: Dict[Tuple[Any, ...], List[float]] = defaultdict(list)
    for r in recs:
        v = r.get("GFLOPS") or 0.0
        if v <= 0:
            continue
        groups[(r.get("source_run"), r["DataType"], r["ProblemType"],
                r.get("kernel_key"), r.get("shapes_per_phase"))].append(v)
    cvs: List[float] = []
    worst: Dict[str, float] = {}
    for key, vals in groups.items():
        if len(vals) < 2:
            continue
        mean = statistics.mean(vals)
        if mean <= 0:
            continue
        cv = statistics.pstdev(vals) / mean * 100.0
        cvs.append(cv)
        form = "single" if key[4] == 1 else "multi"
        worst[form] = max(worst.get(form, 0.0), cv)
    if not cvs:
        return {"n": 0}
    return {
        "n": len(cvs),
        "median_cv_pct": statistics.median(cvs),
        "p90_cv_pct": _pct(cvs, BAND_HI),
        "max_cv_pct": max(cvs),
        "max_cv_single_pct": worst.get("single", 0.0),
        "max_cv_multi_pct": worst.get("multi", 0.0),
    }


def verdict(delta_pct: float, band_pct: float = TIE_BAND_PCT) -> str:
    if delta_pct > band_pct:
        return "WIN"
    if delta_pct < -band_pct:
        return "LOSS"
    return "TIE"


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


def cell_deltas(native: List[Dict[str, Any]], floor: List[Dict[str, Any]],
                agg: str = "best_median",
                base: Optional[Path] = None) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """Canonical per-cell native-vs-floor pairing, from already-loaded records.

    Split out from `arm_record_sets` so a caller that needs the band *and* the
    per-cell reference numbers scans the corpus once rather than twice -- the
    scan walks every run directory and every registry row, so paying it twice for
    one decision is not a rounding error.

    `agg='best_median'` is the report's default asymmetric basis, under which the
    floor side is the *median* of its per-kernel medians. That is the number
    "how the reference ran" means everywhere else in this codebase, which is why
    the slowness bar is derived from this call rather than from a second,
    hand-rolled per-cell statistic that could quietly disagree with the report.
    """
    return _driver(Path(base) if base else BASE).analytics.compute_native_vs_spoof_delta(
        native, floor, agg=agg)


def measured_band(native: List[Dict[str, Any]], floor: List[Dict[str, Any]],
                  band_pct: Optional[float] = None) -> Dict[str, Any]:
    """The acceptance band, and where each component of it came from.

    Two independent estimates of the same thing: cross-arm disagreement on
    identical configs, and raw repeat spread. The shipped 5% is only a floor.
    Never grade inside the repeat tail. An explicit `band_pct` overrides, and
    that is recorded rather than silently substituted.
    """
    cross = reproducible_band(native, floor)
    repeat = repeat_dispersion(native + floor)
    cross_pct = cross["protocol_matched"].get("band_pct") or 0.0
    repeat_pct = repeat.get("p90_cv_pct") or 0.0
    if band_pct is None:
        band = max(cross_pct, repeat_pct, TIE_BAND_PCT)
        source = ("max(cross-arm, repeat-tail, shipped-floor)"
                  if band > TIE_BAND_PCT else "shipped-floor")
    else:
        band = float(band_pct)
        source = "caller-supplied"
    return {"band_pct": band, "band_source": source, "cross_arm": cross,
            "repeat_dispersion": repeat}


def audit(base: Path = BASE, band_pct: Optional[float] = None) -> Dict[str, Any]:
    """Classify every cell in both arms.

    ``native`` is the whole native corpus and ``floor`` the recalled gfx900
    reference chain; both come from :func:`arm_record_sets`.
    """
    native, floor, chain = arm_record_sets(base)

    measured_b = measured_band(native, floor, band_pct)
    band = measured_b["band_pct"]
    cross, repeat = measured_b["cross_arm"], measured_b["repeat_dispersion"]
    measured = measured_b

    cells: Dict[str, Dict[str, Any]] = {}
    for recs, side in ((native, "native"), (floor, "spoof")):
        for r in recs:
            key = r.get("cell_key") or cell_key(
                extract_family_from_phase_id(r["phase_id"]), r["ProblemType"])
            if not key:
                continue
            slot = cells.setdefault(key, {"cell_key": key})
            best = slot.get(side)
            if best is None or r["GFLOPS"] > best["GFLOPS"]:
                slot[side] = r

    for key, slot in sorted(cells.items()):
        n, f = slot.get("native"), slot.get("spoof")
        slot["native_value"] = n["GFLOPS"] if n else None
        slot["spoof_value"] = f["GFLOPS"] if f else None
        if n and f and f["GFLOPS"] > 0:
            slot["delta_pct"] = (n["GFLOPS"] / f["GFLOPS"] - 1) * 100.0
            slot["verdict"] = verdict(slot["delta_pct"], band)
        else:
            slot["delta_pct"] = None
            slot["verdict"] = "UNGRADED"
        slot["protocol_matched"] = bool(
            n and f and n["shapes_per_phase"] == f["shapes_per_phase"])
        slot["native_family"] = n.get("phase_family") if n else None
        slot["spoof_family"] = f.get("phase_family") if f else None
        # Same form is necessary but not sufficient: auto-generated and
        # deck-generated phases are different benchmark procedures. This is a
        # veto, not a confirmation -- "other" is a catch-all for unknown
        # provenance, so an other/other match is reported as
        # provenance_known=False rather than treated as evidence.
        slot["provenance_matched"] = bool(
            slot["protocol_matched"]
            and n.get("phase_family") and f.get("phase_family")
            and n["phase_family"] == f["phase_family"])
        slot["provenance_known"] = bool(
            n and f and n.get("phase_family") not in (None, "", "unknown")
            and f.get("phase_family") not in (None, "", "unknown"))
        slot["native_run"] = n["source_run"] if n else None
        slot["spoof_run"] = f["source_run"] if f else None
        # Certainty is separate from the verdict, and a comparison across
        # different invocation forms produces a number that is not evidence: the
        # band measurement shows those ratios scatter over +/-180%, because form
        # is confounded with both the Tensile generator and the wall-clock
        # window the phase ran in. Within a matched provenance the margin still
        # has to clear the measured repeat tail before it means anything.
        if slot["verdict"] == "UNGRADED":
            slot["certainty"] = "missing"
        elif not slot["protocol_matched"]:
            slot["certainty"] = "form_mismatch"
        elif not slot["provenance_matched"]:
            slot["certainty"] = "generator_mismatch"
        elif abs(slot["delta_pct"] or 0.0) <= band:
            slot["certainty"] = "within_noise"
        else:
            slot["certainty"] = "certain"

    graded = [c for c in cells.values() if c["verdict"] != "UNGRADED"]
    tally: Dict[str, int] = defaultdict(int)
    certain: Dict[str, int] = defaultdict(int)
    for c in graded:
        tally[c["verdict"]] += 1
        if c["certainty"] == "certain":
            certain[c["verdict"]] += 1
    return {
        "floor_chain": chain,
        "band_pct": band,
        "band_source": measured_b["band_source"],
        "shipped_band_pct": TIE_BAND_PCT,
        "reproducible_band": measured,
        "repeat_dispersion": repeat,
        "proposal_coverage": _proposal_coverage(base, band),
        "tally": dict(tally),
        "tally_certain": dict(certain),
        "tally_certainty": dict(Counter(
            c["certainty"] for c in cells.values())),
        "ungraded": sum(1 for c in cells.values() if c["verdict"] == "UNGRADED"),
        "provenance_mismatched_cells": sum(
            1 for c in cells.values()
            if c["protocol_matched"] and not c["provenance_matched"]),
        "provenance_unknown_cells": sum(
            1 for c in cells.values()
            if c["protocol_matched"] and not c["provenance_known"]),
        "protocol_mismatched_cells": sum(
            1 for c in cells.values() if not c["protocol_matched"]),
        "n_cells": len(cells),
        "cells": [cells[k] for k in sorted(cells)],
    }


def _proposal_coverage(base: Path, band_pct: Optional[float] = None) -> Dict[str, Any]:
    """Option H Phase 3 coverage: `n`, spread, and the novel/replicate split.

    Read from the ledger rather than recomputed from the run directories, because
    the ledger is the only place a proposal's *origin* is recorded. A cell whose
    evidence is one seed is reported as `replicate`, which is what makes a
    replicate's value visible after the fact instead of only at selection time.

    `band_pct` is the band `audit` already computed and is passed in deliberately:
    recomputing it here would mean a second, possibly different, corpus sweep -- and
    calling `ab_audit.audit()` from inside `audit()` would recurse.

    Returns a zeroed summary rather than raising when the `proposals` table is
    absent (pre-Phase-1 registries), so this stays additive on an older DB.
    """
    try:
        from oto.metrics.coverage import coverage_from_registry
        from oto.ledger.registry import SQLiteRegistry
        db = base / "gfx90c_results" / "registry.db"
        if not db.exists():
            return {"available": False, "reason": "no registry.db"}
        reg = SQLiteRegistry(base, read_only=True)
        summary = coverage_from_registry(
            reg, band_pct=band_pct, base_dir=base)
        origins: Dict[str, int] = {}
        for row in reg.all_proposals():
            key = str(row.get("origin") or "?")
            origins[key] = origins.get(key, 0) + 1
        return {
            "available": True,
            "band_pct": summary["band_pct"],
            "tally": summary["tally"],
            "origins": origins,
            "n_cells": len(summary["cells"]),
            "cells": [
                {
                    "family": c["family"],
                    "shape": c["shape"],
                    "state": c["state"],
                    "n_distinct_fp": c["n_distinct_fp"],
                    "min_n": c["min_n"],
                    "best_median": c["best_median"],
                    "max_spread_ratio": c["max_spread_ratio"],
                    "parent_fp": c["parent_fp"],
                    "parent_lcb": c["parent_lcb"],
                }
                for c in summary["cells"]
            ],
        }
    except Exception as exc:  # additive: never fail the audit on coverage
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


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


def _fmt_table(rows: List[List[str]], headers: List[str]) -> str:
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [line, "-" * len(line)]
    for r in rows:
        out.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))
    return "\n".join(out)


def _print_proposal_coverage(cov: Dict[str, Any]) -> None:
    """Print `n`, spread and the novel/replicate split per mutated cell."""
    if not cov.get("available"):
        print(f"proposal coverage: unavailable ({cov.get('reason', 'unknown')})")
        return
    tally = cov.get("tally") or {}
    origins = cov.get("origins") or {}
    band = cov.get("band_pct")
    band_txt = f"{band:.1f}%" if band else "unmeasured"
    print(f"\nproposal coverage: cells={cov.get('n_cells', 0)}  "
          f"explore={tally.get('explore', 0)}  replicate={tally.get('replicate', 0)}  "
          f"retired={tally.get('retired', 0)}  "
          f"origin novel={origins.get('novel', 0)} replicate={origins.get('replicate', 0)}"
          f"  band={band_txt}")
    cells = cov.get("cells") or []
    if cells:
        print(_fmt_table(
            [[c["family"], c["shape"], c["state"], c["n_distinct_fp"],
              c["min_n"], f"{c['max_spread_ratio']:.3f}",
              (c["parent_fp"] or "-")[:12]]
             for c in cells],
            ["family", "shape", "state", "n_fp", "min_n", "spread", "parent"]))


def print_report(result: Dict[str, Any]) -> None:
    rb = result["reproducible_band"]
    print(f"floor chain : {result['floor_chain']}")
    print(f"tie band    : +/-{result['band_pct']:.1f}% "
          f"({result['band_source']}; shipped default "
          f"+/-{result['shipped_band_pct']:.1f}%)")
    for label, key in (("protocol-matched  ", "protocol_matched"),
                       ("protocol-mismatched", "protocol_mismatched")):
        s = rb[key]
        if not s.get("n"):
            print(f"{label}: no shared configurations")
            continue
        print(f"{label}: n={s['n']:4}  median={s['median_ratio']:.3f}  "
              f"p10={s['p10_ratio']:.3f}  p90={s['p90_ratio']:.3f}  "
              f"band=+/-{s['band_pct']:.1f}%  "
              f"within shipped band={s['share_within_shipped_band']*100:.1f}%")
    rd = result.get("repeat_dispersion") or {}
    if rd.get("n"):
        print(f"repeat spread: n={rd['n']:4}  median CV="
              f"{rd['median_cv_pct']:.1f}%  p90 CV={rd['p90_cv_pct']:.1f}%  "
              f"worst single={rd['max_cv_single_pct']:.1f}%  "
              f"worst multi={rd['max_cv_multi_pct']:.1f}%")
    _print_proposal_coverage(result.get("proposal_coverage") or {})
    print(f"\ncells={result['n_cells']}  {result['tally']}  "
          f"ungraded={result['ungraded']}  "
          f"protocol-mismatched={result['protocol_mismatched_cells']}  "
          f"generator-mismatched={result['provenance_mismatched_cells']}  "
          f"generator-unknown={result['provenance_unknown_cells']}")
    print(f"certainty: {result['tally_certainty']}")
    print(f"certain (same form + same generator + margin beyond noise): "
          f"{result['tally_certain']}\n")

    rows = []
    for c in result["cells"]:
        nv = c["native_value"]
        fv = c["spoof_value"]
        d = c["delta_pct"]
        rows.append([
            c["cell_key"],
            c["verdict"],
            c["certainty"],
            f"{nv:.2f}" if nv else "-",
            f"{fv:.2f}" if fv else "-",
            f"{d:+.2f}" if d is not None else "-",
            "yes" if c["protocol_matched"] else "NO",
            f"{c.get('native_family') or '-'}/{c.get('spoof_family') or '-'}",
            str(c["native_run"] or "-")[:22],
            str(c["spoof_run"] or "-")[:24],
        ])
    print(_fmt_table(rows, ["cell", "verdict", "certainty", "native", "spoof",
                            "delta%", "matched", "families", "native_run",
                            "spoof_run"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", type=Path, default=BASE)
    ap.add_argument("--json", type=Path, help="also write machine-readable output here")
    ap.add_argument("--arm-classes", action="store_true",
                    help="print the reproducible band per invocation form only")
    ap.add_argument("--band", type=float, default=None,
                    help=f"override the tie band (default: measured, else "
                         f"+/-{TIE_BAND_PCT})")
    args = ap.parse_args()

    result = audit(base=args.base_dir, band_pct=args.band)
    if args.arm_classes:
        print(json.dumps(result["reproducible_band"], indent=2))
    else:
        print_report(result)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, default=str))
        print(f"\njson -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())