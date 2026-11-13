#!/usr/bin/env python3
"""CPU-only Tensile build proof: does Tensile's own writer accept this phase?

Owns: for each phase, driving the same pipeline the real tuner uses minus the GPU
(``BenchmarkProcess`` -> ``generateForkedSolutions`` ->
``KernelWriterAssembly.getSourceFileString``) and reporting Tensile's own
verdict, because the occupancy gate is a calibrated model, not Tensile's truth.

Does NOT own: the gates it cross-checks (oto.tensile.gates), the phases it reads
(oto.tensile.candidate), or any GPU work -- none happens here.

Public API: main, probe_phase_config, write_phase_configs, select_phases.

``getSourceFileString`` is where Tensile decides a kernel is unschedulable: it
sets ``ko.overflowedResources`` and stamps the body with ``s_endpgm //
overflowed resources``. The error code returned is Tensile's verdict, not ours,
which is the whole point of the tool. Because the writer's register pools are
live at that point, the same pass reports Tensile's real per-thread VGPR / SGPR /
accVGPR counts -- the measurement that would retire the calibrated model.

No benchmark is ever run: ``BenchmarkProblems`` / ``BenchmarkStructs`` (the part
that launches GEMMs on the device) is never invoked. The ROCm tools touched are
the path-locating helpers real runs use (``hipconfig``,
``rocm_agent_enumerator``), which only print config.

    python3 -m oto check tensile-build             # all phases
    python3 -m oto check tensile-build --family ZZ # just ZZ
    python3 -m oto check tensile-build --phase-id <id> # one phase
    python3 -m oto check tensile-build --compare   # also check the model
    python3 -m oto check tensile-build --json > out.json
"""


from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from oto import yamlio
from oto.checks.tensile_build_probe import (
    REPO,
    _default_arch,
    _init_tensile,
    probe_phase_config,
)


# --------------------------------------------------------------------------
# Driver: one subprocess per phase (Tensile is heavy global state).
# --------------------------------------------------------------------------
def _worker(args: argparse.Namespace) -> int:
    if args.arch is None:
        args.arch = _default_arch()
    _init_tensile(arch=args.arch)
    result = probe_phase_config(Path(args.phase_yaml))
    Path(args.result_json).write_text(json.dumps(result))
    return 0 if result["ok"] else 1


def write_phase_configs(phases: list[dict[str, Any]], outdir: Path) -> dict[str, Any]:
    """Render every phase's real Tensile config, serially, in the main thread.

    Done up front and in one thread on purpose: TensileDriver.__init__ installs
    signal handlers (main-thread only, and it would rewrite the acceptance
    report if signalled), and patching that out is process-global state that
    would race if several threads did it at once. Config rendering is pure YAML
    and costs nothing, so keep it serial and let only the proof subprocesses fan
    out.
    """
    sys.path.insert(0, str(REPO))
    import signal

    from oto.runners.driver import TensileDriver

    real_signal = signal.signal
    signal.signal = lambda *a, **k: None
    try:
        driver = TensileDriver(REPO, create_run=False)
    finally:
        signal.signal = real_signal

    configs: dict[str, Any] = {}
    for phase in phases:
        pid = phase["phase_id"]
        cfg_path = outdir / f"{pid}.yaml"
        try:
            wrote, refusal = driver._write_phase_config(cfg_path, phase)
        except Exception as exc:
            configs[pid] = {"cfg": None, "refusal": f"config generation failed: {exc}"[:300]}
            continue
        configs[pid] = {
            "cfg": cfg_path if wrote else None,
            "refusal": None if wrote else f"refused pre-build: {refusal}",
        }
    return configs


def _rejection_reason(stdout: str) -> str:
    """Pull Tensile's own rejection explanation out of worker stdout.

    SolutionStructs.reject() writes "reject: <field>=<value> ..." to stdout when
    PrintSolutionRejectionReason is on, so the cause is already in the captured
    stream -- it just has to be picked out. Without this, a phase that yields no
    solutions reports only "0 valid solutions", which cannot be acted on.
    """
    lines = [ln.strip() for ln in (stdout or "").splitlines()]
    out: list[str] = []
    for i, ln in enumerate(lines):
        if ln.startswith("reject:"):
            detail = ln[len("reject:"):].strip()
            # The field list continues on following lines; keep a couple.
            for extra in lines[i + 1:i + 3]:
                if extra and not extra.startswith(("reject:", "[", "!!")):
                    detail += " " + extra
                    break
            if detail and detail not in out:
                out.append(detail)
    if not out:
        return ""
    return "; ".join(out[:3])[:400]


def run_phase(pid: str, cfg_path: Path, outdir: Path, arch: str, timeout: int) -> dict[str, Any]:
    """Build-prove one already-rendered phase config in a dedicated subprocess.

    Tensile is heavy global state (globalParameters, working paths, module-level
    caches), so each phase gets its own process rather than sharing one.
    """
    result_path = outdir / f"{pid}.result.json"
    if result_path.exists():
        result_path.unlink()
    work = outdir / pid
    work.mkdir(parents=True, exist_ok=True)

    # The repo-root shim was deleted in the 2026-11-13 CLI rework; invoke this
    # module directly (it has an __main__ guard) rather than a removed path.
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--_worker",
        "--phase-yaml", str(cfg_path),
        "--result-json", str(result_path),
        "--arch", arch,
    ]
    # The worker __main__-guard imports `oto`, so repo root must be on its path
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            cmd, cwd=str(work), capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"timeout after {timeout}s", "solutions": 0}

    if not result_path.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        return {
            "ok": False,
            "reason": "worker produced no result: " + " | ".join(tail)[:400],
            "solutions": 0,
        }
    result = json.loads(result_path.read_text())
    if not result.get("ok"):
        detail = _rejection_reason(proc.stdout)
        if detail:
            result["reason"] = f"Tensile rejected: {detail}"
            result["tensile_reject"] = detail
    return result


# --------------------------------------------------------------------------
def select_phases(args: argparse.Namespace) -> list[dict[str, Any]]:
    deck = yamlio.load_yaml(REPO / "phases.yaml") or []
    if args.phase_id:
        deck = [p for p in deck if p.get("phase_id") == args.phase_id]
        if not deck:
            raise SystemExit(f"phase_id {args.phase_id!r} not in phases.yaml")
    if args.family:
        want = args.family.upper()
        deck = [
            p for p in deck
            if str((p.get("config") or {}).get("FamilyLabel", "")).upper() == want
        ]
    return deck


def print_progress(row: dict[str, Any], i: int, total: int, outdir: Path,
                   passed: int, failed: int) -> None:
    regs = [r for r in row["results"] if r.get("vgprs") is not None]
    vg = max((r["vgprs"] for r in regs), default=None)
    ag = max((r.get("accvgprs") or 0 for r in regs), default=None)
    flag = "PASS" if row["ok"] else "FAIL"
    print(
        f"[{i:>3}/{total}] {flag} {row['phase_id']:<44} "
        f"MT={row['macro_tile']} TT={row['thread_tile']} "
        f"sols={row['solutions']}"
        + (f" vgpr<={vg}" if vg is not None else "")
        + (f" accvgpr<={ag}" if ag else "")
        + ("" if row["ok"] else f"  <- {row['reason']}"),
        flush=True,
    )
    if "model_ok" in row:
        agree = "MATCH" if row["model_ok"] == row["ok"] else "*** MISMATCH ***"
        print(f"          model: {'legal' if row['model_ok'] else 'illegal'} / Tensile: "
              f"{'legal' if row['ok'] else 'illegal'}  {agree}", flush=True)


def _probe_row(
    i_phase: tuple[int, dict[str, Any]],
    configs: dict[str, Any],
    outdir: Path,
    args: Any,
    model_fn: Any,
) -> dict[str, Any]:
    """Probe one phase and shape its report row (may run in a worker thread)."""
    _, phase = i_phase
    pid = phase["phase_id"]
    cfg = phase.get("config") or {}
    mt, tt = cfg.get("MacroTile"), cfg.get("ThreadTile")
    info = configs.get(pid) or {}
    if not info.get("cfg"):
        res = {"ok": False, "reason": info.get("refusal") or "no config", "solutions": 0}
    else:
        res = run_phase(pid, info["cfg"], outdir, args.arch, args.timeout)
    row = {
        "phase_id": pid,
        "label": phase.get("label"),
        "family": cfg.get("FamilyLabel"),
        "macro_tile": mt,
        "thread_tile": tt,
        "depth_u": cfg.get("DepthU"),
        "data_type": cfg.get("DataType"),
        "shapes": phase.get("shapes"),
        "ok": bool(res.get("ok")),
        "solutions": res.get("solutions", 0),
        "reason": res.get("reason"),
        "worst_err": res.get("worst_err"),
        "results": res.get("results", []),
    }
    if model_fn is not None:
        pred_ok, pred_why = model_fn(cfg) if mt else (False, "no MacroTile")
        row["model_ok"] = pred_ok
        row["model_reason"] = pred_why
    return row


def _build_arg_parser() -> argparse.ArgumentParser:
    """The CLI surface of the build proof."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", help="only this FamilyLabel (e.g. ZZ)")
    ap.add_argument("--phase-id")
    ap.add_argument("--arch", default=None,
                    help="Tensile arch (default: the device profile codename)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per phase")
    ap.add_argument("--jobs", type=int, default=1, help="parallel phase subprocesses")
    ap.add_argument("--json", help="write full report here")
    ap.add_argument("--compare", action="store_true",
                    help="cross-check oto's occupancy model against Tensile's verdict")
    ap.add_argument("--keep", help="keep build artifacts in this dir")
    # internal
    ap.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--phase-yaml", help=argparse.SUPPRESS)
    ap.add_argument("--result-json", help=argparse.SUPPRESS)
    return ap


def main() -> int:
    args = _build_arg_parser().parse_args()

    if args._worker:
        return _worker(args)

    if args.arch is None:
        args.arch = _default_arch()

    phases = select_phases(args)
    outdir = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="tensile_build_"))
    outdir.mkdir(parents=True, exist_ok=True)

    model_fn = None
    if args.compare:
        sys.path.insert(0, str(REPO))
        from oto.tensile.candidate import occupancy_feasible as model_fn

    rows: list[dict[str, Any]] = []
    passed = failed = 0
    print(f"Tensile CPU-only build proof: {len(phases)} phase(s), arch={args.arch}, "
          f"jobs={args.jobs}\n", flush=True)

    configs = write_phase_configs(phases, outdir)

    if args.jobs > 1:
        from concurrent.futures import ThreadPoolExecutor

        # Each phase runs in its own subprocess (Tensile global state), so
        # threads are just process supervision -- no shared mutable state.
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            done = list(pool.map(
                lambda ip: _probe_row(ip, configs, outdir, args, model_fn),
                enumerate(phases, 1)))
    else:
        done = []
        for i_phase in enumerate(phases, 1):
            row = _probe_row(i_phase, configs, outdir, args, model_fn)
            done.append(row)
            print_progress(row, i_phase[0], len(phases), outdir, passed, failed)

    for i, row in enumerate(done, 1):
        print_progress(row, i, len(phases), outdir, passed, failed)
        passed += 1 if row["ok"] else 0
        failed += 0 if row["ok"] else 1
        rows.append(row)

    print(f"\n{passed} passed, {failed} failed, {len(rows)} total")
    if not args.keep:
        shutil.rmtree(outdir, ignore_errors=True)
    else:
        print(f"artifacts: {outdir}")

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"report: {args.json}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
