#!/usr/bin/env python3
"""A/B record identity: how the two arms are made comparable.

Owns: ``norm_config`` / ``_norm_macro_tile`` (canonical config identity that
survives whichever way Tensile happened to write a tile), ``_pair_key`` (the
identity used to pair a native record with a floor record), ``_resolved_config``
(reading a phase's config out of its own resolved 2_BenchmarkData YAML), and
``_driver`` (the read-only driver both arms are read through).
Does NOT own: the band measured from the pairing (oto.metrics.ab_band) or the
audit that grades it (oto.metrics.ab_audit).
Public API: AbIdentityMixin.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from oto import yaml_cached as yamlio

#: The project root, resolved from this module's location.
BASE = Path(__file__).resolve().parents[2]

#: A contraction pattern captured out of a kernel name.
_CP_RE = re.compile(r"Cijk_(.+?)_(?:SB|CB)_")


class AbIdentityMixin:
    """Config identity and arm pairing, mixed into the audit module."""


def _driver(base: Path = BASE):
    """Driver for reading only.

    ``create_run=False`` is essential and not optional: TensileDriver's default
    constructor registers a run row and creates a run directory, so an audit tool
    that instantiates it normally writes to the corpus it is auditing. That
    happened -- 19 empty 'interrupted' runs accumulated in registry.db before
    this was caught.
    """
    from oto.runners.driver import TensileDriver
    return TensileDriver(base_dir=base, create_run=False)


def _resolved_config(phase_dir: Path) -> dict[str, Any]:
    """Merge the config out of a phase's own resolved ``2_BenchmarkData/*.yaml``.

    Tensile writes that file as a list of documents -- a version stamp, a
    ProblemSizes list, then the solution config -- so the config is the entry
    carrying ``MacroTile``. Reading it here is what lets floor phases, which are
    absent from ``phases.yaml``, be paired against native phases on real config
    identity instead of on the solution name alone.
    """
    out: dict[str, Any] = {}
    for yml in sorted(phase_dir.glob("*.yaml")):
        try:
            doc = yamlio.load_yaml_text(yml.read_text(errors="ignore"))
        except Exception:
            continue
        entries = doc if isinstance(doc, list) else [doc]
        for entry in entries:
            if isinstance(entry, dict) and "MacroTile" in entry:
                out.update(entry)
    return out


_CP_RE = re.compile(r"Cijk_(.+?)_(?:SB|CB)_")

def _norm_macro_tile(cfg: dict[str, Any]) -> str:
    """MacroTile as 'MxNxDU' whichever way Tensile wrote it.

    Native phases write ``MacroTile: 128x128x16`` (depth folded in); floor
    phases write ``MacroTile: [128, 64]`` with a separate ``DepthU``. Comparing
    those two spellings directly is how a config comes to look unmatched to
    itself.
    """
    mt = cfg.get("MacroTile")
    if isinstance(mt, (list, tuple)):
        parts = [str(x) for x in mt]
    elif mt:
        parts = str(mt).split("x")
    else:
        parts = [str(cfg.get("MT0", "")), str(cfg.get("MT1", ""))]
    depth = cfg.get("DepthU")
    if len(parts) >= 3 and parts[2]:
        depth = parts[2] if depth is None else depth
        parts = parts[:2]
    return f"{parts[0] if parts else ''}x{parts[1] if len(parts) > 1 else ''}x{depth if depth is not None else ''}"


def norm_config(cfg: dict[str, Any], fingerprint: str = "") -> str:
    """Canonical config identity, comparable across the two arms.

    Built from resolved-Tensile knobs rather than the solution name because the
    solution name omits knobs that change the config (``WorkGroupMapping`` and
    ``GlobalSplitU`` variants emit the same ``Cijk_*`` name), and pairing on it
    would report two different kernels as one.
    """
    cfg = cfg or {}
    cp = cfg.get("ContractionPattern") or cfg.get("contraction_pattern") or ""
    if not cp:
        m = _CP_RE.search(fingerprint or "")
        cp = m.group(1) if m else ""
    tt = cfg.get("ThreadTile")
    tt = "x".join(str(x) for x in tt) if isinstance(tt, (list, tuple)) else \
        (str(tt) if tt else f"{cfg.get('TT0', '')}x{cfg.get('TT1', '')}")
    return "|".join((
        f"CP={cp}",
        f"MT={_norm_macro_tile(cfg)}",
        f"TT={tt}",
        f"VW={cfg.get('VectorWidth')}",
        f"GSU={cfg.get('GlobalSplitU')}",
        f"WGM={cfg.get('WorkGroupMapping')}",
    ))


def _pair_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    """Identity used to pair a native record with a floor record."""
    return (rec.get("DataType") or rec.get("dtype") or "",
            rec.get("ProblemType") or rec.get("shape") or "",
            rec.get("norm_config") or norm_config(rec.get("config") or {},
                                                  rec.get("fingerprint", "")))
