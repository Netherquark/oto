"""Device-doc agents: agent-1 (theoretical limits) + agent-2 (tuning context).

Owns: generating device-specific docs from a starter file + a DeviceProfile.
Does NOT own: the general docs (hand-maintained), the codebase, or the runner.
Public API: generate_theoretical_limits, generate_tuning_context.
"""
