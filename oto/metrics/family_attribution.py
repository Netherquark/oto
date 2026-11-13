#!/usr/bin/env python3
"""Cell/family attribution: which family a measurement row belongs to.

Owns: ``extract_family_from_phase_id`` (family from a phase id),
``resolve_cell_family`` (the anti-contamination resolver that prefers the kernel
typecode over any phase-level stamp), ``_hpa_variant``, ``FAMILY_TO_DTYPE`` and
the known-family constants.
Does NOT own: the CSV load that produces the rows (oto.metrics.analytics) or the
A/B comparison that consumes the attribution (oto.metrics.ab_audit).
Public API: extract_family_from_phase_id, resolve_cell_family, FAMILY_TO_DTYPE.
"""

from __future__ import annotations

from typing import Any

from oto.device.peaks import (
    DTYPE_TO_FAMILY,
    FAMILY_DTYPE_CHAR,
    family_from_kernel_name,
    kernel_typecode,
)

CLOCK_MIN_COVERAGE = 0.5


# Family prefix -> Tensile DataType char (lowercase keys for phase_id parsing).
FAMILY_TO_DTYPE = {
    k.lower(): v for k, v in FAMILY_DTYPE_CHAR.items()
}


# Known family prefixes (longest first for greedy matching).
# Note: family tokens are matched against lowercase phase_id segments, so the
# prefix set must be lowercase regardless of the canonical FAMILY_DTYPE_CHAR.
_KNOWN_FAMILIES = sorted(FAMILY_TO_DTYPE.keys(), key=len, reverse=True)


def extract_family_from_phase_id(phase_id: str) -> str:
    """Extract multi-letter family key from a phase_id (e.g. 'phase_hh_hpa_...' → 'hh_hpa').

    Matches the longest known family token sequence anywhere on a token boundary,
    so prefix tokens (e.g. 'draft_SS_...', 'draft_HH_HPA_...') still resolve.

    Last resort: a bare single-letter dtype token ('phase_auto_0_S_256...'),
    mapped through FAMILY_DTYPE_CHAR ('S' -> 'ss'). 'auto'/'phase' namespace
    tokens never count as families.
    """
    parts = [p for p in str(phase_id).replace('phase_', '').replace('phase', '').split('_') if p]
    best = ''
    best_len = 0
    for fam in sorted(_KNOWN_FAMILIES, key=len, reverse=True):
        fam_tokens = fam.split('_')
        if len(fam_tokens) <= best_len:
            continue
        for i in range(len(parts) - len(fam_tokens) + 1):
            if parts[i:i + len(fam_tokens)] == fam_tokens:
                best = fam
                best_len = len(fam_tokens)
                break
    if not best:
        for tok in parts:
            fam = DTYPE_TO_FAMILY.get(tok.upper(), "")
            if fam:
                return fam.lower()
    return best


# Canonical cell families (upper-case, HPA variants separate).
_KNOWN_CELL_FAMILIES = ("SS", "DD", "HH", "CC", "ZZ", "HH_HPA", "HS_HPA")


def _hpa_variant(stamp: str) -> bool:
    """True when a family stamp is an HPA variant ('HH_HPA'/'HS_HPA').

    HPA cells are distinguished by their explicit FamilyLabel/config stamp, and
    by nothing else — their kernel typecode reads 'HH' (leading 'H'), which is
    why typecode resolution must never collapse them into HH.
    """
    return str(stamp).upper().endswith("_HPA")


#: (stamp, typecode, resolved) contamination classes already reported. One line
#: per class, not one per record: the legacy phase_auto_0_{S,Z}_* pool holds
#: thousands of rows stamped 'Z' whose kernels are SB, and a per-record warning
#: turns every A/B load into 100+ identical lines.
_CONTAMINATION_SEEN: set = set()


def _warn_contamination(stamp: str, typecode: str, resolved: str,
                        phase_id: str) -> None:
    key = (stamp, typecode, resolved)
    if key in _CONTAMINATION_SEEN:
        return
    _CONTAMINATION_SEEN.add(key)


def resolve_cell_family(rec: dict[str, Any]) -> str:
    """Cell (family) attribution for one benchmark record — the anti-contamination resolver.

    Precedence (first hit wins), per the §13.2 typecode-filter rule:

      1. kernel typecode of the record's own kernel name (``kernel`` / ``fp`` /
         ``phase_id`` fallback): SB/DB/HB/CB/ZB + HHS/HSS -> family. This is the
         ground truth of what the kernel actually computes, and overrides a
         lying or missing phase-level stamp — the vector that put
         ``phase_auto_1_hh_1024x1024x1024_3`` into the SS:1024 cell was exactly
         a phase_id text ('auto' prefix) overriding the kernel's real family.
      2. the record's explicit ``family`` stamp, UNLESS it contradicts (1);
         HPA stamps are always kept (see _hpa_variant).
      3. family parsed from ``phase_id``.
      4. DataType char via DTYPE_TO_FAMILY.
      5. '' (record is unattributable; callers skip it).
    """
    kernel_name = str(rec.get("kernel") or rec.get("kernel_name")
                      or rec.get("fingerprint") or rec.get("fp") or "")
    tcode_fam = family_from_kernel_name(kernel_name)
    stamp = str(rec.get("family") or rec.get("cell_key", "").split(":")[0] or "").upper()

    if stamp in _KNOWN_CELL_FAMILIES and _hpa_variant(stamp):
        return stamp

    if tcode_fam:
        if stamp in _KNOWN_CELL_FAMILIES and stamp != tcode_fam:
            _warn_contamination(stamp, kernel_typecode(kernel_name), tcode_fam,
                                str(rec.get("phase_id", "")))
            return tcode_fam
        return tcode_fam

    if stamp in _KNOWN_CELL_FAMILIES:
        return stamp

    fam = extract_family_from_phase_id(str(rec.get("phase_id", ""))).upper()
    if fam in _KNOWN_CELL_FAMILIES:
        return fam

    fam = DTYPE_TO_FAMILY.get(str(rec.get("DataType") or rec.get("dtype") or "").upper(), "")
    return fam if fam in _KNOWN_CELL_FAMILIES else ""

