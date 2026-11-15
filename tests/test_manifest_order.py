"""Manifest order is execution order (audit §3, v1-readiness).

The prior suite's reserved-gap phase numbering belonged to a Windows runbook;
this driver has no number reservation scheme — its invariant is simply that
``phases.yaml``'s order is the run order, and the loader and the drivers must
not reorder it. These tests pin it.
"""

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _check_phase(p):
    assert isinstance(p, dict), p
    pid = p.get("phase_id")
    assert isinstance(pid, str) and pid, p


def test_phases_yaml_loads_as_list():
    deck = yaml.safe_load((REPO / "phases.yaml").read_text())
    assert isinstance(deck, list)
    assert deck, "the production deck is never empty"
    for row in deck:
        _check_phase(row)
    ids = [row["phase_id"] for row in deck]
    assert len(ids) == len(set(ids)), "phase_id must be unique"


def test_deck_loader_preserves_file_order():
    from oto.checks.deck_legality import load_deck
    raw = yaml.safe_load((REPO / "phases.yaml").read_text())
    loaded = load_deck(REPO / "phases.yaml")
    assert [r["phase_id"] for r in loaded] == [r["phase_id"] for r in raw]


def test_roundtrip_is_stable():
    from oto.checks.deck_legality import load_deck
    first = [r["phase_id"] for r in load_deck(REPO / "phases.yaml")]
    second = [r["phase_id"] for r in load_deck(REPO / "phases.yaml")]
    assert first == second
