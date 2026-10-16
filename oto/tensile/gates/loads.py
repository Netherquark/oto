"""Classic-path global-load divisibility, and the 16 B load-width cap.

Owns: ``validate_tensile_loads`` (a faithful port of Tensile SolutionStructs'
``setGlobalLoadVectorWidth`` + ``setGlobalLoadTileDimClassic`` for the non-MI,
FractionalLoad=False, Assembly kernel path) and ``cap_vector_width`` (the
highest VectorWidth that still reaches the 16 B global-load cap).
Does NOT own: the register-file/LDS model (oto.tensile.gates.occupancy), the
GEMM class rules (oto.tensile.gates.assembly), or the tiles of a candidate
(oto.tensile.candidate).

Every rejection cites the SolutionStructs line it mirrors. That is deliberate:
these rejects read as arbitrary arithmetic ("totalVectorsCoalesced % NLCA != 0")
unless the operator can see which Tensile branch produced them.
Public API: validate_tensile_loads, cap_vector_width, LOAD_DTYPE_INFO.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Tuple

from .vgpr_model import (FAMILY_BYTES_PER_ELEMENT, GLOBAL_LOAD_BYTE_CAP,
                         knob_int)

#: Tensile DataType properties the classic path reads, in the units
#: SolutionStructs uses (``reg`` is registers per element, not bytes).
LOAD_DTYPE_INFO = {
    "S":  {"reg": 1,    "bytes": 4,  "isHalf": False, "isInt8": False},
    "D":  {"reg": 2,    "bytes": 8,  "isHalf": False, "isInt8": False},
    "H":  {"reg": 0.5,  "bytes": 2,  "isHalf": True,  "isInt8": False},
    "B":  {"reg": 0.5,  "bytes": 2,  "isHalf": False, "isInt8": False},
    "Z":  {"reg": 2,    "bytes": 8,  "isHalf": False, "isInt8": False},
    "C":  {"reg": 2,    "bytes": 8,  "isHalf": False, "isInt8": False},
    "I8": {"reg": 0.25, "bytes": 1,  "isHalf": False, "isInt8": True},
}

#: Family label -> Tensile DataType char, because the caller may hold either.
_FAMILY_TO_CHAR = {"SS": "S", "DD": "D", "HH": "H", "ZZ": "Z", "CC": "C",
                   "FF": "S"}


# ---------------------------------------------------------------- readers

def _load_dtype_info(config: Dict[str, Any]) -> Dict[str, Any]:
    """LOAD_DTYPE_INFO row for the config's DataType (S fallback)."""
    dtype_char = str(config.get("DataType", config.get("dtype", "S"))).upper()
    dtype_char = _FAMILY_TO_CHAR.get(dtype_char, dtype_char)
    return LOAD_DTYPE_INFO.get(dtype_char, LOAD_DTYPE_INFO["S"])


def _load_geometry(config: Dict[str, Any]) -> Optional[Tuple[int, int, int, int, int]]:
    """(mt0, mt1, DepthU, tt0, tt1) from a config, or None when unusable.

    Why None is legal input: a config that does not name a tile is not this
    gate's business, and the caller treats it as "nothing to check".
    """
    mt_clean = (str(config.get("MacroTile", "64x64x64")).upper()
                .replace("MT", "").replace("SB_", "")
                .replace("HB_", "").replace("DB_", ""))
    mt_parts = [int(x) for x in re.split(r'[xX]', mt_clean)]
    if len(mt_parts) < 2:
        return None
    depthU = knob_int(config.get("DepthU"), mt_parts[2] if len(mt_parts) >= 3 else 16)
    tt_parts = [int(x) for x in re.split(
        r'[xX]', str(config.get("ThreadTile", "4x4")).lower().replace("_", "x"))]
    if len(tt_parts) < 2:
        return None
    tt0, tt1 = tt_parts[0], tt_parts[1]
    if tt0 <= 0 or tt1 <= 0:
        return None
    return mt_parts[0], mt_parts[1], depthU, tt0, tt1


def _vector_width(config: Dict[str, Any], tt0: int, tt1: int,
                   dtype: Dict[str, Any]) -> int:
    """VectorWidth: the user's, else Tensile's default halved until the thread
    tile is divisible by it (SolutionStructs:3435-3443)."""
    vw_user = config.get("VectorWidth")
    if vw_user is None or int(vw_user) < 1:
        vw = int(4.0 / dtype["reg"])
        while (tt0 % vw != 0 or tt1 % vw != 0) and vw > 1:
            vw //= 2
    else:
        vw = int(vw_user)
    return vw


def _glvw_for(config: Dict[str, Any], tc: str, default: int) -> int:
    """The GlobalLoadVectorWidth Tensile actually uses for operand ``tc``.

    An explicit ``GlobalLoadVectorWidthA``/``B`` is honoured verbatim: Tensile
    passes it into ``setGlobalLoadVectorWidth`` as ``grvw``
    (SolutionStructs:2010). Only ``-1`` (the "= VectorWidth" default) and ``0``
    mean "derive it". This gate used to model the *derived* width only, so a
    config that set ``GlobalLoadVectorWidth=2`` on a ``VectorWidth=4`` tile
    passed here and was then refused by Tensile -- "GlobalLoadVectorWidthA 2 must
    be == VectorWidth 4 or == 1" (SolutionStructs:4584-4596). Real refuses of
    exactly that shape are the reference-rerun hashes ``7f866dcf`` / ``a0edeb30``
    (tests/test_reference_tiers.py).

    Args:
        config: A Tensile solution dict.
        tc: Operand, ``"A"`` or ``"B"``.
        default: The derived width to fall back to (``max(VW, numElemPerReg)``).

    Returns:
        The width Tensile will use: the explicit value, else ``default``.
    """
    raw = config.get(f"GlobalLoadVectorWidth{tc}")
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return default if value <= 0 else value


def _transposes(config: Dict[str, Any]) -> Tuple[bool, bool]:
    """(TLUA, TLUB) from the contraction pattern or the label.

    ``Ailk``/``Bjlk`` is the "contiguous-in-k for that operand" form; a config
    that names neither falls back to the NT default.
    """
    pattern = str(config.get("ContractionPattern", config.get("label", "Ailk_Bjlk")))
    return "Ailk" in pattern, "Bjlk" in pattern


def _nlca_for(config: Dict[str, Any], tc: str) -> int:
    """NumLoadsCoalesced for one operand, honouring the shared NLCA alias."""
    value = config.get(f"NumLoadsCoalesced{tc}", config.get("NLCA", 1))
    return knob_int(value, 1)


# --------------------------------------------------------------- per-operand

class _Operand:
    """One operand's derived load shape, exactly as SolutionStructs computes it.

    All five gates below read the same numbers (``totalElements``,
    ``NumThreads*glvw``, ``numLoads``, ``pv``), so they are computed once here
    instead of being restated -- and cannot disagree with each other -- in each
    branch.
    """

    def __init__(self, tc: str, mt_tc: int, depth_u: int, num_threads: int,
                 glvw: int, vw: int, tlu: bool, config: Dict[str, Any]):
        self.tc = tc
        self.mt_tc = mt_tc
        self.depth_u = depth_u
        self.num_threads = num_threads
        self.glvw = glvw
        self.vw = vw
        self.tlu = tlu
        self._config = config

    @property
    def total_elements_coalesced(self) -> int:
        return self.mt_tc if self.tlu else self.depth_u

    @property
    def total_elements_perp(self) -> int:
        return self.depth_u if self.tlu else self.mt_tc

    @property
    def total_elements(self) -> int:
        return self.total_elements_coalesced * self.total_elements_perp

    @property
    def num_thread_grtw(self) -> int:
        return self.num_threads * self.glvw

    @property
    def total_vectors_coalesced(self) -> int:
        return self.total_elements_coalesced // self.glvw

    @property
    def _pv(self) -> int:
        """Partial-vector factor: how many waves one element-set spans."""
        if self.total_elements >= self.num_thread_grtw:
            return 1
        return self.num_thread_grtw // self.total_elements

    @property
    def _num_loads(self) -> int:
        if self.total_elements < self.num_thread_grtw:
            return self.total_elements // (self.num_thread_grtw // self._pv)
        return self.total_elements // self.num_thread_grtw

    def _pv_stage(self) -> Optional[str]:
        """Divisibility when the operand is smaller than one full load wave."""
        if self.total_elements >= self.num_thread_grtw:
            return None
        if self.num_thread_grtw % self.total_elements != 0:
            return (f"{self.tc}: (NumThreads*glvw)={self.num_thread_grtw} % "
                    f"totalElements={self.total_elements} != 0")
        pv = self._pv
        if pv * self.total_elements != self.num_thread_grtw:
            return (f"{self.tc}: pv={pv} * totalElements={self.total_elements} "
                    f"!= numThreadGrvw={self.num_thread_grtw}")
        if self.glvw < 1 or self.glvw % pv != 0:
            return f"{self.tc}: GLVW={self.glvw} % pv={pv} != 0"
        return None

    def _whole_stage(self) -> Optional[str]:
        """Divisibility when the operand is a whole number of load waves."""
        if self.total_elements < self.num_thread_grtw:
            return None
        if self.total_elements % self.num_thread_grtw != 0:
            return (f"{self.tc}: totalElements={self.total_elements} % "
                    f"(NumThreads*glvw)={self.num_thread_grtw} != 0")
        return None

    def _shift_ptr_stage(self) -> Optional[str]:
        """GLVW==VW-or-1: post-pv-reduction shift-ptr guard
        (SolutionStructs:4583-4596). Only fires when the solution cannot
        guarantee the wide load is whole -- see ``_restriction_active``."""
        glvw_eff = self.glvw // self._pv
        if (glvw_eff > 1 and glvw_eff != self.vw
                and self._restriction_active(glvw_eff)):
            return (f"{self.tc}: GLVW={glvw_eff} must be == VectorWidth "
                    f"{self.vw} or == 1")
        return None

    @property
    def buffer_load(self) -> bool:
        """Tensile's local ``bufferLoad`` (SolutionStructs:3292).

        True only for an Assembly kernel with ``BufferLoad`` on. The project's
        ``config_writer`` always writes ``KernelLanguage: Assembly`` and
        ``BufferLoad`` defaults True, so this is the state every deck phase is
        built in -- but it is read, not assumed, so a ``Source`` or
        ``BufferLoad=0`` config still takes the stricter branch.
        """
        language = str(self._config.get("KernelLanguage", "Assembly"))
        return (bool(self._config.get("BufferLoad", True))
                and language == "Assembly")

    def _restriction_active(self, glvw_eff: int) -> bool:
        """``not bufferLoad or not GuaranteeNoPartial`` (SolutionStructs:4584).

        ``GuaranteeNoPartialX`` is ``AssertFree0/1ElementMultiple % GLVW_X == 0``
        when that operand is TLU and True otherwise (SolutionStructs:4177-4183).
        So a tile that asserts the free dimension is a multiple of the wide load
        -- e.g. ``AssertFree0ElementMultiple=2`` beside ``GLVW=2`` -- legitimately
        lifts the restriction, which is why the gate must not apply it blindly.
        """
        if not self.buffer_load:
            return True
        if not self.tlu:
            return False
        knob = ("AssertFree0ElementMultiple" if self.tc == "A"
                else "AssertFree1ElementMultiple")
        return int(self._config.get(knob, 1)) % glvw_eff != 0

    def _nlca_stage(self, nlca: int) -> Optional[str]:
        """NumLoadsCoalesced legality (SolutionStructs:2058)."""
        numLoads = self._num_loads
        tvc = self.total_vectors_coalesced
        perp = self.total_elements_perp

        def satisfied(n: int) -> bool:
            nlp = numLoads // n
            return (numLoads % n == 0 and tvc % n == 0
                    and perp % nlp == 0)

        if nlca == 1:
            if any(satisfied(n) for n in range(1, numLoads + 1)):
                return None
            return f"{self.tc}: No valid NumLoadsCoalesced=1 found"
        if nlca == -1:
            if any(satisfied(n) for n in range(numLoads, 0, -1)):
                return None
            return f"{self.tc}: No valid NumLoadsCoalesced=-1 found"
        if nlca > numLoads:
            return f"{self.tc}: NLCA={nlca} > NumLoads={numLoads}"
        nlp = numLoads // nlca
        if numLoads % nlca != 0:
            return f"{self.tc}: NumLoads={numLoads} % NLCA={nlca} != 0"
        if tvc % nlca != 0:
            return f"{self.tc}: totalVectorsCoalesced={tvc} % NLCA={nlca} != 0"
        if perp % nlp != 0:
            return (f"{self.tc}: totalElementsPerp={perp} % "
                    f"NumLoadsPerp={nlp} != 0")
        return None

    def _depth_stage(self) -> Optional[str]:
        """depthU >= GLVW when !TLU (SolutionStructs:3793)."""
        if not self.tlu and self.depth_u < self.glvw:
            return (f"{self.tc}: depthU={self.depth_u} < "
                    f"GLVW={self.glvw} (TLU=False)")
        return None

    def rejection(self) -> Optional[str]:
        """The first reason this operand's classic load is illegal, if any.

        NLCA is parsed here, not at construction, because the pre-split gate read
        it in the middle of the per-operand loop: a config that fails an earlier
        stage with an unparsable NLCA reports that earlier reason rather than
        raising on the garbage value.
        """
        for stage in (self._pv_stage, self._whole_stage,
                      self._shift_ptr_stage):
            reason = stage()
            if reason:
                return reason
        reason = self._nlca_stage(_nlca_for(self._config, self.tc))
        if reason:
            return reason
        return self._depth_stage()


# -------------------------------------------------------------- public API

def cap_vector_width(family: str, macro_tile: str, thread_tile: str) -> int:
    """Widest VectorWidth that still reaches the 16 B global-load cap.

    A tile only converts load width into throughput once the contiguous load is
    actually 16 B. Every large-cell loss in the corpus had a legal but
    *under-wide* winner, because the family decks hardcoded one step below this.

    Three bounds apply, and this returns the largest power of two satisfying all
    of them, so the result is a legal upper bound rather than a hopeful one:

      1. `VW * bytesPerElement <= 16` -- the global-load byte cap
         (Tensile SolutionStructs:3460).
      2. `VW <= MT0/TT0` and `VW <= MT1/TT1` -- the load must be contiguous
         inside a thread's own extent of the tile.
      3. `TT0 % VW == 0` and `TT1 % VW == 0` -- Tensile rejects a thread tile
         that is not a multiple of the vector width
         (``validate_tensile_loads``, mirroring
         SolutionStructs.setGlobalLoadVectorWidth).

    Why bound 3 exists: it is not a corner case, it is exactly the
    non-power-of-two thread tiles this device uses most (SS 96x96x16/6x6,
    HH 64x64x16/4x4). Without it the cap claimed 4 and 8 for tiles where Tensile
    accepts only 2 and 4, and the generator emitted phases that died at config
    fill.

    Args:
        family: Family label (``SS``/``HH``/...), used for the bytes-per-element
            bound.
        macro_tile: MacroTile string, e.g. ``"128x128x8"``.
        thread_tile: ThreadTile string, e.g. ``"8x8"``.

    Returns:
        The widest legal VectorWidth (>= 1), or 0 when the family is unknown.
    """
    bpe = FAMILY_BYTES_PER_ELEMENT.get(family.upper())
    if not bpe:
        return 0
    limit = GLOBAL_LOAD_BYTE_CAP // bpe
    parts = [int(x) for x in str(macro_tile).split("x") if x.strip().isdigit()]
    tt = [int(x) for x in str(thread_tile).split("x") if x.strip().isdigit()]
    if len(parts) >= 2 and len(tt) == 2 and min(tt) > 0:
        limit = min(limit, parts[0] // tt[0], parts[1] // tt[1])
        # Bound 3: the thread tile must tile evenly at the vector width.
        vw = 1
        while vw * 2 <= limit and (tt[0] % (vw * 2) == 0) and (tt[1] % (vw * 2) == 0):
            vw *= 2
        return vw
    vw = 1
    while vw * 2 <= limit:
        vw *= 2
    return vw


def validate_tensile_loads(config: Dict[str, Any]) -> Tuple[bool, str]:
    """Faithful port of Tensile classic-path divisibility.

    Only covers non-MI, FractionalLoad=False, Assembly kernel path -- which is
    the only path gfx90c can take (no MFMA on this device).

    Args:
        config: A Tensile solution dict.

    Returns:
        ``(True, "")`` when every operand's classic-path load is legal, else
        ``(False, reason)`` naming the operand (A/B) and the branch that failed.
    """
    geom = _load_geometry(config)
    if geom is None:
        return True, ""
    mt0, mt1, depth_u, tt0, tt1 = geom
    num_threads = (mt0 // tt0) * (mt1 // tt1)

    dtype = _load_dtype_info(config)
    vw = _vector_width(config, tt0, tt1, dtype)
    if vw < 1:
        return True, ""

    # TT must be multiples of VW (SolutionStructs:3413)
    if tt0 % vw != 0 or tt1 % vw != 0:
        return False, f"TT0={tt0} or TT1={tt1} not multiple of VW={vw}"

    # Half requires VW >= 2 (SolutionStructs:3435)
    if dtype["isHalf"] and vw < 2:
        return False, "VW must be >= 2 for half"

    # GLVW default: max(VW, numElemPerReg) for assembly (SolutionStructs:3451);
    # an explicit GlobalLoadVectorWidthA/B overrides it per operand (_glvw_for).
    numElemPerReg = math.ceil(1.0 / dtype["reg"]) if dtype["reg"] > 0 else 1
    glvw_default = max(vw, numElemPerReg)

    tlu_a, tlu_b = _transposes(config)
    for tc, mt_tc, tlu in (("A", mt0, tlu_a), ("B", mt1, tlu_b)):
        glvw = _glvw_for(config, tc, glvw_default)
        # GLVW * bpe <= 16 (SolutionStructs:3460)
        if glvw * dtype["bytes"] > 16:
            return False, f"GLVW{tc} {glvw} * bpe {dtype['bytes']} > 16"
        operand = _Operand(tc, mt_tc, depth_u, num_threads, glvw, vw, tlu, config)
        reason = operand.rejection()
        if reason:
            return False, reason
    return True, ""
