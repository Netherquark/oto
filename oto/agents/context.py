"""Shared agent context: the profile surface and the directed research prompt.

Owns: the profile-summary block both agents emit, and the targeted
``ask_with_context`` helper. Neither agent hard-codes a question string;
the shape of what each agent asks for is owned by the agent, this module
just packages it for the cheap case.

Directed prompts beat open-ended ones: when the profile is known, an agent
that asks "what is gfx902" gets a 300-word encyclopedia; an agent that asks
"AMD ISA reference section for gfx902: which CU count do the RAVEN SKUs ship?"
gets an answer a human can verify. The caller decides which form to use;
this package builds the framing block it shares.
"""

from __future__ import annotations

from oto.device.profile import DeviceProfile


def profile_summary_block(profile: DeviceProfile) -> str:
    """One-vocabulary dump of the profile, used as prompt framing."""
    return (
        f"codename: {profile.codename}\n"
        f"isa: {profile.isa}\n"
        f"num_cus: {profile.num_cus}\n"
        f"max_clock_mhz: {profile.max_clock_mhz}\n"
        f"wavefront: {profile.wavefront}\n"
        f"lds_per_cu_kb: {profile.lds_per_cu_kb}\n"
        f"vgpr_per_cu: {profile.vgpr_per_cu}\n"
        f"has_mfma: {profile.has_mfma}\n"
        f"has_dp4a: {profile.has_dp4a}\n"
    )


def directed_question(profile: DeviceProfile, topic: str) -> str:
    """Wrap a topic with the profile summary as prompt framing."""
    return (
        f"{profile_summary_block(profile)}\n"
        f"Task: {topic}\n"
        f"Ground rules: cite the AMD ISA reference or the ROCm release note "
        f"for every factual claim; if you cannot verify, write "
        f"UNVERIFIED and say so explicitly; do not invent CUs, clocks, peaks, "
        f"or shapes; you are collecting evidence for a human to check, not "
        f"writing marketing copy.\n"
    )
