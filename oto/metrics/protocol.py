#!/usr/bin/env python3
"""Measurement-protocol classification: the like-for-like rule, in one place.

Owns: the invocation-form vocabulary and its classifier. A measurement's
*protocol* is how wide the client invocation that produced it was: which
problems the benchmark asked for in one go. The 2026-10-22 like-for-like
regrade (potential_configs.md §R50) found the same kernel reading 2.1-4.2x
differently under a 1-problem invocation than under the family-wide one, so a
verdict pairing across forms measures the protocol, not the kernel.

The four forms, stamped into records, kernel_db rows and the report payload:

* ``FAMILY``  -- the invocation covers every graded cell of the record's
  family (``_loader.current_profile().family_cells``, the deck's own cell list; declared shapes win over
  measured so a family phase that lost one shape to a Tensile rejection still
  classifies by what it was ASKED to run). This is what every gf900 floor
  phase measures (verified 2026-10-23 corpus-wide: all 3802 floor CSVs are
  exactly family-wide), so it is the graded basis wherever a floor is
  compared against.
* ``SINGLE``  -- exactly one problem. Config evidence only (the deck's iso
  calibration rows exist to measure it); never a graded basis against the
  floor.
* ``PARTIAL`` -- more than one problem but not the whole family cell list:
  the trio/pair containers and the narrow (all-but-one) spans. Excluded from
  graded bases anyway -- their readings swap across runs at fixed problem
  order (§R53: one DD trio read 77.8/19.6 and 30.3/80.5 from two runs).
* ``UNKNOWN`` -- not derivable: registry-only rows whose phase shape list was
  never recorded, or an unattributable family. Never asserted either way and
  never admitted to a graded basis.

Does NOT own: the records it classifies (oto.metrics.ab_records builds them),
the deltas they feed (oto.metrics.ab_delta), or the corpus it stamps
(oto.harness.kernel_db).
Public API: SINGLE, PARTIAL, FAMILY, UNKNOWN, PROTOCOLS, LABEL, label,
gradeable, classify, classify_count, protocol_of, like_for_like, yaml_count,
problem_count_text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from oto.device import loader as _loader

#: Invocation forms. Values are stamped into artifacts — treat as format.
SINGLE = "single"
PARTIAL = "partial"
FAMILY = "family"
UNKNOWN = "unknown"

PROTOCOLS = (FAMILY, SINGLE, PARTIAL, UNKNOWN)

#: Human labels, one per form, used in printouts and provenance fields.
LABEL: dict[str, str] = {
    FAMILY: "family-protocol",
    SINGLE: "single-problem",
    PARTIAL: "partial",
    UNKNOWN: "unknown-protocol",
}

#: ``- Exact: [256, 256, 1, 256, ...]`` problem rows under ProblemSizes in a
#: Tensile 00_Final.yaml. Tensile writes no other list form on this corpus
#: (verified 2026-10-23 from every yaml of the modern run), so counting these
#: lines is the whole ProblemSizes read for the kernel_db stamping path.
_PROBLEM_LINE = re.compile(r"^\s*-\s+Exact:", re.MULTILINE)

_CUBE = re.compile(r"\s*([0-9]+)x\1x\1\Z")


def label(protocol: str | None) -> str:
    """The human label for a protocol value (``''``-safe)."""
    return LABEL.get(protocol or UNKNOWN, LABEL[UNKNOWN])


def gradeable(fam: str, profile=None):
    """The graded-cell side set of a family ('NxNxN' strings; may be empty).

    ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
    """
    cells = _loader.resolve_profile(profile,).family_cells.get(str(fam or "").upper(),)
    if not cells:
        return set()
    return {f"{int(s)}x{int(s)}x{int(s)}" for s in cells}


def _side_set(shapes: Iterable[Any]) -> set[str]:
    """Normalized cube-side set from a mixed shape list (non-cubes dropped).

    A non-cube problem (a GEMV probe row) can never satisfy a cell list by
    itself, and the FAMILY superset test tolerates extras by construction, so
    dropping them is what makes the test safe for a phase that also carries
    one non-cube problem.
    """
    out: set[str] = set()
    for s in shapes or ():
        m = _CUBE.match(str(s).strip())
        if m:
            n = int(m.group(1))
            out.add(f"{n}x{n}x{n}")
    return out


def classify(fam: str,
             measured_shapes: Iterable[Any] = (),
             declared_shapes: Iterable[Any] = ()) -> str:
    """Classify one phase's invocation form from its shape lists.

    ``declared_shapes`` is what the phase was configured to benchmark (the
    run manifest / the 00_Final.yaml ProblemSizes); ``measured_shapes`` is
    what the CSVs actually produced. The declared list wins: a family phase
    whose one shape was rejected still *asked* family-wide. A one-problem
    invocation is SINGLE, a side set covering the family's graded cells is
    FAMILY, any other multi-problem invocation is PARTIAL, and nothing
    derivable is UNKNOWN.
    """
    cells = gradeable(fam)
    if not cells:
        # No graded cell list for this family: no measurable form claim
        # (UNKNOWN), including the unattributable and deck-external cases.
        return UNKNOWN

    declared = _side_set(declared_shapes)
    if declared:
        if cells <= declared:
            return FAMILY
        return SINGLE if len(declared) == 1 else PARTIAL

    measured = _side_set(measured_shapes)
    if cells <= measured:
        return FAMILY
    if len(measured) == 1:
        return SINGLE
    if measured:
        return PARTIAL
    return UNKNOWN


def problem_count_text(text: str) -> int:
    """Count declared problems in a parsed 00_Final.yaml text (0-safe)."""
    return len(_PROBLEM_LINE.findall(text))


def yaml_count(yaml_path: Path) -> int | None:
    """How many problems a Tensile 00_Final.yaml declares.

    ``None`` only when the file is missing or unreadable -- callers must treat
    that as "no declared count", never as one problem.
    """
    path = Path(yaml_path)
    if not path.is_file():
        return None
    try:
        return problem_count_text(path.read_text())
    except OSError:
        return None


def classify_count(fam: str,
                   n_problems: int | None,
                   measured_shapes: Iterable[Any] = ()) -> str:
    """Classify from a declared problem count plus the measured side set.

    kernel_db's stamping path: the phase yaml (when one exists) gives the
    count, the CSVs give the shapes. A count cannot prove *which* sides were
    asked for, so a measured superset of the graded cells is the only FAMILY
    proof it can corroborate; everything else follows the same rules as
    :func:`classify` (1 -> SINGLE, big-but-unproven -> PARTIAL, nothing ->
    UNKNOWN).
    """
    cells = gradeable(fam)
    measured = _side_set(measured_shapes)
    if cells and cells <= measured:
        return FAMILY
    if len(measured) == 1:
        return SINGLE
    if n_problems == 1:
        return SINGLE
    if n_problems and n_problems > 1:
        return PARTIAL
    if measured:
        return PARTIAL
    return UNKNOWN


def protocol_of(record: dict[str, Any]) -> str:
    """A record's stamped protocol (UNKNOWN when unstamped).

    The only read-side accessor: every graded-basis filter must go through
    this, so a record that predates the stamp is honestly UNKNOWN and is
    excluded from graded bases rather than silently admitted.
    """
    p = record.get("protocol")
    return p if p in PROTOCOLS else UNKNOWN


def like_for_like(native_protocol: str | None,
                  floor_protocol: str | None) -> bool:
    """True when both sides carry the same, known protocol.

    UNKNOWN on either side can neither be asserted to match nor mismatch, so
    it is never comparable.
    """
    return native_protocol in (FAMILY, SINGLE, PARTIAL) \
        and native_protocol == floor_protocol
