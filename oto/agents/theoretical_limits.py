"""Agent-1: generate <codename>_theoretical_limits.md from a profile + starter.

Owns: the document template and the ALU peaks / ceilings section, which is
DERIVED from the profile on every call (see oto.device.derive). Does NOT own:
web research (injected via `research` callable) or writing to disk (caller
decides).

Public API: generate(profile, starter_text, research=None) -> str.
"""

from __future__ import annotations

from collections.abc import Callable

from oto.device import derive
from oto.device.profile import DeviceProfile


def _peak_table(profile: DeviceProfile) -> str:
    """The lane-class peak table, with the derivation formula alongside."""
    lines = [
        "| lane class | formula | Peak GFLOPS | derived |",
        "|---|---|---|---|",
    ]
    for fam, val in sorted(derive.derive_lane_classes(profile).items()):
        ln = derive.lanes(profile)
        lines.append(f"| {fam} | lanes x 2 x f "
                     f"(lanes={ln}, f={profile.max_clock_mhz / 1000.0} GHz) "
                     f"| {val} | formula |")
    lines.append("")
    lines.append("| family | BLAS-8 GFLOPS (derived) | stored in the profile "
                 "| agree |")
    lines.append("|---|---|---|---|")
    derived = derive.derive_theoretical_peaks_blas8(profile)
    stored = dict(profile.theoretical_peaks_blas8)
    for fam in sorted(derived):
        d = derived[fam]
        s = stored.get(fam)
        lines.append(f"| {fam} | {d} | {s} | {'OK' if s == d else 'MISMATCH'} |")
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
        "> Derived from hardware facts on every run. Numbers below re-check "
        "equal ",
        "> ``oto.device.derive`` exactly; if `oto.device.derive` disagrees with ",
        "> `profiles/<codename>.json`, `oto.device.derive` is right — the "
        "profile ",
        "> has a mistake and the profile needs fixing, not the formula.",
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
        "## 1. ALU peaks (derived)",
        _peak_table(profile=profile,),
        "",
        "## 2. Realistic ceilings",
    ]
    for fam, val in sorted(profile.realistic_ceilings.items()):
        parts.append(f"- {fam}: {val}")
    if extra:
        parts += ["", "## Research (UNVERIFIED — transcribe to profiles/*.json only "
                  "after checking first-party sources)", extra]
    return "\n".join(parts) + "\n"
