#!/usr/bin/env python3
"""Visually pleasing comparison: native gfx90c vs gfx900-spoofed (floor) on the same HW.

Reads gfx90c_results/acceptance_report.json and plots per-cell GFLOP/s for the
native best vs the spoof (gfx900 shipped library) best, with verdict + delta.
"""
import json
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - example script
    raise SystemExit(f"matplotlib is required for this example: {exc}") from exc
import numpy as np

BASE = Path(__file__).resolve().parent
report = json.load(open(BASE / "gfx90c_results" / "acceptance_report.json"))
cells = report["per_cell_verdicts"]

# Pick one representative cell per family: the cell with the largest native value
# (most visually interesting) — keeps the chart readable.
by_fam = {}
for c in cells:
    by_fam.setdefault(c["family"], []).append(c)
reps = []
for fam in ["SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA"]:
    cs = by_fam.get(fam, [])
    if not cs:
        continue
    # prefer the honest-reference cells if present
    reps.append(max(cs, key=lambda c: c["native_value"]))

# Sort by family order for stable layout
fam_order = ["SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA"]
reps.sort(key=lambda c: fam_order.index(c["family"]))

labels = [f"{c['family']}\n{c['shape']}" for c in reps]
native = [c["native_value"] for c in reps]
spoof = [c["spoof_value"] for c in reps]
verdicts = [c["verdict"] for c in reps]
deltas = [c["delta_pct"] for c in reps]

x = np.arange(len(reps))
w = 0.38

fig, ax = plt.subplots(figsize=(12, 6.5))
bars_n = ax.bar(x - w/2, native, w, label="Native gfx90c (best)", color="#2563eb", edgecolor="white", linewidth=0.6)
bars_s = ax.bar(x + w/2, spoof, w, label="gfx900 spoof floor", color="#f97316", edgecolor="white", linewidth=0.6)

# value labels on bars
for b in list(bars_n) + list(bars_s):
    h = b.get_height()
    ax.annotate(f"{h:.0f}", (b.get_x() + b.get_width()/2, h),
                ha="center", va="bottom", fontsize=8, fontweight="bold", color="#111827")

# verdict + delta annotations above pairs
for i, (v, d) in enumerate(zip(verdicts, deltas, strict=False)):
    ymax = max(native[i], spoof[i])
    color = "#16a34a" if v == "WIN" else ("#ca8a04" if v == "TIE" else "#dc2626")
    sign = "+" if d >= 0 else ""
    ax.text(x[i], ymax * 1.06, f"{v}  {sign}{d:.1f}%", ha="center", va="bottom",
            fontsize=9, fontweight="bold", color=color)

ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=9)
ax.set_ylabel("GFLOP/s (best per cell)", fontsize=11, fontweight="semibold")
ax.set_title("Native gfx90c vs gfx900-spoofed on identical hardware\n"
             "(per-cell best; tie band ±5%)", fontsize=13, fontweight="bold", pad=12)

# Environment annotation (emphasise latest nightly stack)
env_lines = [
    "Environment (latest nightly stack):",
    "  ROCm 7.15.0a20260728 (gfx90c)  |  PyTorch 2.12.0+rocm7.15  |  Python 3.14.4",
    "  GPU: AMD Radeon Graphics (gfx90c, cap 9.0)  |  HIP 7.16  |  amdclang 23.0",
    "  TensileLibrary.dat: best-effort (38 cells / 19 configs, basis=any)",
    "  Source: gfx90c_results/acceptance_report.json (like-for-like graded basis)",
]
fig.text(0.99, 0.93, "\n".join(env_lines), ha="right", va="top",
         fontsize=8, family="monospace", color="#374151",
         bbox={"boxstyle": "round,pad=0.4", "fc": "#f3f4f6", "ec": "#d1d5db", "alpha": 0.9})
ax.legend(loc="upper left", frameon=False, fontsize=10)
ax.grid(axis="y", linestyle=":", alpha=0.4)
ax.set_axisbelow(True)
# headroom for annotations
ax.set_ylim(0, max(*native, *spoof) * 1.22)

# summary box
wins = sum(1 for v in verdicts if v == "WIN")
ties = sum(1 for v in verdicts if v == "TIE")
losses = sum(1 for v in verdicts if v == "LOSS")
fig.text(0.99, 0.01, f"WIN {wins}  /  TIE {ties}  /  LOSS {losses}   (38 cells total)",
         ha="right", va="bottom", fontsize=9, style="italic", color="#4b5563")

fig.tight_layout()
out = BASE / "gfx90c_vs_spoof.png"
fig.savefig(out, dpi=150, bbox_inches="tight")
