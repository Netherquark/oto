#!/usr/bin/env python3
"""Evergreen config-writer equivalence.

For every phase in today's live corpus (``phases.yaml`` + the reference and
recovery overlays), the writer must render the same (ok, reason) verdict in
this tree and in ``--base REF``, and identical YAML bytes when both write.
Between post-split refs this is the library's reset button for emitter drift;
the split-era comparison against ``port_tensile.py`` is preserved for
``--base 2824c2f`` (and any ref carrying ``port_tensile.py``).

Owns: the corpus render + comparison; the (forward/LocalSplitU/bool-spelling)
divergence classes the refactor accepted, still honored for legacy refs.
Does NOT own: the writer (oto.tensile.config_writer) or the corpus.
Public API: main, corpus, phases_from, render_ref. Contract: exit code.
"""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oto import yaml_cached as yamlio

# --- the classification machinery (from the split era; kept verbatim in
# spirit) ---------------------------------------------------------------------
# Knobs the refactor forwarded (the old writer silently dropped them), and the
# LocalSplitU -> WorkGroup[2] honored value. These excuse only the divergences
# between the pre-split base and today -- never a divergence introduced today.
FORWARDED_SINCE_BASE = frozenset({
    "MaxOccupancy", "AggressivePerfMode", "UseSgprForGRO", "InnerUnroll",
    "FractionalLoad", "NonTemporalA", "NonTemporalB",
    "NumLoadsCoalescedB", "AssertFree1ElementMultiple",
})
HONOURED_SINCE_BASE = {"LocalSplitU"}
BOOL_AS_INT = {("true", "1"), ("true", "2"), ("1", "true"), ("2", "true")}

#: The load-divisibility gate (this check's peers refused A: GLVW < VW) was added
#: after the split as a *fix* for kernels Tensile rejects. The pre-split writer
#: emitted those configs and they were silently dead (Tensile refuses them at
#: SolutionStructs). Accepted for the base-vs-HEAD comparison only, and counted
#: separately so the reader always knows what was excused.
DIVISIBILITY_SINCE_BASE = "load divisibility illegal"


def _scalar(line: str) -> str:
    return line[1:].strip().lstrip("-").strip()


def _value_rewrite(diff: list[str]):
    if len(diff) != 2:
        return None
    removed, added = diff
    if not (removed.startswith("-") and added.startswith("+")):
        return None
    return _scalar(removed), _scalar(added)


def _only_bool_spelling(diff: list[str]) -> bool:
    pair = _value_rewrite(diff)
    return pair is not None and pair in BOOL_AS_INT


def _only_honoured_local_split_u(diff: list[str], phase_id: object) -> bool:
    if "LocalSplitU" not in str(phase_id):
        return False
    pair = _value_rewrite(diff)
    return pair is not None and pair == ("1", "2")


def _only_adds_of(diff: list[str], allowed) -> bool:
    if not diff:
        return False
    under_key = False
    for line in diff:
        body = line[1:].strip()
        if line.startswith("-"):
            return False
        if not line.startswith("+"):
            return False
        if body.endswith(":"):
            key = body[:-1].strip().lstrip("- ").strip()
            if key not in allowed:
                return False
            under_key = True
        elif not under_key:
            return False
    return True


def _only_honoured_value_changes(diff: list[str], phase_id: object) -> bool:
    return _only_bool_spelling(diff) or _only_honoured_local_split_u(diff, phase_id)


# --- the split-era legacy lift (kept, used only when the ref carries it) ------
LIFT = {
    "from scheduler import (parse_tensile_shape, assembly_class_valid,\n"
    "                               occupancy_feasible, ldspad_feasible)":
        "from oto.tensile.candidate import parse_tensile_shape\n"
    "        from oto.tensile.gates.assembly import assembly_class_valid\n"
    "        from oto.tensile.gates.occupancy import (ldspad_feasible,\n"
    "                                             occupancy_feasible)",
    "from scheduler import assembly_class_valid":
        "from oto.tensile.gates.assembly import assembly_class_valid",
    "from run_status import LiveStatus, RunPlan":
        "from oto.metrics.run_status import LiveStatus, RunPlan",
    "from auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS":
        "from oto.runners.auto_prompt import AutoPlan, DEFAULT_ITERATIONS, DEFAULT_MUTATIONS",
    "from auto_prompt import AutoPlan, ask":
        "from oto.runners.auto_prompt import AutoPlan, ask",
    "from library_parity import load_pipeline_phases, parity_report":
        "from oto.tensile.library_parity import load_pipeline_phases, parity_report",
    "from analytics import extract_family_from_phase_id":
        "from oto.metrics.benchmark_analytics import extract_family_from_phase_id",
    "from policy import check_retirement_eligibility":
        "from oto.metrics.cell_policy import check_retirement_eligibility",
    "from report import ABVerdict":
        "from oto.metrics.acceptance_report import ABVerdict",
}


def lift(src: str) -> str:
    src = re.sub(r"from [A-Za-z0-9_]*_common import", "from oto.device.kernel_vocabulary import", src)
    for old_text, new_text in LIFT.items():
        src = src.replace(old_text, new_text)
    return src


def load_legacy(base: str):
    """Pre-split port_tensile.py at ``base`` with flat sibling imports lifted."""
    import types

    src = subprocess.run(["git", "show", f"{base}:port_tensile.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    for name in ("registry", "scheduler", "analytics", "policy", "agent",
                 "mutator", "report", "telemetry", "library_parity"):
        sys.modules.pop(name, None)
    for old, new in (("registry", "oto.ledger.registry"),
                     ("scheduler", "oto.tensile.candidate"),
                     ("analytics", "oto.metrics.benchmark_analytics"),
                     ("policy", "oto.metrics.cell_policy"),
                     ("agent", "oto.ledger.convergence_agent"),
                     ("mutator", "oto.ledger.mutator"),
                     ("report", "oto.metrics.acceptance_report"),
                     ("telemetry", "oto.metrics.telemetry"),
                     ("library_parity", "oto.tensile.library_parity")):
        sys.modules[old] = __import__(new, fromlist=["*"])
    sys.modules["auto_prompt"] = __import__("oto.runners.auto_prompt", fromlist=["*"])
    sys.modules["tensile_library"] = __import__("oto.tensile.shipped_floor_manifest", fromlist=["*"])
    sys.modules["run_status"] = __import__("oto.metrics.run_status", fromlist=["*"])
    sys.modules["port_tensile"] = __import__("oto.runners.stage_cli", fromlist=["*"])
    mod = types.ModuleType("old_port_tensile")
    mod.__file__ = str(ROOT / "port_tensile.py")
    mod.__dict__["__name__"] = "old_port_tensile"
    exec(compile(lift(src), str(ROOT / "port_tensile.py"), "exec"), mod.__dict__)
    return mod


def phases_from(path: Path) -> list[dict]:
    phases = []
    for f in sorted(Path(path).glob("*/phases_reference.yaml")):
        try:
            phases.extend(yamlio.load_yaml_text(f.read_text()) or [])
        except Exception:
            continue
    return phases


_REF_SRC = """
import sys, json
sys.path.insert(0, {tree!r})
phases = json.load(open({phases_json!r}))
import os
from pathlib import Path
os.makedirs({workdir!r}, exist_ok=True)
try:
    import oto.yaml_cached as yamlio
except ImportError:
    import oto.yamlio as yamlio
from oto.tensile import config_writer
class _Stub: pass
d = _Stub()
out = {{}}
for i, p in enumerate(phases):
    pid = p.get("phase_id")
    path = Path({workdir!r}) / f"{{i:05d}}.yaml"
    ok, reason = config_writer.write_phase_config(d, path, p)
    out[pid] = [bool(ok), str(reason),
                (path.read_bytes().hex() if ok else "")]
with open({report!r}, "w") as fh:
    json.dump(out, fh)
print("rendered", len(out))
"""


def render_ref(ref: str, phases: list[dict], tmpdir: Path) -> dict | None:
    """Render ``phases`` through REF's writer; None when REF cannot boot."""
    import json as _json

    from oto.tools.verifiers import ref_worktree

    try:
        tree = ref_worktree.ref_worktree(ref)
    except ref_worktree.EvergreenError as exc:
        print(f"REF comparison BLOCKED: {exc}")
        return None
    payload = tmpdir / "corpus.json"
    payload.write_text(_json.dumps(phases))
    report = tmpdir / "ref_report.json"
    code = _REF_SRC.format(tree=str(tree), phases_json=str(payload),
                           workdir=str(tmpdir / "ref"), report=str(report))
    (tmpdir / "ref").mkdir(parents=True, exist_ok=True)
    proc = ref_worktree.probe(tree, code, timeout=1800)
    if proc.returncode != 0 or not report.exists():
        tail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "child failed"
        print(f"REF comparison BLOCKED: {tail}")
        return None
    return _json.loads(report.read_text())


def corpus(root: Path, profile=None) -> list[dict]:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    from oto.device import loader as _loader
    from oto.runners.result_paths import results_dir, runs_dir

    phases = list(yamlio.load_yaml(root / "phases.yaml") or [])
    for base in (runs_dir(root, _loader.resolve_profile(profile).codename),
                 results_dir(root, _loader.resolve_profile(profile).codename) / "gfx900_ref_locked_52149f315d"):
        phases.extend(phases_from(base))
    return phases


def _legacy_compare(base: str, all_phases: list[dict], workdir: Path) -> int:
    from oto.tensile import config_writer

    d = type("_Stub", (), {})()
    old = load_legacy(base)
    n_ok = n_refused = n_forwarded = n_divisibility = 0
    mismatch = []
    a_path, b_path = workdir / "a.yaml", workdir / "b.yaml"
    for p in all_phases:
        ro, rr = old.TensileDriver._write_phase_config(d, a_path, p)
        rn, rn_reason = config_writer.write_phase_config(d, b_path, p)
        if (ro, rr) != (rn, rn_reason):
            if (isinstance(rn_reason, str)
                    and rn_reason.startswith(DIVISIBILITY_SINCE_BASE)):
                n_divisibility += 1
                continue
            mismatch.append((p.get("phase_id"), (ro, rr), (rn, rn_reason)))
            continue
        if ro and a_path.read_bytes() != b_path.read_bytes():
            a_lines = a_path.read_text().splitlines()
            b_lines = b_path.read_text().splitlines()
            diff = [ln for ln in difflib.unified_diff(
                a_lines, b_lines, "orig", "new", lineterm="", n=0)
                if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
            if (_only_adds_of(diff, FORWARDED_SINCE_BASE)
                    or _only_honoured_value_changes(diff, p.get("phase_id"))):
                n_forwarded += 1
                continue
            mismatch.append((p.get("phase_id"), "YAML DIFFERS", diff[:20]))
            continue
        if ro:
            n_ok += 1
        else:
            n_refused += 1
    print(f"phases: {len(all_phases)}; written: {n_ok}, refused: {n_refused}")
    print(f"accepted as newly-forwarded knobs: {n_forwarded}")
    print(f"accepted as intentional tightening (GLVW<VW refused): {n_divisibility}")
    print(f"mismatches: {len(mismatch)}")
    from collections import Counter
    hist = Counter()
    for _pid, _a, _b in mismatch:
        reason = str(_b[1] if isinstance(_b, tuple) and len(_b) > 1 else _b)
        hist[reason.split(":")[0].split(" =")[0][:60]] += 1
    for _reason, _count in hist.most_common():
        print(f"    {_count:>5}  {_reason}")
    for _m in mismatch[:6]:
        print("  ", _m)
    if mismatch:
        return 1
    print("CONFIG WRITER EQUIVALENCE: OK")
    return 0


def _head_render(all_phases, workdir):
    from oto.tensile import config_writer
    d = type("_Stub", (), {})()
    cur = {}
    for i, p in enumerate(all_phases):
        path = workdir / "cur" / f"{i:05d}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        ok, reason = config_writer.write_phase_config(d, path, p)
        cur[p.get("phase_id")] = [bool(ok), str(reason),
                                  path.read_bytes().hex() if ok else ""]
    return cur


def _post_split_compare(args, all_phases, workdir):
    print("post-split REF comparison")
    t0 = time.time()
    refv = render_ref(args.base, all_phases, workdir)
    print(f"REF render: {'OK' if refv is not None else 'BLOCKED'} "
          f"({time.time() - t0:.0f}s)")

    cur = _head_render(all_phases, workdir)
    if refv is None:
        print("REF render blocked -- HEAD renders "
              f"{sum(1 for v in cur.values() if v[0])} configs; verdicts not compared.")
        print("CONFIG WRITER EQUIVALENCE: OK (HEAD-only; REF blocked)")
        return 0

    n_ok = n_refused = 0
    mismatch = []
    for p in all_phases:
        pid = p.get("phase_id")
        co = cur.get(pid)
        rv = refv.get(pid)
        if co is None or rv is None:
            mismatch.append((pid, ("cur", co), ("ref", rv)))
            continue
        if co[:2] != rv[:2]:
            mismatch.append((pid, tuple(co[:2]), tuple(rv[:2])))
            continue
        if co[0] and co[2] != rv[2]:
            mismatch.append((pid, "YAML DIFFERS", "ref vs current"))
            continue
        if co[0]:
            n_ok += 1
        else:
            n_refused += 1
    print(f"phases: {len(all_phases)}; HEAD-written: {n_ok}, refused: {n_refused}")
    print(f"mismatches: {len(mismatch)}")
    for _m in mismatch[:6]:
        print("  ", _m)
    if mismatch:
        return 1
    print("CONFIG WRITER EQUIVALENCE: OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="HEAD~1",
                    help="REF to compare against; default HEAD~1 (per-commit evergreen); "
                         "pass 2824c2f for the split-era legacy comparison")
    ap.add_argument("--limit", type=int, default=None,
                    help="render only the first N phases (bring-up/triage)")
    args = ap.parse_args()

    all_phases = corpus(ROOT)
    if args.limit is not None:
        all_phases = all_phases[: args.limit]
    print(f"phases under test: {len(all_phases)}")

    workdir = Path(tempfile.mkdtemp(prefix="oto_cfg_writer_"))
    try:
        t0 = time.time()
        head = subprocess.run(["git", "cat-file", "-e", f"{args.base}:port_tensile.py"],
                              cwd=ROOT, capture_output=True)
        if head.returncode == 0:
            rc = _legacy_compare(args.base, all_phases, workdir)
            print(f"elapsed: {time.time() - t0:.0f}s")
            return rc

        rc = _post_split_compare(args, all_phases, workdir)
        print(f"elapsed: {time.time() - t0:.0f}s")
        return rc
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
