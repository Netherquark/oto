"""Element-multiple assertions are checked against the problem shape.

`AssertFree0ElementMultiple`, `AssertFree1ElementMultiple` and
`AssertSummationElementMultiple` are Tensile **assertions**, not hints. Tensile's
own `validParameters` comment says the kernel generator "will assume that the
... size is some multiple", and for the summation case it says outright that this
"requires runtime checking to ensure the specified summation value meets the
requirements" — which Tensile does not do. A wrong value drops the M/N/K
predication the kernel needed and returns **silently wrong numbers**, so there is
no loud failure to notice.

Nothing else in the pipeline can catch this. The gate families in
`oto.tensile.gates` validate a *config*; these assertions are about a *shape*,
and the gates never see one. `oto.harness.candidate_pool._offer_row` is the only
place config and shape are both in scope, so that is where the check lives.

What is covered:

* the dimension each assertion claims (AF0->M, AF1->N, ASEM->K), read from
  Tensile's FreeIndex naming rather than assumed;
* the `GlobalSplitU` interaction -- Tensile applies `ASEM//GSU`, so an ASEM that
  is not a multiple of GSU does not mean what it says;
* "1 means no assertion" -- a config that omits every assertion must pass on any
  size, including the awkward ones;
* the shipped assertion rows really hold on every shape they are measured on,
  and a row that loses a cell to its own assertion says so in its note. This is
  the regression guard for the CC:256 steal batch: it passes today, and the
  test says so explicitly rather than leaving it to inspection.

CPU only. No GPU, no Tensile run.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oto.harness.candidate_pool import (
    _assertion_failures,
    _shapes_satisfying_assertions,
)
from oto.harness.candidate_rows import TARGET_CELLS


def _sides(fam: str) -> tuple:
    """TARGET_CELLS entries as ints (the list mixes ints and 'NxNxN')."""
    return tuple(int(s) if isinstance(s, int) else int(str(s).split("x")[0])
                 for s in TARGET_CELLS[fam])


# ------------------------------------------------------------ dimensions

def test_free0_asserts_m_and_free1_asserts_n():
    """AF0 is FreeIndex[0]='I'=M; AF1 is FreeIndex[1]='J'=N."""
    af0 = {"AssertFree0ElementMultiple": 4}
    af1 = {"AssertFree1ElementMultiple": 4}
    # 258 is not a multiple of 4. The failure must name the right dimension, or
    # a TLU=0 transpose would silently assert the wrong axis.
    assert _assertion_failures(af0, 258) == [
        "M=258 not a multiple of AssertFree0ElementMultiple=4"]
    assert _assertion_failures(af1, 258) == [
        "N=258 not a multiple of AssertFree1ElementMultiple=4"]
    # 256 is fine for both, and each assertion must ignore the other axis.
    assert _assertion_failures(af0, 256) == []
    assert _assertion_failures(af1, 256) == []


def test_summation_asserts_k():
    assert _assertion_failures({"AssertSummationElementMultiple": 4}, 258) == [
        "K=258 not a multiple of AssertSummationElementMultiple=4"]


def test_summation_must_also_divide_by_gsu():
    """Tensile applies ASEM//GSU, so ASEM % GSU == 0 is part of the assertion."""
    assert _assertion_failures(
        {"AssertSummationElementMultiple": 8, "GlobalSplitU": 4}, 256) == [], \
        "ASEM=8 divides by GSU=4, so ASEM//GSU=2 is the asserted multiple"
    bad = _assertion_failures(
        {"AssertSummationElementMultiple": 8, "GlobalSplitU": 16}, 256)
    assert bad, "ASEM=8 does not divide by GSU=16"
    assert "GlobalSplitU=16" in bad[0]


def test_one_means_no_assertion():
    """Tensile: '1 indicates no assertion (since all sizes are multiples of 1)'."""
    for config in ({}, {"AssertFree0ElementMultiple": 1},
                   {"AssertFree1ElementMultiple": 1},
                   {"AssertSummationElementMultiple": 1},
                   {"AssertFree0ElementMultiple": "1"}):
        assert _assertion_failures(config, 1365) == [], \
            "1365 is divisible by 1 and nothing else"


# ---------------------------------------------------------- shape filter

def test_filter_keeps_only_satisfied_shapes():
    kept, refused = _shapes_satisfying_assertions(
        {"AssertFree0ElementMultiple": 4, "AssertFree1ElementMultiple": 4},
        (192, 256, 512, 1000, 1365))
    assert kept == (192, 256, 512, 1000)
    assert len(refused) == 1
    assert "1365" in refused[0]


def test_row_is_dropped_only_when_no_shape_survives():
    kept, refused = _shapes_satisfying_assertions(
        {"AssertFree0ElementMultiple": 4}, (1365,))
    assert kept == ()
    assert len(refused) == 1


# ------------------------------------------------------- shipped rows hold

def test_every_shipped_assertion_row_holds_on_every_shape_it_carries():
    """The regression guard for the CC:256 steal batch (PLAN_BATCH, R8).

    2026-10-20 (R40): checked against each row's *emitted* shape list rather
    than `TARGET_CELLS`, because `_offer_row` filters the target list through
    `_shapes_satisfying_assertions` before the row is built. That filter is why
    a shipped assertion can never be silently wrong on a shape it is measured
    on; what it can do is cost a cell, so the second half asserts the loss is
    reported in the row note instead of disappearing. The invariant is
    unchanged and is now end-to-end: every shape a row is measured on satisfies
    that row's assertions.
    """
    from oto.harness.candidate_pool import iter_candidates

    checked = asserted = 0
    for row in iter_candidates():
        config = row["config"]
        if (config.get("AssertFree0ElementMultiple", 1) == 1
                and config.get("AssertFree1ElementMultiple", 1) == 1):
            continue
        asserted += 1
        assert row["shapes"], f"assertion row with no survivable shape: {row}"
        offered = len(TARGET_CELLS[config["FamilyLabel"]])
        if len(row["shapes"]) < offered:
            assert "assertion filter" in row.get("note", ""), (
                "a row that lost a cell to its own assertion must say so in its "
                f"note: {row.get('note')!r}")
        for shape in row["shapes"]:
            checked += 1
            side = int(shape.split("x")[0])
            assert _assertion_failures(config, side) == [], (
                f"{config['FamilyLabel']}:{side} -- a shipped assertion row does "
                "not hold on a shape it is measured on. That is the "
                "silently-wrong-results case. "
                f"row note: {row.get('note')!r}")

    assert asserted and checked, (
        "no emitted row carries an assertion; if that is intentional, say so "
        "here rather than letting the guard rot into a no-op")


def test_a_non_divisible_target_shape_would_be_caught():
    """The landmine this guard exists for, proven live.

    `SS` targets include 1365, which is divisible by neither 2 nor 4. An AF=4 SS
    row would be silently wrong on it. This asserts the guard refuses it, so
    adding such a row later fails here instead of on hardware.
    """
    assert 1365 in _sides("SS")
    assert _assertion_failures({"AssertFree0ElementMultiple": 4}, 1365), \
        "SS:1365 must refuse an AF=4 row; if it no longer does, re-check the " \
        "divisibility rule against Tensile's FreeIndex semantics"
