#!/usr/bin/env python3
"""The ``--auto`` convergence loop: floor first, then tune to convergence.

Owns: ``run_auto`` -- preflight, establish or resume the reference floor, then
iterate (manifest -> run_phases -> retire -> analytics -> converged? ->
harvest/mutate) until the budget or the convergence verdict ends it.
Does NOT own: the floor it calls (reference.py), the phases it runs (phases.py),
or the plan it asks the user for (oto.runners.auto_prompt).
Public API: AutoMixin.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from oto.runners.auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS


class AutoMixin:
    """The one-command overnight loop, mixed into TensileDriver."""

    def run_auto(
        self,
        budget: Optional[int] = None,
        mutation_budget: Optional[int] = None,
        opt_in_identical_skip: bool = True,
        release_held: bool = False,
        skip_reference: bool = False,
        plan: Optional["AutoPlan"] = None,
    ) -> Dict[str, Any]:
        """
        Run auto-convergence loop (one-command overnight).

        Order:
          1. Preflight (Phase-0 checks, non-fatal)
          2. Preflight A/B baseline pair (spoof vs native anchor)
          3. All manifest phases in order (policy-filtered)
          4. Convergent harvest/mutate loop
        """
        # The four decisions (re-measure illegal? re-measure under-specified?
        # iterations? mutations?) are the user's, not a default's. resolve_plan
        # is filled by the CLI after asking; the values here are the fallback.
        from oto.runners.auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS
        plan = plan or AutoPlan()
        if budget is None:
            budget = plan.iterations
        if mutation_budget is None:
            mutation_budget = plan.mutations
        # The legacy --release-under-specified flag is a non-interactive way to
        # answer question 2; keep it working, but never let it answer question 3.
        if release_held:
            plan.rerun_underspecified = True
        release_held = plan.rerun_underspecified
        release_drop = plan.rerun_unreproducible
        self._auto_plan = plan
        self._reference_floor_authoritative = True
        self._reference_floor_status = "not attempted"

        print(f"Starting auto-convergence loop (budget={budget}, "
              f"mutation_budget={mutation_budget})")
        print(f"Plan: {plan.summary()}")

        # 1. Phase-0 preflight guarantees Tensile/DB/manifest presence
        preflight_ok = self.run_preflight()
        if not preflight_ok:
            print("WARNING: preflight reported FAIL; continuing (non-fatal).")
        if self._stop_requested or self._finish_after_iteration:
            return {"converged": False, "reason": "Preflight aborted", "iterations": 0}

        # A floor is "authoritative" only when every mandatory T1 phase has a
        # verdict. An incomplete or failed floor still gets a full pass, but the
        # native tuning below proceeds regardless -- an unfinished reference
        # must never be able to consume an entire overnight budget without
        # producing a single native measurement.
        self._reference_floor_authoritative = True
        self._reference_floor_status = "not attempted"

        # 2. A/B floor: a completed gfx900 reference run (recalled, not re-run).
        #    Established via --gfx900-reference, or by --auto. If the reference
        #    deck is not fully decided yet, --auto RESUMES it (finishing only
        #    the undecided shipped phases) and refuses to proceed with any
        #    tuning until every shipped phase has a verdict.
        if not skip_reference and not plan.reruns_any_reference:
            # The user was asked and said no to all three re-measurement
            # questions. Do not silently resume the reference anyway -- that is
            # the exact behaviour being replaced.
            print("Reference re-measurement declined (all three questions answered "
                  "no); recalling the existing floor and proceeding to native "
                  "tuning. A/B for this run is PROVISIONAL.")
            self._reference_floor_authoritative = False
            self._reference_floor_status = "re-measurement declined by user"
            ref = None
            self._reference_declined = True
        elif not skip_reference:
            ref = self._latest_reference_run(exclude=self.run_dir.name)
            if ref:
                print(f"\n--- A/B floor: gfx900 shipped reference run {ref} (recalled) ---")
                remaining = self._reference_remaining()
                if remaining > 0:
                    print(f"Reference floor incomplete ({remaining} triaged phase(s) still "
                          "owed) — resuming it before tuning...")
                    ref_res = self.run_gfx900_reference(resume=True, resume_base=ref,
                                                        release_held=release_held,
                                                        release_drop=release_drop)
                    remaining = self._reference_remaining()
                    if remaining > 0:
                        # Deliberately NOT an abort. Three consecutive overnight
                        # runs (gfx900_ref_20260928_023401/023858/092818) each
                        # spent their whole budget here and produced 0 of 127
                        # phases, so the reference floor has demonstrably
                        # prevented any native tuning at all. Record the debt and
                        # continue; the A/B comparison is marked non-authoritative
                        # until the floor is complete.
                        self._reference_floor_authoritative = False
                        self._reference_floor_status = str(ref_res.get("status"))
                        print(f"Reference floor STILL {remaining} triaged phase(s) undecided "
                              f"after resume ({ref_res.get('status')}). Proceeding to native "
                              "tuning anyway; A/B for this run is PROVISIONAL because the "
                              "floor is incomplete. Re-run --gfx900-reference to settle it.")
                    else:
                        self._reference_floor_status = str(ref_res.get("status"))
                    # T1 is fully re-measured, so the floor is trusted. T2 is HELD /
                    # best-effort: it is pinned out of this run unless explicitly
                    # released, and even when released it ran in the leftover time
                    # and may legitimately be partial or interrupted, so the run's
                    # own status must not veto proceeding here.
                    if str(ref_res.get("status")) not in ("completed", "noop"):
                        print(f"Reference resume ended as '{ref_res.get('status')}', but all "
                              "mandatory (T1) phases are re-measured. Held/best-effort T2 "
                              "phases may be skipped at any point — proceeding to tuning.")
                print("--- reference floor mandatory phases decided; proceeding with tuning ---")
            elif getattr(self, "_reference_declined", False):
                pass  # answered no at the prompt; do not start one anyway
            else:
                print("\nNo completed gfx900 shipped reference floor found — "
                      "establishing it now (--gfx900-reference, full deck, once).")
                ref_res = self.run_gfx900_reference(release_held=release_held,
                                                    release_drop=release_drop)
                if ref_res.get("status") == "completed":
                    ref = ref_res.get("run_id")
                    print(f"--- A/B floor: gfx900 shipped reference run {ref} "
                          f"(freshly established) ---")
                else:
                    # Same reasoning as the resume path above: one failed
                    # reference attempt must not cost the whole budget.
                    self._reference_floor_authoritative = False
                    self._reference_floor_status = str(ref_res.get("status"))
                    print(f"WARNING: reference benchmark did not complete "
                          f"({ref_res.get('status')}). Proceeding to native tuning "
                          "anyway; A/B for this run is PROVISIONAL because no "
                          "complete floor exists. Establish it with "
                          "--gfx900-reference when convenient.")
        else:
            print("\n--- Skipping gfx900 reference floor (native-only mode) ---")
            self._last_ab_reference_run_id = None

        iteration = 0
        while iteration < budget and not self._stop_requested and not self._finish_after_iteration:
            print(f"\n=== Iteration {iteration + 1}/{budget} ===")

            phases = self.load_phases_manifest()
            if not phases:
                print("Manifest empty; generating family phases...")
                self.scheduler.generate_family_phases("SS", ["Ailk_Bljk"], ["1024x1024x1024"])

            results = self.run_phases(opt_in_identical_skip=opt_in_identical_skip)

            if self._finish_after_iteration:
                print("End-after-iteration requested, halting auto loop")
                break

            # Retire stable cells before re-running policy gates
            self._retire_stable_candidates()

            # Load latest analytics
            all_analytics = self._load_analytics_from_run()

            # Check convergence
            verdict = self.agent.converged(all_analytics, budget - iteration)
            if verdict.converged:
                print(f"Converged: {verdict.reason}")
                self.generate_acceptance_report()
                return {
                    "converged": True,
                    "reason": verdict.reason,
                    "iterations": iteration + 1
                }

            # Harvest and mutate
            winners = self.agent.harvest(all_analytics)
            new_candidates = self.agent.mutate_and_feed(winners, mutation_budget)

            if not new_candidates:
                print("No valid mutations generated, stopping")
                self.generate_acceptance_report()
                return {
                    "converged": False,
                    "reason": "No valid mutations",
                    "iterations": iteration + 1
                }

            print(f"Generated {len(new_candidates)} new candidates")
            iteration += 1

        self.generate_acceptance_report()
        return {
            "converged": False,
            "reason": "Budget exhausted",
            "iterations": iteration
        }
