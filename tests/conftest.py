#!/usr/bin/env python3
"""Shared pytest configuration: the markers, the serial rule, the corpus cache.

Owns: the ``serial`` and ``preflight`` markers, the rule that keeps a
shared-state test out of a distributed run, and the session-scoped fixtures
that read the expensive corpus artifacts once per session.

Does NOT own: the tests themselves, the corpus (oto.harness.kernel_db), or the
gate memo (oto.tensile.gates.memo).

Why the markers exist:

* ``serial`` -- a test that writes into the repo tree (the deck, the overlay,
  the registry, kernel_db.json) must not run while another worker is reading
  it. The suite is currently fully isolated (every write goes to a tmp dir),
  so nothing carries the marker today; the rule is here so the *next* such
  test is safe by default rather than by remembering.
* ``preflight`` -- the fast subset the overnight checklist runs before a run
  (``python3 -m pytest -m preflight``). It is the same tests the checklist
  names, tagged so the two cannot drift.

Why the fixtures: ``kernel_db.json`` is 18 MB of JSON and the shipped
manifest is a decode of the rocBLAS library. Several tests read them; the
session fixture parses each once and hands the same object to every test.

CPU only. No GPU, no Tensile run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from oto.runners.result_paths import results_rel

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def pytest_configure(config: pytest.Config) -> None:
    """Register the project's markers."""
    config.addinivalue_line(
        "markers",
        "serial: writes into the repo tree; skipped under a distributed run")
    config.addinivalue_line(
        "markers",
        "preflight: the fast pre-run subset the overnight checklist runs")


#: The test files the overnight preflight runs (the same list the checklist
#: names in `command.txt` and the runbook repeats). Marking them here keeps
#: the three in step: `pytest -m preflight` is the subset, and the checklist
#: can name the marker instead of a file list that drifts.
PREFLIGHT_FILES = (
    "test_candidate_generator.py",
    "test_occupancy_model_vgpr.py",
    "test_occupancy_model_lds.py",
    "test_occupancy_live_deck.py",
    "test_cell_attribution.py",
    "test_writer_forwards_sweep_knobs.py",
    "test_cell_resolver.py",
    "test_complex_flop_accounting.py",
    "test_tile_frontier.py",
    "test_corpus_census.py",
    "test_function_length.py",
    "test_pyflakes.py",
)


def pytest_collection_modifyitems(config: pytest.Config,
                                  items: list[pytest.Item]) -> None:
    """Tag the preflight subset, and keep the serial tests out of a
    distributed run.

    Under ``pytest -n auto`` the workers run concurrently, so a test that
    writes into the repo tree could be read half-written by another worker.
    The serial tests are skipped with the reason spelled out, and the
    checklist runs them in a serial pass.
    """
    for item in items:
        if item.path.name in PREFLIGHT_FILES:
            item.add_marker(pytest.mark.preflight)
    workers = config.getoption("numprocesses", 0) or 0
    if workers in (0, 1):
        return
    skip = pytest.mark.skip(
        reason=f"serial test: {workers} workers are running; run it serially "
               f"(pytest -m serial tests/...)")
    for item in items:
        if "serial" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def kernel_db_rows() -> dict[str, list[dict[str, Any]]]:
    """The corpus database, parsed once per session.

    Returns:
        The ``run_id -> rows`` mapping from ``kernel_db.json`` (empty when the
        cache does not exist yet).
    """
    from oto.harness.kernel_db import load_kernel_db

    cache = REPO / results_rel("analysis", "kernel_db.json")
    if not cache.is_file():
        return {}
    return load_kernel_db(str(cache))


@pytest.fixture(scope="session")
def default_profile():
    """The default (gfx90c) device profile, loaded once per session."""
    from oto.device.loader import load_profile

    return load_profile("gfx90c")


@pytest.fixture(scope="session")
def shipped_manifest() -> dict[str, Any]:
    """The shipped gfx900 footprint manifest, read once per session."""
    from oto.tensile.shipped_floor_manifest import load_shipped_manifest

    try:
        return load_shipped_manifest(REPO)
    except Exception:
        return {}


@pytest.fixture(scope="session")
def changed_python_files() -> list[str]:
    """The Python files changed in the working tree, for the fast guards.

    The function-length and pyflakes guards walk the whole tree. When the
    developer only needs the changed files, ``OTO_GUARD_FILES=1`` narrows
    them to the files git reports as modified or staged. The *full* scan is
    still the default, because a guard that only looks at what you touched
    is not a guard.
    """
    if os.environ.get("OTO_GUARD_FILES") != "1":
        return []
    import subprocess

    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO,
        capture_output=True, text=True, check=False).stdout
    files = []
    for line in out.splitlines():
        path = line[3:].strip()
        if path.endswith(".py"):
            files.append(path)
    return files


