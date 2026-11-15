"""Agent-2: generate <codename>_tuning_context.md from agent-1 output + starter.

Owns: the tuning-context document template. Does NOT own web research (injected).
The doc is a scaffold: every fact it prints is either profile-derived (safe)
or marked UNVERIFIED for a human to fill in. It never invents tiles, widths,
or ceilings — it names the ISA rule and leaves the number to the device doc.

Public API: generate(profile, theoretical_limits_doc, starter_text="", research=None) -> str.
"""

from __future__ import annotations

from collections.abc import Callable

from oto.agents.context import directed_question
from oto.device.profile import DeviceProfile


def _knob_section() -> list[str]:
    return [
        "## 1. Knob surface (universal; device rules live in the tuning guide)",
        "",
        "| knob | meaning | device-independent rules |",
        "|---|---|---|",
        "| MacroTile | MT0 x MT1 x DepthU for the LDS tile | MT0 x MT1 x DepthU x BPE ≤ lds_per_cu_kb |",
        "| ThreadTile | TT0 x TT1 (output per thread) | MacroTile % ThreadTile == 0 (per axis) |",
        "| VectorWidth | FP vector width per ALU op | VW ≤ asm_path_max; bf16/half 1 or 2; SD=2 for FP64 |",
        "| GlobalSplitU / LocalSplitU / NLCA | LDS split and cache axes | device-dependent (Tensile 3616 for half Assembly) |",
        "| AssertFree0EM / AssertFree1EM | Alignment asserts (vector-load/store) | AssertFree0/1EM ≥ 1; half Assembly ≥ 2 |",
        "| GlobalLoadVectorWidthA/B | Global -> LDS vector width | >1 requires AssertFree0/1EM ≥ 2 |",
        "| LdsPadA / LdsPadB | Bank-conflict pad | >1 legality: Tensile classic; own depth |",
        "| StaggerU / StaggerUMapping / StaggerUStride | Intra-depth LDS swizzle | admin across the whole depth barrier |",
        "| StoreCInUnroll / UnrollMajorLDS | Compute epilog | classic path only |",
        "| WorkGroupMapping | row/col mapping | miso row/col heuristics |",
        "",
        "See `docs/gfx90c_tuning_guide.md` for the fully-worked GCN (gfx90c) example;",
        "its rules are gfx90c-specific and **do not transport to another ISA family**.",
        "",
    ]


def generate(profile: DeviceProfile, theoretical_limits_doc: str = "",
            starter_text: str = "", research: Callable[[str], str] | None = None) -> str:
    """Generate the tuning-context doc for a device. ``profile`` is the device to tune."""
    extra = ""
    if research is not None:
        try:
            extra = research(directed_question(
                profile,
                f"Tuning context for {profile.codename} (ISA {profile.isa}): "
                f"which families of the shipped Tensile matrix matter for this device, "
                f"the ISA decisions an autotuner has to make (vector width caps, load-width caps, "
                f"thread-tile divisibility, GlobalSplitU and AssertFree restrictions, the LDS pinning rules), "
                f"and how the FP64 1/16 throughput position on GCN shapes the family weights. "
                f"Deliver per-family: preferred macro-tile shapes, preferred vector width, "
                f"Papyrus VGPR pressure, and one line on why."))
        except Exception as exc:  # pragma: no cover
            extra = f"(research unavailable: {exc})"
    parts = [
        f"# {profile.codename} tuning context",
        "",
        "> Scaffold. Every fact above this line is profile-derived. Observations in the",
        "> research section are UNVERIFIED until checked against first-party sources.",
        "",
        "## 0. Profile",
        f"- codename: {profile.codename}",
        f"- isa: {profile.isa}",
        "- families (shapes):",
    ]
    for fam, shapes in sorted(profile.family_shapes.items()):
        parts.append(f"  - {fam}: {shapes}")
    parts += ["",
              f"- lds_per_cu_kb: {profile.lds_per_cu_kb}",
              f"- vgpr_per_cu: {profile.vgpr_per_cu}",
              f"- num_cus: {profile.num_cus}",
              f"- max_clock_mhz: {profile.max_clock_mhz}",
              f"- has_mfma: {profile.has_mfma}",
              f"- has_dp4a: {profile.has_dp4a}",
              ""]
    parts += _knob_section()
    parts += [
        "## 3. Per-family notes",
        "",
        "Each entry below is a research anchor. Fill after consulting ISA references.",
        "",
    ]
    for fam in sorted(profile.family_shapes):
        parts += [
            f"### {fam}",
            "- Pick from the shapes in the profile.",
            "- UNVERIFIED: preferred MacroTile shape and VectorWidth on this device.",
            "- UNVERIFIED: binding constraint (register pressure, LDS, wave-count).",
            "",
        ]
    if theoretical_limits_doc:
        parts += ["", "## Theoretical limits (from agent-1)", theoretical_limits_doc[:500]]
    if extra:
        parts += ["", "## Research (UNVERIFIED — transcribe to profiles/*.json only "
                  "after checking first-party sources)", extra]
    return "\n".join(parts) + "\n"
