"""Oto/README.md byte-matches what ``python3 -m oto.readme_gen`` would emit.

Unlike docs/cli.md (pinned by tests/test_docs_cli.py), oto/README.md drifted
silently -- the generator was the only writer, and nothing asserted the
committed file was current. This renders the package map in-memory and
compares, so any stale docstring surfaces here instead of as a confusing
surprise to a new reader.
"""
from __future__ import annotations

from pathlib import Path

import oto.readme_gen

REPO = Path(__file__).resolve().parents[1]
_DOC = REPO / "oto" / "README.md"


def test_oto_readme_is_fresh():
    assert _DOC.read_text() == oto.readme_gen.render(), (
        "oto/README.md is stale -- regenerate with `python3 -m oto.readme_gen`")
