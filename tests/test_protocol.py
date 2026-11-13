#!/usr/bin/env python3
"""The invocation-form classifier tests (oto.metrics.protocol, §R56.3).

Every case below is corpus-derived: the forms the classifier must separate are
the ones the deck actually emits (family-wide spans, the §R50 iso AUTO_EXPLICIT
singles, the §R53 trio containers, and the narrow all-but-one spans), and the
ground rules were verified against the live runs on 2026-10-23 -- e.g. the
identically-named `phase_auto_0_hh_256x256x256_4` ran family-protocol
(5 problems) in run_20261006_122020 and single-problem in run_20261008_005217,
which is why no naming shortcut is ever consulted.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from oto.metrics.protocol import (
    FAMILY,
    PARTIAL,
    SINGLE,
    UNKNOWN,
    classify,
    classify_count,
    label,
    like_for_like,
    protocol_of,
)


def _cube(n: int) -> str:
    return f"{n}x{n}x{n}"


class TestClassify(unittest.TestCase):
    """classify() over the corpus's real invocation families."""

    def test_family_declared_and_measured(self):
        assert classify("SS", [], [_cube(s) for s in (256, 512, 768, 1000, 1024, 1365, 2048, 4096)]) == FAMILY
        assert classify("SS", [_cube(s) for s in (256, 512, 768, 1000, 1024, 1365, 2048, 4096)]) == FAMILY

    def test_family_tolerates_non_cube_extras(self):
        declared = [_cube(s) for s in (256, 512, 1024, 2048, 4096)]
        assert classify("HH", [*declared, "32x4096x1"]) == FAMILY

    def test_single(self):
        assert classify("HH", [_cube(256)]) == SINGLE
        assert classify("SS", declared_shapes=[_cube(256)]) == SINGLE

    def test_partial_containers_and_narrows(self):
        # the §R53 DD trio: 3 sides, not the deck's 6-cell DD list
        trio = [_cube(s) for s in (192, 256, 2048)]
        assert classify("DD", trio) == PARTIAL
        # the §R50b narrow span: HH minus one side
        narrow = [_cube(s) for s in (512, 1024, 2048, 4096)]
        assert classify("HH", narrow) == PARTIAL

    def test_hpa_family_uses_its_own_cell_list(self):
        # HS_HPA's graded list is 3 cells (512/1024/2048) though its benchmark
        # contract has 4 sides: the modern HS_HPA deck span IS family form.
        assert classify("HS_HPA", [_cube(s) for s in (512, 1024, 2048)]) == FAMILY
        assert classify("HS_HPA", [_cube(s) for s in (512, 1024, 2048, 4096)]) == FAMILY
        # ...and an HS_HPA pair is not family form either way.
        assert classify("HS_HPA", [_cube(512), _cube(2048)]) == PARTIAL

    def test_unknown_family_and_empty(self):
        assert classify("QQ", [_cube(256)]) == UNKNOWN
        assert classify("SS", []) == UNKNOWN
        assert classify("", [_cube(256)]) == UNKNOWN

    def test_declared_wins_over_partial_measurement(self):
        """A family phase that lost one shape still asked family-wide."""
        cells = [_cube(s) for s in (256, 512, 768, 1000, 1024, 1365, 2048)]
        declared = [*cells, _cube(4096)]
        assert classify("SS", cells, declared) == FAMILY


class TestClassifyCount(unittest.TestCase):
    """The kernel_db path: yaml count + CSV sides."""

    def test_count_one_is_single_without_other_proof(self):
        assert classify_count("HH", 1, [_cube(256)]) == SINGLE
        assert classify_count("HH", 1, []) == SINGLE

    def test_family_proof_beats_the_count(self):
        # floor phases carry no yaml (count None); their CSVs prove family.
        assert classify_count("SS", None, [_cube(s) for s in (256, 512, 768, 1000, 1024, 1365, 2048, 4096)]) == FAMILY

    def test_multi_count_without_proof_is_partial(self):
        assert classify_count("DD", 3, [_cube(s) for s in (192, 256, 2048)]) == PARTIAL
        assert classify_count("DD", 7, []) == PARTIAL

    def test_nothing_is_unknown(self):
        assert classify_count("SS", None, []) == UNKNOWN


class TestAccessors(unittest.TestCase):
    """protocol_of/like_for_like/label: the stamp's read side."""

    def test_protocol_of_unstamped_is_unknown(self):
        assert protocol_of({}) == UNKNOWN
        assert protocol_of({"protocol": "family"}) == FAMILY
        assert protocol_of({"protocol": "nonsense"}) == UNKNOWN

    def test_like_for_like(self):
        assert like_for_like(FAMILY, FAMILY)
        assert like_for_like(SINGLE, SINGLE)
        assert not like_for_like(FAMILY, SINGLE)
        assert not like_for_like(FAMILY, UNKNOWN)
        assert not like_for_like(UNKNOWN, UNKNOWN)

    def test_labels(self):
        assert label(FAMILY) == "family-protocol"
        assert label(SINGLE) == "single-problem"
        assert label(PARTIAL) == "partial"
        assert label(None) == "unknown-protocol"


if __name__ == "__main__":
    unittest.main()
