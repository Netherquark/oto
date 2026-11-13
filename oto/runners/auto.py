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

from typing import Any

from oto.runners.auto_prompt import AutoPlan


class AutoMixin:
    """The one-command overnight loop, mixed into TensileDriver."""

    def run_auto(
        self,
        budget: int | None = None,
        mutation_budget: int | None = None,
        opt_in_identical_skip: bool = True,
        release_held: bool = False,
        release_drop: bool = False,
        skip_reference: bool = False,
        plan: AutoPlan | None = None,
    ) -> dict[str, Any]:
        """
        Run auto-convergence loop: preflight, A/B baseline, manifest phases, harvest/mutate loop.
        """
        budget, mutation_budget, plan, release_held, release_drop = self._resolve_auto_plan(
            budget, mutation_budget, plan, release_held, release_drop)
        self._auto_plan = plan
        self._reference_floor_authoritative = True
        self._reference_floor_status = "not attempted"


        if not self._run_preflight_check():
            return {"converged": False, "reason": "Preflight aborted", "iterations": 0}

        self._establish_reference_floor(skip_reference, plan, release_held, release_drop)

        iteration = 0
        while iteration < budget and not self._stop_requested and not self._finish_after_iteration:
            iteration_result = self._run_auto_iteration(iteration, budget, opt_in_identical_skip, mutation_budget)
            if iteration_result.get("should_break"):
                break
            if iteration_result.get("return"):
                return iteration_result["return"]
            iteration += 1

        self.generate_acceptance_report()
        return {
            "converged": False,
            "reason": "Budget exhausted",
            "iterations": iteration
        }

    def _resolve_auto_plan(
        self,
        budget: int | None,
        mutation_budget: int | None,
        plan: AutoPlan | None,
        release_held: bool,
        release_drop: bool,
    ) -> tuple[int, int, AutoPlan, bool, bool]:
        """Resolve the auto plan and budget parameters."""
        from oto.runners.auto_prompt import AutoPlan
        plan = plan or AutoPlan()
        if budget is None:
            budget = plan.iterations
        if mutation_budget is None:
            mutation_budget = plan.mutations
        if release_held:
            plan.rerun_underspecified = True
        if release_drop:
            plan.rerun_unreproducible = True
        release_held = plan.rerun_underspecified
        release_drop = plan.rerun_unreproducible
        return budget, mutation_budget, plan, release_held, release_drop

    def _run_preflight_check(self) -> bool:
        """Run preflight and return True if should continue."""
        preflight_ok = self.run_preflight()
        if not preflight_ok:
            pass
        return not (self._stop_requested or self._finish_after_iteration)

    def _establish_reference_floor(
        self,
        skip_reference: bool,
        plan: AutoPlan,
        release_held: bool,
        release_drop: bool,
    ) -> None:
        """Establish or resume the A/B reference floor."""
        if not skip_reference and not plan.reruns_any_reference:
            self._reference_floor_authoritative = False
            self._reference_floor_status = "re-measurement declined by user"
            self._reference_declined = True
        elif not skip_reference:
            ref = self._latest_reference_run(exclude=self.run_dir.name)
            if ref:
                self._resume_existing_reference(ref, release_held, release_drop)
            elif getattr(self, "_reference_declined", False):
                pass
            else:
                self._establish_new_reference(release_held, release_drop)
        else:
            self._last_ab_reference_run_id = None

    def _resume_existing_reference(self, ref: str, release_held: bool, release_drop: bool) -> None:
        """Resume an existing reference floor."""
        remaining = self._reference_remaining()
        if remaining > 0:
            ref_res = self.run_gfx900_reference(resume=True, resume_base=ref,
                                                release_held=release_held,
                                                release_drop=release_drop)
            remaining = self._reference_remaining()
            if remaining > 0:
                self._reference_floor_authoritative = False
                self._reference_floor_status = str(ref_res.get("status"))
            else:
                self._reference_floor_status = str(ref_res.get("status"))
            if str(ref_res.get("status")) not in ("completed", "noop"):
                pass

    def _establish_new_reference(self, release_held: bool, release_drop: bool) -> None:
        """Establish a new reference floor."""
        ref_res = self.run_gfx900_reference(release_held=release_held,
                                            release_drop=release_drop)
        if ref_res.get("status") == "completed":
            ref_res.get("run_id")
        else:
            self._reference_floor_authoritative = False
            self._reference_floor_status = str(ref_res.get("status"))

    def _run_auto_iteration(
        self,
        iteration: int,
        budget: int,
        opt_in_identical_skip: bool,
        mutation_budget: int,
    ) -> dict[str, Any]:
        """Run a single auto iteration. Returns dict with 'should_break' and optional 'return'."""

        phases = self.load_phases_manifest()
        if not phases:
            self.scheduler.generate_family_phases("SS", ["Ailk_Bljk"], ["1024x1024x1024"])

        self.run_phases(opt_in_identical_skip=opt_in_identical_skip)

        if self._finish_after_iteration:
            return {"should_break": True}

        self._retire_stable_candidates()

        all_analytics = self._load_analytics_from_run()
        verdict = self.agent.converged(all_analytics, budget - iteration)
        if verdict.converged:
            self.generate_acceptance_report()
            return {"should_break": True, "return": {
                "converged": True,
                "reason": verdict.reason,
                "iterations": iteration + 1
            }}

        winners = self.agent.harvest(all_analytics)
        new_candidates = self.agent.mutate_and_feed(winners, mutation_budget)

        if not new_candidates:
            self.generate_acceptance_report()
            return {"should_break": True, "return": {
                "converged": False,
                "reason": "No valid mutations",
                "iterations": iteration + 1
            }}

        return {"should_break": False}
