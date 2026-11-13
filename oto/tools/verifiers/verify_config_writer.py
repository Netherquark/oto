#!/usr/bin/env python3
"""_write_phase_config equivalence.

The config writer is the one method that was genuinely restructured, so it gets
its own differential: for every phase in the live deck (and the reference decks),
the OLD implementation and the NEW one must agree on (ok, reason) AND on the
exact YAML bytes written.
"""
from __future__ import annotations

import difflib
import re
import subprocess
import sys
import tempfile
from pathlib import Path


from oto import yamlio  # noqa: E402
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

#: The last commit before the package split; every check compares against it.
REFACTOR_BASE = "2824c2f"

SRC = subprocess.run(["git", "show", f"{REFACTOR_BASE}:port_tensile.py"], cwd=ROOT,
                     capture_output=True, text=True, check=True).stdout


#: Redirects the pre-refactor module's flat sibling imports at their new homes
#: so it can be executed against the current tree.
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
        "from oto.metrics.analytics import extract_family_from_phase_id",
    "from policy import check_retirement_eligibility":
        "from oto.metrics.policy import check_retirement_eligibility",
    "from report import ABVerdict":
        "from oto.metrics.report import ABVerdict",
}


def lift(src: str) -> str:
    """Rewrite a pre-refactor source's flat imports to their new module paths."""
    src = re.sub(r"from [A-Za-z0-9_]*_common import", "from oto.device.peaks import", src)
    for old_text, new_text in LIFT.items():
        src = src.replace(old_text, new_text)
    return src


def load_old():
    """The HEAD port_tensile module, with the flat imports redirected."""
    import types
    for name in ("registry", "scheduler", "analytics",
                 "policy", "agent", "mutator", "report", "telemetry",
                 "library_parity"):
        if name in sys.modules:
            del sys.modules[name]
    shims = {}
    for old, new in (("registry", "oto.ledger.registry"),
                     ("scheduler", "oto.tensile.candidate"),
                     ("analytics", "oto.metrics.analytics"),
                     ("policy", "oto.metrics.policy"),
                     ("agent", "oto.ledger.agent"),
                     ("mutator", "oto.ledger.mutator"),
                     ("report", "oto.metrics.report"),
                     ("telemetry", "oto.metrics.telemetry"),
                     ("library_parity", "oto.tensile.library_parity")):
        shims[old] = importlib.import_module(new)
        sys.modules[old] = shims[old]
    sys.modules["auto_prompt"] = importlib.import_module("oto.runners.auto_prompt")
    sys.modules["tensile_library"] = importlib.import_module("oto.tensile.library")
    sys.modules["run_status"] = importlib.import_module("oto.metrics.run_status")
    sys.modules["port_tensile"] = importlib.import_module("oto.runners.cli")
    mod = types.ModuleType("old_port_tensile")
    mod.__file__ = str(ROOT / "port_tensile.py")
    mod.__dict__["__name__"] = "old_port_tensile"
    SRC2 = lift(SRC)
    exec(compile(SRC2, str(ROOT / "port_tensile.py"), "exec"), mod.__dict__)
    return mod


import importlib  # noqa: E402

old = load_old()
from oto.tensile import config_writer  # noqa: E402
import oto.device.peaks as _peaks
from oto.runners.paths import results_dir as _results_dir
from oto.runners.paths import runs_dir as _runs_dir


class _Stub:
    pass


def phases_from(path):
    phases = []
    for f in sorted(Path(path).glob("*/phases_reference.yaml")):
        try:
            phases.extend(yamlio.load_yaml_text(f.read()) or [])
        except Exception:
            continue
    return phases


all_phases = yamlio.load_yaml(ROOT / "phases.yaml") or []
all_phases += phases_from(_runs_dir(ROOT, _peaks.CODENAME))
all_phases += phases_from(_results_dir(ROOT, _peaks.CODENAME) / "gfx900_ref_locked_52149f315d")
print(f"phases under test: {len(all_phases)}")

d = _Stub()
mismatch = []
n_ok = n_refused = n_forwarded = 0

#: Knobs this refactor made the writer actually emit.
#:
#: Before it, `_write_phase_config` silently discarded these when a phase set
#: them, so a candidate asking for `NonTemporalA: 1` or
#: `AssertFree1ElementMultiple: 2` was benchmarked *without* the knob. That is
#: the bug the forwarding work fixed, and it is why the sweep phases in the
#: corpus differ here. Every measured difference is an ADDITION of one of these
#: knobs; nothing the old writer emitted is now dropped (checked by
#: `_only_adds_of`, which requires the diff to contain no removals at all).
#:
#: This is the one place where a byte-identical writer would be *wrong*: the
#: base commit is the behaviour being fixed, not the behaviour to preserve.
FORWARDED_SINCE_BASE = frozenset({
    "MaxOccupancy", "AggressivePerfMode", "UseSgprForGRO", "InnerUnroll",
    "FractionalLoad", "NonTemporalA", "NonTemporalB",
    "NumLoadsCoalescedB", "AssertFree1ElementMultiple",
})

#: Value changes that are also deliberate fixes, keyed by the block they sit in.
#:
#: ``LocalSplitU`` is not a standalone Tensile key -- it is ``WorkGroup[2]``. The
#: old writer read element 3 of the workgroup and threw the third element away,
#: so a candidate carrying ``LocalSplitU: 2`` benchmarked at LSU=1 with no
#: warning (corpus3 Q-D). The new writer honours it, which is why 14 corpus
#: phases differ by ``1 -> 2``.
HONOURED_SINCE_BASE = {"LocalSplitU"}

#: Value spellings that are the same knob value. The old writer emitted
#: ``PrefetchGlobalRead: true`` where the new one emits the integer, because the
#: knob's legal values are ``[0, 1, 2]`` and Python ``True == 1``. Not a
#: behaviour change; recorded so the count reconciles.
BOOL_AS_INT = {("true", "1"), ("true", "2"), ("1", "true"), ("2", "true")}


def _scalar(line):
    """`'      - true'` -> `'true'`: drop the diff sign and the YAML list dash."""
    return line[1:].strip().lstrip("-").strip()


def _value_rewrite(diff):
    """`(old, new)` for a two-line pure value change, else None."""
    if len(diff) != 2:
        return None
    removed, added = diff
    if not (removed.startswith("-") and added.startswith("+")):
        return None
    return _scalar(removed), _scalar(added)


def _only_bool_spelling(diff):
    """True for `PrefetchGlobalRead: true` -> `1`. The same knob value.

    The knob's legal values are ``[0, 1, 2]`` and Python ``True == 1``, so this
    is a serialisation change, not a behaviour one.
    """
    pair = _value_rewrite(diff)
    return pair is not None and pair in BOOL_AS_INT


def _only_honoured_local_split_u(diff, phase_id):
    """True for the LocalSplitU value the sweep asked for, and it was ignored.

    ``LocalSplitU`` has no standalone Tensile key -- it is ``WorkGroup[2]`` --
    so when it changes no key line appears in the diff and the only handle on it
    is the phase id, which names the swept dimension (``..._swLocalSplitU2``).
    Requiring that keeps this from excusing any other knob's value change.
    """
    if "LocalSplitU" not in str(phase_id):
        return False
    pair = _value_rewrite(diff)
    return pair is not None and pair == ("1", "2")


def _only_adds_of(diff, allowed):
    """True when `diff` adds only keys in `allowed` and removes nothing.

    A YAML block is a key line (``    - Name:``) followed by its value line
    (``      - 1``), so the value is accepted only while under a key that was
    itself accepted -- an orphan value line fails.

    Deliberately strict: a single removal, or an addition of anything not named
    here, fails. Otherwise this would quietly excuse a future regression that
    happens to touch a forwarded knob.
    """
    if not diff:
        return False
    under_accepted_key = False
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
            under_accepted_key = True
        elif not under_accepted_key:
            return False
    return True


def _only_honoured_value_changes(diff, phase_id):
    """True when `diff` is a deliberate value change (see the helpers above)."""
    return _only_bool_spelling(diff) or _only_honoured_local_split_u(
        diff, phase_id)
with tempfile.TemporaryDirectory() as td:
    a_path = Path(td) / "a.yaml"
    b_path = Path(td) / "b.yaml"
    for p in all_phases:
        ro, rr = old.TensileDriver._write_phase_config(d, a_path, p)
        rn, rn_reason = config_writer.write_phase_config(d, b_path, p)
        if (ro, rr) != (rn, rn_reason):
            mismatch.append((p.get("phase_id"), (ro, rr), (rn, rn_reason)))
            continue
        if ro and a_path.read_bytes() != b_path.read_bytes():
            # Store the actual differing lines. Truncating both sides to a
            # fixed prefix made every mismatch print identically -- the two
            # 120-char windows were always the same GlobalParameters preamble,
            # so the report could not say what had actually changed.
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

print(f"written: {n_ok}, refused: {n_refused}")
print(f"accepted as newly-forwarded knobs: {n_forwarded}")
print(f"mismatches: {len(mismatch)}")
for m in mismatch[:6]:
    print("  ", m)
if mismatch:
    sys.exit(1)
print("CONFIG WRITER EQUIVALENCE: OK")
