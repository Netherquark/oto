"""Agent-2: generate <codename>_tuning_context.md from agent-1 output + starter.

Owns: the tuning-context document template. Does NOT own web research (injected).

Public API: generate(profile, theoretical_limits_doc, starter_text="", research=None) -> str.
"""

from __future__ import annotations

from collections.abc import Callable

from oto.device.profile import DeviceProfile


def generate(profile: DeviceProfile, theoretical_limits_doc: str = "",
            starter_text: str = "", research: Callable[[str], str] | None = None) -> str:
    """Generate the tuning-context doc for a device. ``profile`` is the device to tune."""
    extra = ""
    if research is not None:
        try:
            extra = research(f"tuning context for {profile.codename}")
        except Exception as exc:  # pragma: no cover
            extra = f"(research unavailable: {exc})"
    parts = [
        f"# {profile.codename} tuning context",
        "",
        "## 0. Profile",
        f"- codename: {profile.codename}",
        f"- families: {', '.join(sorted(profile.family_shapes))}",
        "",
        "## 1. Knob surface",
        "- MacroTile / ThreadTile / VectorWidth / DepthU / GlobalSplitU / WorkGroup",
        "",
        "## 2. Family shapes",
    ]
    for fam, shapes in sorted(profile.family_shapes.items()):
        parts.append(f"- {fam}: {shapes}")
    if theoretical_limits_doc:
        parts += ["", "## Theoretical limits (from agent-1)", theoretical_limits_doc[:500]]
    if extra:
        parts += ["", "## Research (UNVERIFIED — transcribe to profiles/*.json only "
                  "after checking first-party sources)", extra]
    return "\n".join(parts) + "\n"
