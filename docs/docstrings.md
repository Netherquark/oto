# The docstring convention

Applies to every module, class and function in `oto/`. The boundary this sits
under is `docs/README.md` — read that first if you are unsure whether a fact is
a docstring or an MD.

## Module docstring

Three mandatory clauses, in this order, each starting with the same lead-in so a
reader can scan for them:

```python
"""Register-file and LDS occupancy gates.

Owns: the CPU-only model that reproduces every observed gfx90c occupancy
outcome (occupancy_feasible, ldspad_feasible, the swizzle StaggerU rules).
Does NOT own: the candidate generator (oto.tensile.candidate), the VGPR
*measurement* table (oto.tensile.gates.vgpr_model), or any device constant
(oto.device.peaks).
Public API: occupancy_feasible, ldspad_feasible.
"""
```

1. **Owns** — the one responsibility. If you cannot write this clause in one
   sentence, the module has two responsibilities and should be split.
2. **Does NOT own** — the neighbouring modules whose job is most often confused
   with this one. This is the clause that stops one fact acquiring two homes,
   which is the failure `claude.md` section 3 exists to prevent. It is also the
   clause that drifts: after a move, run `grep` for the module's old name and
   check every `Does NOT own` mention still points somewhere real.
3. **Public API** — the names an outside caller needs, so nobody has to read the
   body to find them.

`Does NOT own` is required even when the answer is uninteresting ("does not
perform I/O"), because the interesting failure is the module that acquired a
second responsibility without anyone deciding it should.

## Class docstring

Same three clauses, plus — for a mixin — which composition root it is mixed
into:

```python
class HarvestMixin:
    """Parent selection, mixed into ConvergenceAgent.

    Owns: ...
    """
```

## Function docstring

1. **One-line summary.** Not a restatement of the name; the thing the name does
   not tell you.
2. **Args / Returns** where either is non-obvious. A single obvious argument does
   not need a section.
3. **Why** where the behaviour is non-obvious. Not *what* it does — the code
   already says that — but *why it has to*. Cite the source fact with
   `file:line`; a line number is allowed here precisely because a docstring is
   pinned to the same commit as the code it describes, which an MD is not.

Example, from `oto/tensile/gates/occupancy.py`:

```python
def occupancy_feasible(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Register-file gate: reject configs Tensile cannot generate.

    Why fail closed on an unknown dtype: a wrong guess would pick the wrong
    VGPR weight (Z is 8, S is 1) and silently admit a config the gate must
    reject. See ``oto/tensile/gates/vgpr_model.MEASURED_VGPR_BY_DTYPE`` for
    the measured boundary.
    """
```

## What a docstring must never contain

* **A corpus count.** The tier sizes, cell counts and kernel totals move every
  time a cell is re-triaged, and a number transcribed into a docstring is wrong
  the moment that happens. Cite the *date and decision* instead. This is the
  `claude.md` section 5 rule; it applies to docstrings exactly as to MDs.
* **Benchmark results.** Those are `results.md`'s job; a docstring that quotes a
  number from one run is a changelog entry in the wrong file.
* **A reference to deleted machinery.** Anything removed from the codebase must
  not reappear in code, configs or docs, in any wording.
* **The words "obviously" or "simply".** If it were, the code would not need a
  comment.

## Enforcement

`oto/tools/verifiers/verify_all.py` proves the code did not change during the package split.
It says nothing about docstrings. The convention is enforced by review: when you
touch a module, check its three clauses still describe it, and check its
`Does NOT own` neighbours have not quietly absorbed one of its jobs.
