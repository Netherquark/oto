#!/usr/bin/env python3
"""Visually pleasing comparison: native gfx90c vs gfx900-spoofed (floor).

Owns: the figure itself -- reading the acceptance report, per-cell GFLOP/s for
the native best vs the spoof (gfx900 shipped library) best, with verdict +
delta, and the matplotlib output.
Does NOT own: the data it plots or the report design language.
Public API: main.

    oto chart [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from oto.device import peaks as _peaks
from oto.runners.paths import results_dir as _results_dir


def _base(args: argparse.Namespace) -> Path:
    return Path(args.base or _results_dir())


def make_report(base: Path) -> dict[str, Any]:
    path = _results_dir(base, _peaks.CODENAME) / "acceptance_report.json"
    return json.loads(path.read_text())


def _figure(reps: list[dict[str, Any]], labels: list[str],
           native: list[float], spoof: list[float],
           verdicts: list[str], deltas: list[float]) -> Any:
    """Render the native-vs-spoof figure (matplotlib is an optional dep)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 6.5))
    x = range(len(reps))
    w = 0.38
    bars_n = ax.bar([i - w / 2 for i in x], native, w, label="Native gfx90c (best)", color="#2563eb", edgecolor="white", linewidth=0.6)
    bars_s = ax.bar([i + w / 2 for i in x], spoof, w, label="gfx900 spoof floor", color="#f97316", edgecolor="white", linewidth=0.6)
    for b in list(bars_n) + list(bars_s):
        h = b.get_height()
        ax.annotate(f"{h:.0f}", (b.get_x() + b.get_width() / 2, h), ha="center", va="bottom", fontsize=8, fontweight="bold", color="#111827")
    for i, (v, d) in enumerate(zip(verdicts, deltas, strict=False)):
        ymax = max(native[i], spoof[i])
        color = "#16a34a" if v == "WIN" else ("#ca8a04" if v == "TIE" else "#dc2626")
        sign = "+" if d >= 0 else ""
        ax.text(i, ymax * 1.06, f"{v}  {sign}{d:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold", color=color)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("GFLOP/s (best per cell)", fontsize=11, fontweight="semibold")
    ax.set_title("Native gfx90c vs gfx900-spoofed on identical hardware\n(per-cell best; tie band ±5%)", fontsize=13, fontweight="bold", pad=12)
    ax.legend(loc="upper left", frameon=False, fontsize=10)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(max(native), max(spoof)) * 1.22)
    wins = sum(1 for v in verdicts if v == "WIN")
    ties = sum(1 for v in verdicts if v == "TIE")
    losses = sum(1 for v in verdicts if v == "LOSS")
    fig.text(0.99, 0.93, "Native gfx90c vs gfx900 spoof floor (per-cell best)", ha="right", va="top", fontsize=8, family="monospace")
    fig.text(0.99, 0.01, f"WIN {wins} / TIE {ties} / LOSS {losses}   (cells total)", ha="right", va="bottom", fontsize=9, style="italic", color="#4b5563")
    fig.tight_layout()
    return fig


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=None, help="project base dir")
    ap.add_argument("--out", default=None, help="output PNG path")
    args = ap.parse_args(argv)
    base = _base(args)
    report = make_report(base)
    cells = report.get("per_cell_verdicts") or []
    by_fam: dict[str, list[dict[str, Any]]] = {}
    for c in cells:
        by_fam.setdefault(str(c.get("family")), []).append(c)
    fam_order = ("SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA")
    reps: list[dict[str, Any]] = []
    for fam in fam_order:
        cs = by_fam.get(fam, [])
        if not cs:
            continue
        reps.append(max(cs, key=lambda c: c.get("native_value") or 0))
    labels = [f"{c.get('family')}\n{c.get('shape')}" for c in reps]
    native = [c.get("native_value") or 0 for c in reps]
    spoof = [c.get("spoof_value") or 0 for c in reps]
    verdicts = [c.get("verdict") or "?" for c in reps]
    deltas = [c.get("delta_pct") or 0 for c in reps]
    try:
        fig = _figure(reps, labels, native, spoof, verdicts, deltas)
    except Exception as exc:  # pragma: no cover - optional plotting dep
        print(f"matplotlib is required for the chart: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "gfx90c_vs_spoof.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
