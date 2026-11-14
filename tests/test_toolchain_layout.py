"""Root-resolution tests: oto must find Tensile inside the rocm-libraries
super repo, where it lives at ``shared/tensile`` (all lowercase), as well as
the older ``projects/Tensile`` / ``shared/Tensile`` spellings and the
standalone checkout layout.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from oto.runners.toolchain import require_tensile_root
from oto.tensile import best_effort_library as best_library


def _fake_root(base: Path, sub: str) -> Path:
    bindir = base / sub / "Tensile" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "Tensile").write_text("#!/bin/sh\n")
    return base


@pytest.mark.parametrize("sub", ["projects/Tensile", "shared/Tensile",
                                 "shared/tensile"])
def test_require_tensile_root_super_repo_layouts(tmp_path, sub):
    root = _fake_root(tmp_path, sub)
    assert require_tensile_root(root, None) == root / sub


def test_require_tensile_root_standalone(tmp_path):
    bindir = tmp_path / "Tensile" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "Tensile").write_text("#!/bin/sh\n")
    assert require_tensile_root(tmp_path, None) == tmp_path


@pytest.mark.parametrize("sub", ["projects/Tensile", "shared/Tensile",
                                 "shared/tensile"])
def test_expand_tensile_root_super_repo_layouts(tmp_path, sub):
    root = _fake_root(tmp_path, sub)
    assert best_library._expand_tensile_root(str(root)) == [str(root / sub)]
