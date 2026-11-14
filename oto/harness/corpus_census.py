#!/usr/bin/env python3
"""Corpus census: what the corpus has ever measured, per family and per cell.

Owns: reading ``<codename>_results/analysis/kernel_db.json`` back as a history --
the distinct values each structural axis has held and the best seed-median
GFLOP/s at each, the distinct geometries and their best, and every geometry
measured on one cell next to the floor's best.

Does NOT own: the database builder (``oto.harness.kernel_db``), the per-cell
winner resolution (``oto.harness.cell_resolver``), the native-vs-floor knob
diff (``oto.harness.cell_knob_diff``), the forward-knob legality domain
(``oto.tools.deck_review legality``), or the regression verdicts
(``oto.harness.regression_matrix``).

Public API: load_rows, group_rows, resolve_family, axis_census,
geometry_census, cell_history, main.

Why this exists: candidate generation starts by asking "has this cell, at this
geometry, on this axis value, already been measured -- and how did it score?"
That answer used to be re-derived with a throwaway script per run. This is the
one CPU-only read of it, and it writes nothing except ``--json``.

Every statistic is the seed **median** (``gflops_median``), the repo's standing
basis; ``gflops_best`` is only a fallback when a row carries no median. Rows are
grouped by ``family/typecode`` because that is the attribution ground truth:
the HH-HPA and HS-HPA kernels share family ``HH`` and differ only by typecode,
so ``--family HH_HPA`` and ``--cell HH_HPA:1024`` are resolved to that block
(``resolve_family``) rather than silently reading an empty HH cell.

CPU only, read-only, never benchmarks.

    python3 -m oto.harness.corpus_census                     # axes + geometries
    python3 -m oto.harness.corpus_census --family SS --top 20
    python3 -m oto.harness.corpus_census --knob DepthU --family HH
    python3 -m oto.harness.corpus_census --cell SS:1024
    python3 -m oto.harness.corpus_census --cell HH_HPA:1024
    python3 -m oto.harness.corpus_census --typecode HHS
    python3 -m oto.harness.corpus_census --json out.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from oto.device import loader as _loader
from oto.device.kernel_vocabulary import cell_key
from oto.harness.kernel_db import read_kernel_db
from oto.runners.result_paths import results_rel

DEFAULT_DB_REL = results_rel("analysis", "kernel_db.json")

#: The structural axes this census reports. The forward-knob domain
#: (WorkGroupMapping, LdsPad, StaggerU, ...) is deliberately absent: those are
#: not in ``kernel_db`` rows, and their coverage question is owned by
#: ``oto.tools.deck_review legality`` and ``oto.tools.run_census``.
AXES: tuple[str, ...] = (
    "MacroTile", "MacroTile area", "ThreadTile", "ThreadTile area",
    "DepthU", "VectorWidth", "GlobalSplitU", "WorkGroup",
)

#: The full-geometry identity used by ``geometry_census`` and ``cell_history``.
GEOMETRY_KEYS = ("MacroTile", "ThreadTile", "DepthU", "VectorWidth",
                 "GlobalSplitU", "WorkGroup")
#: The JSON/output field names for the same six knobs.
GEOMETRY_FIELDS = ("macro_tile", "thread_tile", "depth_u", "vector_width",
                   "global_split_u", "work_group")

#: Family spellings the deck uses that are not the ``kernel_db`` family field.
#: ``kernel_db`` collapses HH_HPA/HS_HPA into family ``HH`` (they differ only by
#: typecode), so a caller asking for the deck family must be resolved to
#: ``(family, typecode)``. Plain families and typecodes map through unchanged.
FAMILY_ALIASES = {
    "HH_HPA": ("HH", "HHS"),
    "HS_HPA": ("HH", "HSS"),
    "SB": ("SS", "SB"), "DB": ("DD", "DB"), "HB": ("HH", "HB"),
    "CB": ("CC", "CB"), "ZB": ("ZZ", "ZB"),
    "HHS": ("HH", "HHS"), "HSS": ("HH", "HSS"),
}


def _ints(value: Any) -> tuple[int, ...]:
    """The integers in a kernel_db tile field (``'[128, 128]'`` or ``'8'``)."""
    return tuple(int(x) for x in re.findall(r"-?\d+", str(value or "")))


def _raw(row: dict[str, Any], key: str) -> str | None:
    """A row's value for one axis, or None when it carries no usable value."""
    value = row.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "None", "0") else text


def _tile_area(row: dict[str, Any], key: str) -> int | None:
    """Product of a two-element tile field, or None."""
    parts = _ints(row.get(key))
    return parts[0] * parts[1] if len(parts) >= 2 else None


def _axis_value(row: dict[str, Any], axis: str) -> Any | None:
    """One row's value on a named axis from ``AXES``."""
    if axis == "MacroTile area":
        return _tile_area(row, "MacroTile")
    if axis == "ThreadTile area":
        return _tile_area(row, "ThreadTile")
    return _raw(row, axis)


def _gflops(row: dict[str, Any]) -> float:
    """The row's seed-median GFLOP/s, falling back to its best seed."""
    for key in ("gflops_median", "gflops_best"):
        try:
            value = float(row.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _group_label(row: dict[str, Any]) -> str:
    """``family/typecode`` -- the attribution-aware census group."""
    family = str(row.get("family") or "?").upper()
    typecode = str(row.get("typecode") or "?").upper()
    return f"{family}/{typecode}"


def _group_sort(label: str, profile=None) -> tuple[int, str]:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    family, _, typecode = label.partition("/")
    order = {f: i for i, f in enumerate(_loader.resolve_profile(profile,).family_shapes)}
    return (order.get(family, len(order),), typecode)


def load_rows(db_path: str | None = None, side: str = "native",
              base_dir: Path | None = None) \
        -> list[dict[str, Any]]:
    """Flatten ``kernel_db.json`` into rows tagged ``side`` (native / floor).

    ``side`` is ``native`` (default: every ``run_*`` key), ``floor`` (every
    reference-tier key) or ``all``. A row is a dict from the database plus
    ``side`` and ``run``.
    """
    fallback = Path(base_dir) if base_dir else _HERE
    path = Path(db_path) if db_path else (fallback / DEFAULT_DB_REL)
    if side not in ("native", "floor", "all"):
        raise ValueError(f"side must be native/floor/all, not {side!r}")
    database = read_kernel_db(str(path))
    rows: list[dict[str, Any]] = []
    for run_id, run_rows in database.items():
        run_side = "floor" if run_id.startswith(f"{_loader.spoof_prefix()}_ref") else "native"
        if side not in ("all", run_side):
            continue
        rows.extend({**row, "side": run_side, "run": run_id}
                    for row in run_rows)
    return rows


def group_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """``{family/typecode: rows}`` in canonical family order."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_group_label(row)].append(row)
    return {label: groups[label] for label in sorted(groups, key=_group_sort)}


def resolve_family(token: str | None) -> tuple[str | None, str | None]:
    """``(family, typecode)`` for a family name, typecode or deck alias.

    ``HH_HPA`` / ``HS_HPA`` are not ``kernel_db`` family values; they resolve to
    ``(HH, HHS)`` / ``(HH, HSS)``. Plain families resolve with no typecode, so
    ``HH`` still means every HH block.
    """
    if not token:
        return None, None
    key = token.upper().replace("-", "_")
    return FAMILY_ALIASES.get(key, (key, None))


def axis_census(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per (group, axis, value): how often, and the best median.

    ``best`` is the maximum seed-median GFLOP/s measured at that value, so an
    axis value the corpus has never scored cannot be read as a winner. Missing
    or zero-score axis values are skipped, not counted as a value.
    """
    out: list[dict[str, Any]] = []
    for label, group in group_rows(rows).items():
        family, _, typecode = label.partition("/")
        for axis in AXES:
            stats: dict[Any, dict[str, Any]] = {}
            for row in group:
                if _gflops(row) <= 0:
                    continue
                value = _axis_value(row, axis)
                if value is None:
                    continue
                stat = stats.setdefault(value, {"value": value, "n": 0,
                                                "best": 0.0})
                stat["n"] += 1
                stat["best"] = max(stat["best"], _gflops(row))
            out.extend(
                {"family": family, "typecode": typecode,
                 "axis": axis, **stat}
                for stat in stats.values())
    return out


def _geometry(row: dict[str, Any]) -> tuple[str | None, ...]:
    return tuple(_raw(row, key) for key in GEOMETRY_KEYS)


def _geometry_fields(row: dict[str, Any]) -> dict[str, str | None]:
    """A row's six geometry knobs under their output field names."""
    return dict(zip(GEOMETRY_FIELDS, _geometry(row), strict=False))


def geometry_census(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """One record per (group, full geometry): row count and best median.

    A "geometry" is the tuple in ``GEOMETRY_KEYS`` -- what the deck calls a
    tile, not a cell. Unscored rows and rows with no geometry at all are
    skipped.
    """
    out: list[dict[str, Any]] = []
    for label, group in group_rows(rows).items():
        family, _, typecode = label.partition("/")
        stats: dict[tuple[str | None, ...], dict[str, Any]] = {}
        for row in group:
            if _gflops(row) <= 0:
                continue
            geometry = _geometry(row)
            if all(part is None for part in geometry):
                continue
            if geometry not in stats:
                stats[geometry] = {"n": 0, "best": 0.0}
                stats[geometry].update(_geometry_fields(row))
            stats[geometry]["n"] += 1
            stats[geometry]["best"] = max(stats[geometry]["best"],
                                          _gflops(row))
        out.extend(
            {"family": family, "typecode": typecode, **stat}
            for stat in stats.values())
    return out


def _attempt(row: dict[str, Any]) -> dict[str, Any]:
    """The compact per-attempt record printed by ``cell_history``."""
    return {"gflops": _gflops(row), "n_seeds": row.get("n_seeds"),
            "phase": row.get("phase"), "run": row.get("run"),
            **_geometry_fields(row)}


def cell_history(rows: Sequence[dict[str, Any]], family: str, side: int,
                 typecode: str | None = None, top: int = 12) \
        -> dict[str, Any]:
    """Every geometry measured on ``family:side``, best median first.

    ``typecode`` restricts the history to one block (``HHS`` for HH_HPA,
    ``HSS`` for HS_HPA); it is how a caller separates families that share the
    ``kernel_db`` family field. Repeated measurement of one geometry is
    collapsed into that geometry's record (``n`` rows, ``gflops`` the best of
    them), because replication is evidence about noise, not a distinct
    candidate. ``top=0`` returns every geometry. Non-cube shapes have no cell
    and are excluded by ``oto.device.kernel_vocabulary.cell_key``. The floor reference is
    computed from rows tagged ``side='floor'``; it is absent when the caller
    loaded only native rows.
    """
    key = f"{family.upper()}:{int(side)}"
    wanted = typecode.upper() if typecode else None
    native, floor = [], []
    for row in rows:
        if cell_key(row.get("family"), row.get("shape")) != key:
            continue
        if wanted and str(row.get("typecode") or "").upper() != wanted:
            continue
        if _gflops(row) <= 0:
            continue
        (floor if row.get("side") == "floor" else native).append(row)
    stats: dict[tuple[str | None, ...], dict[str, Any]] = {}
    for row in native:
        geometry = _geometry(row)
        if geometry not in stats:
            stats[geometry] = {"gflops": 0.0, "n": 0, "n_seeds": None,
                               "phase": None, "run": None,
                               **_geometry_fields(row)}
        record = stats[geometry]
        record["n"] += 1
        if _gflops(row) > record["gflops"]:
            record.update(gflops=_gflops(row), n_seeds=row.get("n_seeds"),
                          phase=row.get("phase"), run=row.get("run"))
    ordered = sorted(stats.values(), key=lambda record: -record["gflops"])
    floor_rows = [_attempt(row) for row in floor]
    floor_rows.sort(key=lambda record: -record["gflops"])
    label = f"{family.upper()}/{wanted}:{int(side)}" if wanted else key
    return {"cell": key, "label": label, "n_attempts": len(native),
            "n_geometries": len(stats),
            "geometries": ordered if top <= 0 else ordered[:top],
            "floor_best": floor_rows[0] if floor_rows else None}


def _fmt(value: Any | None) -> str:
    return "-" if value is None else str(value)


def _geometry_text(record: dict[str, Any]) -> str:
    return (f"MT={_fmt(record.get('macro_tile'))} "
            f"TT={_fmt(record.get('thread_tile'))} "
            f"DU={_fmt(record.get('depth_u'))} "
            f"VW={_fmt(record.get('vector_width'))} "
            f"GSU={_fmt(record.get('global_split_u'))} "
            f"WG={_fmt(record.get('work_group'))}")


def _print_axes(records: Sequence[dict[str, Any]], top: int) -> None:
    """Print one line per (group, axis), values ranked by best median."""
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_group[f"{record['family']}/{record['typecode']}"].append(record)
    for label in sorted(by_group, key=_group_sort):
        print(f"\n### {label}")
        by_axis: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in by_group[label]:
            by_axis[record["axis"]].append(record)
        for axis in AXES:
            values = sorted(by_axis.get(axis, []),
                            key=lambda r: (-r["best"], -r["n"]))
            if not values:
                continue
            shown = values if top <= 0 else values[:top]
            cells = " | ".join(f"{_fmt(v['value'])} {v['best']:.1f} "
                               f"(n={v['n']})" for v in shown)
            print(f"  {axis:16s} {len(values):3d} values: {cells}")


def _print_geometries(records: Sequence[dict[str, Any]], top: int) -> None:
    """Print each group's geometries, best median first."""
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_group[f"{record['family']}/{record['typecode']}"].append(record)
    for label in sorted(by_group, key=_group_sort):
        values = sorted(by_group[label], key=lambda r: -r["best"])
        print(f"\n### {label}: {len(values)} distinct geometries")
        shown = values if top <= 0 else values[:top]
        for record in shown:
            print(f"  {record['best']:9.1f}  n={record['n']:5d}  "
                  f"{_geometry_text(record)}")


def _print_cell(history: dict[str, Any]) -> None:
    """Print one cell's geometry history and the floor reference."""
    print(f"### {history.get('label', history['cell'])}  "
          f"native rows={history['n_attempts']}  "
          f"geometries={history['n_geometries']}")
    floor = history.get("floor_best")
    if floor:
        print(f"  floor best {floor['gflops']:8.1f}  {_geometry_text(floor)}")
    for record in history["geometries"]:
        seeds = f"n={record['n_seeds']}" if record.get("n_seeds") else ""
        print(f"  {record['gflops']:9.1f}  rows={record['n']:4d} {seeds:7s}  "
              f"{_geometry_text(record)}")


def _payload(args: argparse.Namespace, rows: Sequence[dict[str, Any]],
             family: str | None, typecode: str | None,
             side: int | None = None) -> dict[str, Any]:
    """The ``--json`` document for the arguments in force."""
    payload: dict[str, Any] = {"meta": {"db": str(args.db),
                                        "family": family,
                                        "typecode": typecode}}
    if side is not None:
        payload["cell"] = cell_history(rows, family, side,
                                       typecode=typecode, top=args.top)
        return payload
    if args.knob:
        payload["axes"] = [record for record in axis_census(rows)
                           if record["axis"] == args.knob]
    else:
        payload["axes"] = axis_census(rows)
        payload["geometries"] = geometry_census(rows)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-dir", "--base", type=Path, default=None,
                    help="repo root override (default: this file's parent of package)")
    ap.add_argument("--db", default=None,
                    help="kernel_db.json to read")
    ap.add_argument("--family",
                    help="family, typecode or deck alias (SS, HHS, HH_HPA)")
    ap.add_argument("--typecode", help="only this typecode (SB, HHS, ...)")
    ap.add_argument("--cell",
                    help="one cell's history, FAMILY:SIDE (SS:1024, HH_HPA:1024)")
    ap.add_argument("--knob", choices=list(AXES), help="only this axis")
    ap.add_argument("--top", type=int, default=8,
                    help="rows/values per block; 0 = all (default 8)")
    ap.add_argument("--json", dest="json_path",
                    help="write the same data as JSON to this path")
    args = ap.parse_args(argv)

    side: int | None = None
    if args.cell:
        token, _, cell_side = args.cell.partition(":")
        family, typecode = resolve_family(token)
        if not family or not cell_side.isdigit():
            ap.error("--cell must be FAMILY:SIDE, e.g. SS:1024")
        side = int(cell_side)
        rows = load_rows(args.db, side="all", base_dir=args.base_dir)
    else:
        family, typecode = resolve_family(args.family)
        rows = load_rows(args.db, side="native", base_dir=args.base_dir)
        if family or typecode:
            rows = [r for r in rows
                    if (not family or str(r.get("family") or "").upper()
                        == family)
                    and (not typecode or str(r.get("typecode") or "").upper()
                         == typecode)]
    if args.typecode:
        typecode = args.typecode.upper()
        rows = [r for r in rows
                if str(r.get("typecode") or "").upper() == typecode]

    if side is not None:
        _print_cell(cell_history(rows, family, side, typecode=typecode,
                                 top=args.top))
    else:
        axes = [r for r in axis_census(rows)
                if not args.knob or r["axis"] == args.knob]
        _print_axes(axes, args.top)
        if not args.knob:
            _print_geometries(geometry_census(rows), args.top)

    if args.json_path:
        with open(args.json_path, "w") as handle:
            json.dump(_payload(args, rows, family, typecode, side), handle,
                      indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

def __getattr__(name: str, profile=None):
    """Resolve device-profile-derived names per attribute access (call time)."""
    if name == '_FAMILY_ORDER':
        return {f: i for i, f in enumerate(_loader.resolve_profile(profile,).family_shapes)}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
