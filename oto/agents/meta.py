"""Meta-agent: orchestrates agent-1 -> agent-2 -> (workflow) -> potential_configs.

Owns: the orchestration order. Does NOT own the agents or the workflow.

Public API: run(profile, starter_text, research=None, run_workflow=None) -> dict.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from oto.agents.theoretical_limits import generate as gen_tl
from oto.agents.tuning_context import generate as gen_tc
from oto.device.profile import DeviceProfile


def run(profile: DeviceProfile, starter_text: str = "",
        research: Optional[Callable[[str], str]] = None,
        run_workflow: Optional[Callable[[], Any]] = None) -> dict:
    tl = gen_tl(profile, starter_text, research)
    tc = gen_tc(profile, tl, starter_text, research)
    wf_result = None
    if run_workflow is not None:
        wf_result = run_workflow()
    return {"theoretical_limits": tl, "tuning_context": tc, "workflow": wf_result}
