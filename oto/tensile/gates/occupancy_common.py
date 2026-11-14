"""Shared occupancy-gate vocabulary.

Owns: ``tile_dims`` (MacroTile/ThreadTile parse) and ``dtype_char``
(dtype resolution, failing closed with "") -- the two helpers the occupancy
gate, the LdsPad gate and their callers all read. Separated so neither gate
module imports the other. Read-only helpers; the gate logic lives with the
gates.
Does NOT own: the gate verdicts (``oto.tensile.gates.occupancy`` /
``ldspad_gate``) or the profile (``oto.device.loader``).
Public API: tile_dims, dtype_char.
"""

from __future__ import annotations

import re
from typing import Any


def tile_dims(config: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """(MT0, MT1, TT0, TT1) from MacroTile/ThreadTile, or None if unusable.

    Args:
        config: A Tensile solution dict.

    Returns:
        The four dims, or None when either key is absent, unparsable or
        non-positive. Callers treat None as "cannot model" and fail closed.
    """
    mt_raw = config.get("MacroTile")
    tt_raw = config.get("ThreadTile")
    if not mt_raw or not tt_raw:
        return None
    mt_clean = str(mt_raw).upper().replace("MT", "").replace("SB_", "").replace("HB_", "").replace("DB_", "")
    tt_clean = str(tt_raw).lower().replace("_", "x")
    try:
        mt_parts = [int(x) for x in re.split(r'[xX]', mt_clean)]
        tt_parts = [int(x) for x in re.split(r'[xX]', tt_clean)]
    except ValueError:
        return None
    if len(mt_parts) < 2 or len(tt_parts) < 2:
        return None
    if mt_parts[0] <= 0 or mt_parts[1] <= 0 or tt_parts[0] <= 0 or tt_parts[1] <= 0:
        return None
    return mt_parts[0], mt_parts[1], tt_parts[0], tt_parts[1]


def dtype_char(config: dict[str, Any]) -> str:
    """Dtype char for a config, or "" when it cannot be determined.

    Why: a wrong guess would pick the wrong VGPR weight (Z is 8, S is 1) and
    silently admit a config the gate must reject, so an unknown dtype fails
    closed with "".

    Args:
        config: A Tensile solution dict carrying ``DataType``/``dtype`` or a
            ``FamilyLabel``/``family_label``.

    Returns:
        The canonical dtype char (S/D/H/B/I8/C/Z), or "" when unreadable.
    """
    raw = config.get("DataType", config.get("dtype"))
    if raw is None:
        # Label-only configs exist in the auto-generated phases; the label
        # carries the same information, so resolve through it rather than
        # failing closed on a config whose dtype is knowable.
        raw = config.get("FamilyLabel", config.get("family_label"))
    if raw is None:
        return ""
    ch = str(raw).upper()
    # HPA families carry the base dtype in their label: HH_HPA is f16 pairs
    # (weight 1) and HS_HPA is f32 pairs (weight 1). Without these, a
    # label-only HPA config cannot be modelled and the register-file gate fails
    # it closed -- which silently removes the entire HPA deck from generation.
    return {
        "SS": "S", "DD": "D", "HH": "H", "ZZ": "Z", "CC": "C", "FF": "S",
        "HH_HPA": "H", "HS_HPA": "S",
    }.get(ch, ch)


