#!/usr/bin/env python3
"""Evergreen gate differential.

Each tree renders the same corpus of configs through the gate surface; the
two verdict streams must agree verdict-for-verdict (and on the accepted
diagnostic-message rewrites). The REF side runs in a detached worktree of
``--base REF`` (default HEAD~1, the per-commit gate). The comparison never
depend on which commit produced HEAD: the base is a parameter, nothing is
pinned.

Owns: the verdict-stream comparison (verdict_flipped / text_differs /
old_raised / new_raised buckets).
Does NOT own: the gate logic (`oto.tensile.gates`.*) or the corpus
(verdict_corpus). Public API: main; the contract is the process exit code.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: The one reject message the split reworded (kept: verdict comparison still
#: happens on every row).
ACCEPTED_MESSAGE_REWRITES = (
    (re.compile(r"\bGLVW (\d+) \* bpe (\d+) > 16$"), r"GLVWA \1 * bpe \2 > 16"),
)


def _verdict(v):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return v[0] if v and v[0] != "EXC" else None
    return v


def _message(v):
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return v[1]
    return None


def check(row, out):
    """Bucket one comparison (labels: cur vs ref)."""
    label = f"{row['f']}:{json.dumps(row['c'], sort_keys=True)}"
    a, b = row["r"]
    if a == b:
        return
    buckets = out["buckets"]
    if isinstance(a, (list, tuple)) and a and a[0] == "EXC":
        buckets["old_raised"].append((label, a, b))
        return
    if isinstance(b, (list, tuple)) and b and b[0] == "EXC":
        buckets["new_raised"].append((label, a, b))
        return
    av, bv = _verdict(a), _verdict(b)
    if av == bv:
        am, bm = _message(a), _message(b)
        for pattern, replacement in ACCEPTED_MESSAGE_REWRITES:
            if isinstance(am, str) and pattern.sub(replacement, am) == bm:
                return
        buckets["text_differs"].append((label, a, b))
        return
    buckets["verdict_flipped"].append((label, a, b))
    return


def _attest(name: str, base: str) -> bool:
    from oto.tools.verifiers.ref_worktree import gate_attested
    return gate_attested("gate_differential", base, name)


def _compress_shim(profile=None) -> tuple[str, str]:
    """``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile."""
    import json as _json

    from oto.device.loader import resolve_profile

    prof = resolve_profile(profile)
    shim = _json.dumps({
        "NUM_CUS": prof.num_cus,
        "LDS_PER_CU_KB": prof.lds_per_cu_kb,
        "MAX_WAVES_PER_CU": prof.max_waves_per_cu,
        "FAMILY_DTYPE_CHAR": dict(prof.family_dtype_char),
    })
    archs = _json.dumps([prof.codename, "gfx900", None])
    return shim, archs


def _emit(tree: Path, path: Path, base: str, shim: str, archs: str,
          worker: Path | None = None) -> None:
    from oto.tools.verifiers import ref_worktree

    if worker is not None:
        import shutil

        dst = tree / "oto/tools/verifiers/verdict_corpus.py"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(worker, dst)

    proc = ref_worktree.probe(
        tree,
        f"from oto.tools.verifiers.verdict_corpus import emit; "
        f"emit({str(path)!r}, {base!r})",
        env_extra={"OTO_PROFILE_SHIM": shim, "OTO_ARCHS": archs},
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit(2)


def _compare(cur_path: Path, ref_path: Path, base: str) -> int:
    buckets: dict = {"verdict_flipped": [], "text_differs": [],
                     "old_raised": [], "new_raised": []}
    n = 0
    with cur_path.open() as fa, ref_path.open() as fb:
        for la, lb in zip(fa, fb, strict=False):
            row = json.loads(la)
            ref_row = json.loads(lb)
            if (row["f"], row["c"]) != (ref_row["f"], ref_row["c"]):
                buckets["new_raised"].append(("ROW ORDER DIVERGED", row, ref_row))
                break
            row["r"] = (ref_row["r"], row["r"])  # ref vs cur
            check(row, {"buckets": buckets})
            n += 1
    print(f"differential comparisons: {n}")
    print(f"  the REF gate raised where HEAD returns a verdict: "
          f"{len(buckets['old_raised'])}")

    if base == "2824c2f":
        n_attested = 0
        for bucket_name in ("verdict_flipped", "text_differs"):
            kept = []
            for row in buckets[bucket_name]:
                if _attest(row[0].split(":", 1)[0], base):
                    n_attested += 1
                else:
                    kept.append(row)
            buckets[bucket_name] = kept
        if n_attested:
            print(f"INTENTIONAL DIVERGENCE vs {base} "
                  f"(manifest-attested, legacy legality closure): "
                  f"{n_attested} rows attested and excused")

    fails = buckets["verdict_flipped"] + buckets["text_differs"] + buckets["new_raised"]
    if fails:
        print(f"FAILURES: {len(fails)}")
        for key in ("new_raised", "verdict_flipped", "text_differs"):
            rows = buckets[key]
            if not rows:
                continue
            print(f"  {key}: {len(rows)}")
            for _label, _a, _b in rows[:6]:
                print(f"   {key[:4].upper()} {_label}")
                print("     ref :", _a)
                print("     cur :", _b)
        return 1
    print("ALL EQUAL")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="HEAD~1",
                    help="ref to compare against (default: HEAD~1 -- the per-commit "
                         "evergreen check; pass a specific ref for the legacy comparison)")
    args = ap.parse_args()

    from oto.tools.verifiers import ref_worktree

    print(f"base: {args.base}")
    shim, archs = _compress_shim()
    cur_path = ref_worktree.scratch_dir() / "_gate_cur.jsonl"
    ref_path = ref_worktree.scratch_dir() / "_gate_ref.jsonl"

    _emit(ROOT, cur_path, args.base, shim, archs)
    try:
        ref_dir = ref_worktree.ref_worktree(args.base)
    except ref_worktree.EvergreenError as exc:
        print(f"REF worktree BLOCKED: {exc}")
        sys.exit(2)

    worker_src = Path(__file__).with_name("verdict_corpus.py")
    _emit(ref_dir, ref_path, args.base, shim, archs, worker=worker_src)
    return _compare(cur_path, ref_path, args.base)



if __name__ == "__main__":
    sys.exit(main())
