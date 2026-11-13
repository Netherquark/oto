"""Agent-1: generate <codename>_theoretical_limits.md from a profile + starter.

Owns: the document template and the derivation of ALU peaks / ceilings from the
profile. Does NOT own: web research (injected via `research` callable) or
writing to disk (caller decides).

Public API: generate(profile, starter_text, research=None) -> str.
"""

from __future__ import annotations

from collections.abc import Callable

from oto.device.profile import DeviceProfile


def _peak_table(profile: DeviceProfile) -> str:
    lines = ["| Family | Peak GFLOPS (BLAS-8) |", "|---|---|"]
    for fam, val in sorted(profile.peak_gflops.items()):
        lines.append(f"| {fam} | {val} |")
    return "\n".join(lines)


def generate(profile: DeviceProfile, starter_text: str = "",
            research: Callable[[str], str] | None = None) -> str:
    """Generate the theoretical-limits doc for ``profile``.

    ``research`` is an optional callable (API-key-backed) returning extra
    context; when None, only the profile-derived sections are emitted.
    """
    extra = ""
    if research is not None:
        try:
            extra = research(f"theoretical limits for {profile.codename}")
        except Exception as exc:  # pragma: no cover - defensive
            extra = f"(research unavailable: {exc})"
    parts = [
        f"# {profile.codename} theoretical limits",
        "",
        "## 0. Hardware",
        f"- codename: {profile.codename}",
        f"- isa: {profile.isa}",
        f"- num_cus: {profile.num_cus}",
        f"- max_clock_mhz: {profile.max_clock_mhz}",
        f"- lds_per_cu_kb: {profile.lds_per_cu_kb}",
        f"- vgpr_per_cu: {profile.vgpr_per_cu}",
        f"- has_mfma: {profile.has_mfma}",
        f"- has_dp4a: {profile.has_dp4a}",
        "",
        "## 1. ALU peaks",
        _peak_table(profile),
        "",
        "## 2. Realistic ceilings",
    ]
    for fam, val in sorted(profile.realistic_ceilings.items()):
        parts.append(f"- {fam}: {val}")
    if extra:
        parts += ["", "## Research (UNVERIFIED — transcribe to profiles/*.json only "
                  "after checking first-party sources)", extra]
    return "\n".join(parts) + "\n"
