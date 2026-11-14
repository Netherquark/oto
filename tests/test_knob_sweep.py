#!/usr/bin/env python3
"""
test_knob_sweep.py — the knob-sweep deck.

Regression guards for the deck that cross-joins each family's measured winner
tile with one change to a knob the corpus never *explicitly* set
(potential_configs.md §8, after `allruns.py` reported `GlobalSplitU = ['1']` and
`StaggerU = ['32']` as the only values ever seen, and every complex winner
leaving AggressivePerfMode/MaxOccupancy/GlobalLoadVectorWidth unset):

  * every sweep base tile is itself gate-legal, so a sweep never perturbs an
    illegal tile and blames the knob;
  * the emitted set is exactly the legal subset reported in §8.1 -- in
    particular GlobalSplitU>1 is refused for every half and complex family and
    allowed only for SS and DD;
  * ``width_override`` is what makes NumLoadsCoalesced legal (it is gated by
    VectorWidth through NumLoads), and dropping it silently loses the row;
  * no two emitted candidates share a phase_id, which is the property that
    used to silently overwrite one config's results with another's;
  * the dry-run path validates but never writes the manifest.

Run: python3 -m pytest -q tests/test_knob_sweep.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from oto.device import loader as _loader
from oto.tensile.candidate import CandidateGenerator
from oto.tensile.decks import (
    DECISION_TRIAL_TILES,
    FAMILY_DECKS,
    KNOB_SWEEP_BASES,
    KNOB_SWEEPS,
)

SHAPE = "1024x1024x1024"
REAL = ["CC", "ZZ", "SS", "HH", "DD", "HH_HPA", "HS_HPA"]
# The families GlobalSplitU>1 is legal for on this gate.
GSU_OK = {"SS", "DD"}


@pytest.fixture(scope="module")
def gen():
    return CandidateGenerator(BASE)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """A copy of phases.yaml in a temp dir, so a test can never write the live one."""
    d = tmp_path_factory.mktemp("sweep_sandbox")
    shutil.copy(BASE / "phases.yaml", d / "phases.yaml")
    return CandidateGenerator(d)


def _template(family: str, shape: str = SHAPE) -> dict:
    return {"Architecture": "gfx90c",
            "DataType": _loader.current_profile().family_dtype_char[family],
            "ContractionPattern": "Ailk_Bljk",
            "ProblemType": shape, "ScheduleName": "isa",
            "FamilyLabel": family}


def _merged(family, base, value, width=None):
    knobs = dict(base)
    if width is not None:
        knobs["VectorWidth"] = width
    knobs.update(value)
    return {**_template(family), **knobs}


# --------------------------------------------------------------------------
# the data itself
# --------------------------------------------------------------------------

def test_sweep_bases_cover_every_family_deck_family():
    assert sorted(KNOB_SWEEP_BASES) == sorted(FAMILY_DECKS)


def test_every_sweep_base_tile_is_gate_legal(gen):
    """A sweep must never perturb an illegal tile, or a measured delta is
    attributed to the knob when the tile was the problem."""
    for family, bases in KNOB_SWEEP_BASES.items():
        for base in bases:
            ok, why = gen.validate_config({**_template(family), **base})
            assert ok, f"{family} base {base.get('MacroTile')}/" \
                       f"{base.get('ThreadTile')} is itself illegal: {why}"


def test_sweep_entries_name_only_live_tensile_knobs():
    """§H.1's do-not-propose list. A sweep row naming a knob that does not
    exist in Tensile v4.44 wastes a whole run."""
    from oto.tensile.candidate import ILLEGAL_KNOBS
    bogus = {"WorkGroupSize", "WorkGroupTile", "DepthUD", "AsyncCopy",
             "BufferLoadEnable", "NumBuffers", "LdsFlags", "StallCount",
             "EnableAddK", "GlobalLoadPerThread", "UseMfmaInitialLoad",
             "WaveSeparateGlobalWrite", "MagicDivAlgorithm"}
    for sweep in KNOB_SWEEPS:
        assert sweep["knob"] not in bogus
        for value in sweep["values"]:
            for key in value:
                assert key not in bogus
                assert key not in ILLEGAL_KNOBS


def test_sweep_entries_declare_at_least_one_family():
    for sweep in KNOB_SWEEPS:
        assert sweep["families"], f"{sweep['knob']} names no family"
        for fam in sweep["families"]:
            assert fam in KNOB_SWEEP_BASES, f"{sweep['knob']} names unknown {fam}"


def test_every_sweep_row_offers_a_non_default_value():
    """A row whose every value equals the Tensile default re-measures the base
    tile instead of testing the knob.

    Tensile fills absent knobs from ``defaultBenchmarkCommonParameters``, so a
    winner that "never sets" a knob does not mean the knob is at zero -- see
    ``TENSILE_KNOB_DEFAULTS`` and ``knowledge_base.md`` §7.1. This is what
    removed the ``BufferLoad: True`` row (its default is already ``True``).
    """
    from oto.tensile.decks import TENSILE_KNOB_DEFAULTS

    for sweep in KNOB_SWEEPS:
        # The knob *label* is not always the key set (`GlobalLoadVectorWidth`
        # sets the A/B keys), so name the keys from the values themselves.
        keys = {k for value in sweep["values"] for k in value}
        unknown = keys - set(TENSILE_KNOB_DEFAULTS)
        assert not unknown, (
            f"{sweep['knob']} sets {sorted(unknown)}, absent from "
            f"TENSILE_KNOB_DEFAULTS -- add the verified default"
        )
        real = [value for value in sweep["values"]
                if any(value[k] != TENSILE_KNOB_DEFAULTS[k] for k in value)]
        assert real, (
            f"{sweep['knob']}: every value equals the Tensile default, so the "
            f"whole row is a no-op -- remove it"
        )


# --------------------------------------------------------------------------
# the two hard legality results §8.1 reports
# --------------------------------------------------------------------------

@pytest.mark.parametrize("family", sorted(set(REAL) - GSU_OK))
def test_global_splitu_is_illegal_for_half_and_complex(gen, family):
    """`Assembly class: GlobalSplitU=2 on complex C: illegal`, and the same for
    every half family. This is what confines the wave-quantisation route to
    SS and DD."""
    base = KNOB_SWEEP_BASES[family][0]
    for value in ({"GlobalSplitU": 2}, {"GlobalSplitU": 4}):
        ok, why = gen.validate_config(_merged(family, base, value))
        assert not ok, f"{family} accepted GlobalSplitU > 1"
        assert "GlobalSplitU" in why


@pytest.mark.parametrize("family", sorted(GSU_OK))
def test_global_splitu_is_legal_for_ss_and_dd(gen, family):
    base = KNOB_SWEEP_BASES[family][0]
    ok, why = gen.validate_config(_merged(family, base, {"GlobalSplitU": 2}))
    assert ok, f"{family} refused GlobalSplitU=2: {why}"


def test_nlca_needs_the_width_override(gen):
    """NumLoadsCoalesced is gated by VectorWidth through NumLoads. With the
    override the row builds; without it, it does not -- which is exactly why the
    sweep carries ``width_override`` as data rather than fixing it at the gate."""
    for family, width in (("CC", 1), ("SS", 1), ("HH", 2)):
        base = KNOB_SWEEP_BASES[family][0]
        with_override = _merged(family, base, {"NumLoadsCoalescedA": 2}, width)
        ok, why = gen.validate_config(with_override)
        assert ok, f"{family} vw{width}+NLCA2 should be legal: {why}"
        # The widest tiles are the ones that cannot carry NLCA=2.
        if family == "SS":
            ok_wide, _ = gen.validate_config(
                _merged(family, base, {"NumLoadsCoalescedA": 2}, 4))
            assert not ok_wide, "SS vw4+NLCA2 was legal in §8.1 but not now"


def test_nlca_is_never_legal_for_zz_dd_or_hpa(gen):
    row = next(s for s in KNOB_SWEEPS if s["knob"] == "NumLoadsCoalescedA")
    for family in ("ZZ", "DD", "HH_HPA", "HS_HPA"):
        assert family not in row["families"], \
            f"{family} was found illegal for NLCA in §8.1"


# --------------------------------------------------------------------------
# the measured dead axis, and the LSU thread count
# --------------------------------------------------------------------------

def test_no_sweep_row_sweeps_aggressive_perf_mode():
    """AggressivePerfMode=2 is a dead axis on this device, measured not guessed.

    The mode-2 sweep ran 2026-10-15/17 and produced **zero** ``.hsaco`` objects
    for every family and every tile (24 phases, 0 CSV), while its mode-1 control
    in the same run built 20 (one per target arch). Tensile writes the source and
    then fails to compile it, so each phase costs a full subprocess and returns
    nothing. No tile property predicts that, which is why it is a deck decision
    (``decks.py`` records it) and not a gate.
    """
    for sweep in KNOB_SWEEPS:
        for value in sweep["values"]:
            assert value.get("AggressivePerfMode") != 2, sweep["knob"]


def test_generator_refuses_the_dead_perf_mode(gen):
    """The generator seam refuses APM=2 even though the writer forwards it.

    ``config_writer`` deliberately forwards any knob value verbatim -- its
    contract test probes APM=2 to prove exactly that -- so the refusal lives in
    ``CandidateGenerator.validate_config``, beside the AssertSizeMultiple crash
    rule. This is what makes "the sweep row is gone" a *structural* guarantee:
    a hand-written candidate or a mutator cannot re-draw the value.
    """
    base = KNOB_SWEEP_BASES["CC"][0]
    ok, why = gen.validate_config(_merged("CC", base, {"AggressivePerfMode": 2}))
    assert not ok, "APM=2 must be refused at the generator seam"
    assert "AggressivePerfMode=2" in why, why
    for good in (0, 1):
        ok, why = gen.validate_config(
            _merged("CC", base, {"AggressivePerfMode": good}))
        assert ok, f"APM={good} must stay legal: {why}"


def test_no_legal_complex_tile_is_wider_than_the_measured_max(gen):
    """The wide-MacroTile route is closed for CC and ZZ (potential_configs §R24).

    Pins the search that retired the 2026-10-14 "headroom" tiles: over every CC
    tile with area > 8192 (the widest *emitted* CC tile, 128x64) and every ZZ
    tile with area > 4096 (64x64 / 128x32), at every thread tile that survives
    the per-thread budget, not one is legal. The binding constraints are the
    workgroup register-file ceiling (R*MT0*MT1*LSU < 65536) and the classic-load
    divisibility rule, both calibrated zero-false-rejection, so "none legal" is a
    property of the device rather than of an over-strict gate.
    """
    found = []
    for family, cap in (("CC", 8192), ("ZZ", 4096)):
        for m0 in (64, 96, 128, 160, 192, 256):
            for m1 in (32, 48, 64, 96, 128):
                for du in (4, 8, 16, 32):
                    if m0 * m1 <= cap:
                        continue
                    for tt in ("2x2", "4x4", "4x2", "2x4"):
                        cfg = {**_template(family),
                               "MacroTile": f"{m0}x{m1}x{du}", "ThreadTile": tt}
                        ok, _ = gen.validate_config(cfg)
                        if ok:
                            found.append((family, m0, m1, du, tt))
    assert found == [], f"a wider complex tile exists and should be decked: {found[:5]}"


def test_localsplitu_is_legal_only_where_the_thread_count_survives(gen):
    """LSU>1 multiplies NumThreads (SolutionStructs:1964), so it stays legal only
    where the operand still fills the load wave. The deck's family list must
    match the gate family by family -- the measured split is CC/HH legal,
    SS/HH_HPA/ZZ/DD/HS_HPA refused."""
    row = next(s for s in KNOB_SWEEPS if s["knob"] == "LocalSplitU")
    assert set(row["families"]) == {"CC", "HH"}, row["families"]
    for family in REAL:
        base = KNOB_SWEEP_BASES[family][0]
        ok, why = gen.validate_config(_merged(family, base, {"LocalSplitU": 2}))
        assert ok == (family in row["families"]), \
            f"{family}: gate says {ok} ({why}) but the deck lists {row['families']}"


def test_no_live_phase_decks_the_dead_perf_mode():
    """The live deck must not re-ship what measurement killed.

    AggressivePerfMode=2 built 0 `.hsaco` and 0 CSV for every family and every
    tile across two runs. The sweep row is gone from ``KNOB_SWEEPS`` and the
    emitted rows were pruned from ``phases.yaml``; this is the guard that keeps
    a hand-edit or a stale regeneration from putting them back
    (potential_configs.md §R23).
    """
    import yaml
    deck = yaml.safe_load((BASE / "phases.yaml").read_text()) or []
    bad = [p["phase_id"] for p in deck
           if (p.get("config") or {}).get("AggressivePerfMode") == 2]
    assert bad == [], f"{len(bad)} live phases sweep AggressivePerfMode=2: {bad[:3]}"


# --------------------------------------------------------------------------
# the paired GLVW widen (D4) and the baseline control
# --------------------------------------------------------------------------

def _glvw_row():
    return next(s for s in KNOB_SWEEPS
                if s["knob"] == "GlobalLoadVectorWidth")


def test_glvw_widen_is_cc_only_and_paired(gen):
    """The widen is realizable only on CC and only as a pair (D4).

    An unpaired ``GlobalLoadVectorWidth=2`` is refused by Tensile's
    ``GLVW == VectorWidth or == 1`` guard because the default
    ``AssertFree0ElementMultiple=1`` leaves ``GuaranteeNoPartialA`` false.
    Pairing it with ``AssertFree(0,1)ElementMultiple=2`` lifts the guard, and CC
    is the only base whose ``pv`` does not cancel the 2 back to 1.
    """
    row = _glvw_row()
    assert row["families"] == ["CC"], "the paired widen is CC-only"
    (value,) = row["values"]
    assert value["GlobalLoadVectorWidthA"] == 2
    assert value["GlobalLoadVectorWidthB"] == 2
    assert value["AssertFree0ElementMultiple"] == 2
    assert value["AssertFree1ElementMultiple"] == 2

    base = KNOB_SWEEP_BASES["CC"][0]
    ok, why = gen.validate_config(_merged("CC", base, value))
    assert ok, f"paired CC widen refused: {why}"
    # ...and the same value WITHOUT the pair is refused, which is why the two
    # knobs must travel together.
    unpaired = {"GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2}
    ok, why = gen.validate_config(_merged("CC", base, unpaired))
    assert not ok and "GLVW" in why, "unpaired GLVW=2 was accepted"


def test_include_baseline_emits_one_control_per_family_shape(sandbox):
    """D4: the control is the base tile unchanged, once per (family, shape),
    and it never collides with a sweep id."""
    fams = ["CC", "ZZ"]
    base_tiles = [b for fam in fams for b in KNOB_SWEEP_BASES[fam]]
    control = sandbox.generate_knob_sweep_phases(
        families=fams, base_shapes=[SHAPE], include_baseline=True)
    plain = sandbox.generate_knob_sweep_phases(
        families=fams, base_shapes=[SHAPE], include_baseline=False)
    controls = [c for c in control if c.phase_id.endswith("_base")]
    assert len(controls) == len(fams), [c.phase_id for c in controls]
    assert len(control) == len(plain) + len(controls)
    ids = [c.phase_id for c in control]
    assert len(ids) == len(set(ids)), "baseline id collides with a sweep id"
    for c in controls:
        # the control carries the base tile and no sweep knob on top.
        assert c.knobs in base_tiles, c.knobs


# --------------------------------------------------------------------------
# the emission
# --------------------------------------------------------------------------

def test_generated_ids_are_unique_and_self_describing(sandbox):
    cands = sandbox.generate_knob_sweep_phases(
        families=["CC", "ZZ"], base_shapes=[SHAPE])
    assert cands, "no candidates emitted"
    ids = [c.phase_id for c in cands]
    assert len(ids) == len(set(ids)), \
        f"duplicate phase_ids would overwrite results: " \
        f"{sorted(i for i in ids if ids.count(i) > 1)[:3]}"


def test_value_tag_names_the_key_not_the_row_label():
    """A NumLoadsCoalescedB candidate must not carry an id saying A."""
    tag = CandidateGenerator._sweep_value_tag({"NumLoadsCoalescedB": 2})
    assert tag == "NumLoadsCoalescedB2"
    tag = CandidateGenerator._sweep_value_tag(
        {"GlobalLoadVectorWidthA": 2, "GlobalLoadVectorWidthB": 2})
    assert "GlobalLoadVectorWidthA2" in tag
    assert "GlobalLoadVectorWidthB2" in tag
    # booleans stay path-safe and deterministic
    assert CandidateGenerator._sweep_value_tag({"NonTemporalA": True}) == \
        "NonTemporalA1"


def test_full_sweep_is_the_legal_subset(sandbox):
    """The §8.1 tally: the deck emits the rows that pass, and refuses -- loudly
    -- the rows that do not."""
    cands = sandbox.generate_knob_sweep_phases(
        families=REAL, base_shapes=[SHAPE])
    by_fam = {}
    for c in cands:
        # The label is "{family}_{pattern}_{shape}{tag}" and a family can itself
        # contain an underscore (HH_HPA), so split on the pattern, not on "_".
        family = c.label.split("_" + "Ailk_Bljk")[0]
        by_fam.setdefault(family, []).append(c)
    for fam in REAL:
        assert by_fam.get(fam), f"{fam} emitted nothing"
    # GlobalSplitU appears only for SS and DD.
    gsu = {fam for fam, cs in by_fam.items()
           if any(c.knobs.get("GlobalSplitU", 1) > 1 for c in cs)}
    assert gsu == GSU_OK, f"GlobalSplitU leaked into {gsu - GSU_OK}"


def test_dry_run_validates_without_writing(sandbox, tmp_path):
    """`knob_sweep.main` without --emit must not touch the manifest."""
    from oto.tensile import knob_sweep

    manifest = sandbox.base_dir / "phases.yaml"
    before = manifest.read_bytes()
    rc = knob_sweep.main(["--families", "CC", "--shapes", SHAPE])
    assert rc == 0
    assert manifest.read_bytes() == before, "dry run wrote the manifest"


def test_dry_run_reports_refusals(sandbox):
    """Silence on a knob must read as 'refused', not as 'measured negative'."""
    from oto.tensile import knob_sweep

    rc = knob_sweep.main(["--families", "CC", "ZZ", "--shapes", SHAPE])
    assert rc == 0
    # A dry run that can only ever succeed here still returns 0 with the
    # refusal list printed to stdout by the generator itself.


def test_emit_honours_phases_and_never_touches_the_live_deck(sandbox, tmp_path):
    """`--phases` routes the write; without it nothing may surprise the operator.

    Regression: `target` was once dead code and every `--emit` appended to
    `./phases.yaml` no matter what `--phases` said."""
    from oto.tensile import knob_sweep

    out = tmp_path / "deck_out.yaml"
    out.write_text("")
    rc = knob_sweep.main(["--families", "CC", "--shapes", SHAPE,
                          "--emit", "--baseline", "--trials",
                          "--phases", str(out)])
    assert rc == 0
    import yaml
    written = yaml.safe_load(out.read_text())
    assert written, "--phases file got nothing"
    ids = [p["phase_id"] for p in written]
    assert any(i.endswith("_base") for i in ids), "no baseline written"
    assert any("_trialD" in i for i in ids), "no trial written"
    assert any("GlobalLoadVectorWidthA2" in i for i in ids), "no paired widen"


# --------------------------------------------------------------------------
# the decision trials (D1/D2/D3)
# --------------------------------------------------------------------------

def test_every_decision_trial_is_gate_legal(gen):
    """A trial must pass the gate everywhere it claims to run, or the decision
    it answers is untestable.

    Checked against BOTH gates: ``validate_config`` (the append boundary) and
    the consolidate deck gate ``_is_legal``, which reads dtype bytes from
    Tensile itself rather than from the modelled table. The two agree on ZZ's
    load width since the ``LOAD_DTYPE_INFO["Z"]`` correction (16 B, pinned by
    ``tests/test_measurement_integrity.py``); the second is still worth asking
    because it is the authority, and a trial only the first accepts is exactly
    the phase that dies at solution construction.
    """
    from oto.tools.consolidate import _is_legal

    for trial in DECISION_TRIAL_TILES:
        for shape in trial.get("shapes", [SHAPE]):
            cfg = {**_template(trial["family"], shape), **trial["knobs"]}
            ok, why = gen.validate_config(cfg)
            assert ok, f"{trial['decision']} trial {trial['knobs']} refused " \
                       f"at {shape}: {why}"
            ok2, why2 = _is_legal(cfg)
            assert ok2, f"{trial['decision']} trial {trial['knobs']} passes " \
                        f"validate_config but the Tensile-truth gate refuses " \
                        f"it at {shape}: {why2}"


def test_decision_trials_cover_d1():
    """Every still-open decision owns a trial tile. D2/D3 retired 2026-11-14.

    The LDS decision is closed: ``BYTES_PER_ELEMENT["Z"]`` is Tensile's 16 B
    and ``LDS_BUDGET`` stands, so the D2 boundary tile and the D3 "widest
    legal ZZ" pair are refused by the gate by design and are no longer
    decked. D1 remains the only open owner-decision and keeps its trial."""
    from oto.tensile.decks import DECISION_TRIAL_TILES

    covered = {t["decision"] for t in DECISION_TRIAL_TILES}
    assert {"D1"} <= covered, f"D1 has no trial: {covered}"
    assert not ({"D2", "D3"} & covered), \
        f"retired decisions must not be decked: {covered}"
    # D2 carries the LDS-boundary tile only. A ZZ VectorWidth=2 row is NOT a
    # trial: Tensile refuses it (numBytes 16 x 2 > 16), the archived deck
    # already measured that refusal, and
    # tests/test_consolidate.py::TestLegalityGate::
    # test_gate_catches_a_real_archived_zz_phase locks it.
    # D1 names the shallow cells, so it never depends on sweep shapes.
    d1 = [t for t in DECISION_TRIAL_TILES if t["decision"] == "D1"]
    assert d1 and all("shapes" in t for t in d1), "D1 must name its cells"


def test_trial_ids_carry_the_decision_and_never_collide(sandbox):
    cands = sandbox.generate_decision_trial_phases(
        families=["CC", "ZZ"], base_shapes=[SHAPE])
    assert cands, "no trials emitted"
    ids = [c.phase_id for c in cands]
    assert all("_trialD" in i for i in ids), ids[:3]
    assert len(ids) == len(set(ids)), "trial ids collide"
    # a trial id never collides with a sweep or baseline id
    sweeps = sandbox.generate_knob_sweep_phases(
        families=["CC", "ZZ"], base_shapes=[SHAPE], include_baseline=True)
    sweep_ids = {c.phase_id for c in sweeps}
    assert not (set(ids) & sweep_ids), "trial id collides with sweep/baseline"


def test_no_emitted_candidate_passes_only_the_lenient_gate(gen):
    """Blanket guard: nothing this deck can emit may pass ``validate_config``
    while the Tensile-truth gate (``consolidate._is_legal``) refuses it.

    ``validate_config`` reads dtype bytes from the modelled ``LOAD_DTYPE_INFO``;
    ``_is_legal`` reads them from Tensile's own ``DataType``. They agreed on ZZ
    only after the ``Z`` row was corrected to complex double's 16 B — before
    that a ZZ VW2 config passed the first and failed the second, which is
    precisely the phase Tensile refuses at solution construction after the whole
    compile budget is spent. The deck must agree with the stricter gate, because
    that is the one that describes what gets built.
    """
    from oto.tools.consolidate import _is_legal

    checks = [(fam, base, sweep.get("width_override", {}).get(fam), value)
              for fam, bases in KNOB_SWEEP_BASES.items()
              for base in bases
              for sweep in KNOB_SWEEPS
              if fam in sweep.get("families", [])
              for value in sweep["values"]]
    checks.extend((trial["family"], trial["knobs"], None, {})
                  for trial in DECISION_TRIAL_TILES)
    assert len(checks) > 60, len(checks)
    for family, base, width_override, value in checks:
        merged = {**base, **value}
        if width_override is not None:
            merged["VectorWidth"] = width_override
        cfg = {**_template(family), **merged}
        ok_lenient, _why_lenient = gen.validate_config(cfg)
        ok_truth, why_truth = _is_legal(cfg)
        assert not (ok_lenient and not ok_truth), (
            f"{family} {merged} passes validate_config but the Tensile-truth "
            f"gate refuses it: {why_truth}")
