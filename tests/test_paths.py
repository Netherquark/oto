"""Tests for the runs/results-directory resolvers (CPU-only)."""

import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oto.runners.paths import (
    LEGACY_RESULTS_DIR_NAME,
    LEGACY_RUNS_DIR_NAME,
    results_dir,
    runs_dir,
)


def test_primary_wins_when_present(tmp_path):
    primary = tmp_path / "fake900_runs"
    legacy = tmp_path / LEGACY_RUNS_DIR_NAME
    primary.mkdir()
    legacy.mkdir()
    assert runs_dir(tmp_path, "fake900") == primary


def test_primary_used_when_no_legacy(tmp_path):
    assert runs_dir(tmp_path, "fake900") == tmp_path / "fake900_runs"


def test_legacy_fallback_warns(tmp_path):
    legacy = tmp_path / LEGACY_RUNS_DIR_NAME
    legacy.mkdir()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = runs_dir(tmp_path, "fake900")
    assert resolved == legacy
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_results_primary_wins_when_present(tmp_path):
    primary = tmp_path / "fake900_results"
    legacy = tmp_path / LEGACY_RESULTS_DIR_NAME
    primary.mkdir()
    legacy.mkdir()
    assert results_dir(tmp_path, "fake900") == primary


def test_results_primary_used_when_no_legacy(tmp_path):
    assert results_dir(tmp_path, "fake900") == tmp_path / "fake900_results"


def test_results_legacy_fallback_warns(tmp_path):
    legacy = tmp_path / LEGACY_RESULTS_DIR_NAME
    legacy.mkdir()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = results_dir(tmp_path, "fake900")
    assert resolved == legacy
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
