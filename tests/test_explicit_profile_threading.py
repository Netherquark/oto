"""End-to-end explicit-profile threading (C2.5-C2.9).

Passing ``profile=`` kwargs through the public seams must produce the
*receiving* profile's verdicts, not the ambient one -- the explicit path is
API, not decoration. Complements ``test_profile_gates.py`` (ambient/bound
profile) with the per-call explicit argument.
"""

import dataclasses

from oto.device.loader import load_profile
from oto.metrics.family_attribution import family_to_dtype
from oto.tensile.candidate import CandidateGenerator
from oto.tensile.gates.assembly import assembly_class_valid


def _mfma_synthetic():
    base = load_profile("gfx90c")
    return dataclasses.replace(base, codename="synthetictest", isa=(9, 9, 99),
                               num_cus=64, max_clock_mhz=1500, has_mfma=True)


def _cc_gsu_config():
    return {"DataType": "C", "FamilyLabel": "CC",
            "MacroTile": "64x64x8", "ThreadTile": "4x4", "VectorWidth": 1,
            "DepthU": 8, "GlobalSplitU": 2}


def test_assembly_gate_honors_explicit_profile():
    cfg = _cc_gsu_config()
    base = load_profile("gfx90c")
    synth = _mfma_synthetic()
    ok_gfx, why_gfx = assembly_class_valid(cfg, profile=base)
    ok_synth, _ = assembly_class_valid(cfg, profile=synth)
    assert ok_gfx is False
    assert "complex" in why_gfx.lower()
    assert "gfx90c" in why_gfx  # reason names the device that refused
    assert ok_synth is True


def test_validate_config_threads_explicit_profile_into_gates():
    """validate_config must hand the explicit profile to every gate it calls."""
    cfg = _cc_gsu_config()
    gen = CandidateGenerator(".")
    _, why_gfx = gen.validate_config(cfg, profile=load_profile("gfx90c"))
    _, why_synth = gen.validate_config(cfg, profile=_mfma_synthetic())
    assert "complex" in why_gfx.lower()
    # The MFMA-capable synthetic device reaches a later (or no) refusal: the
    # complex GSU>1 rule no longer fires.
    assert "complex" not in why_synth.lower()


def test_family_to_dtype_reads_explicit_profile():
    base = load_profile("gfx90c")
    synth = dataclasses.replace(base, codename="synthetictest",
                                family_dtype_char={**base.family_dtype_char, "SS": "B"})
    assert family_to_dtype(synth)["ss"] == "B"
    assert family_to_dtype(base)["ss"] == "S"
