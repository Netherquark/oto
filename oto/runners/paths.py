#!/usr/bin/env python3
"""Shared path conventions for the driver.

Owns: the runs-directory resolver. The pre-refactor oto recorded every run
under ``<base>/gfx90c_runs``; the device-independent layout is
``<base>/<codename>_runs`` (derived from the resolved ``DeviceProfile``).
Checkouts that still have the legacy directory keep working: the primary
``<codename>_runs`` wins when it exists (or the legacy one does not), and the
legacy directory is used as a fallback otherwise -- never silently moved or
renamed.
Does NOT own: device facts (oto.device owns those) or the results directory
for best-effort libraries (oto.tensile.best_library owns its dest).
Public API: runs_dir, legacy_runs_dir.
"""

from __future__ import annotations

import warnings
from pathlib import Path

# The one and only place the historic directory name appears. Kept so
# existing checkouts (and their knowledge_base/report references) keep
# resolving; everything else derives from the profile.
LEGACY_RUNS_DIR_NAME = "gfx90c_runs"
LEGACY_RESULTS_DIR_NAME = "gfx90c_results"

RUNS_DIR_TEMPLATE = "{codename}_runs"
RESULTS_DIR_TEMPLATE = "{codename}_results"


def runs_dir(base_dir, codename: str) -> Path:
    """The runs directory for this device under ``base_dir``.

    ``<base>/<codename>_runs`` when it exists or when no legacy directory is
    present; otherwise the legacy ``gfx90c_runs`` (backwards compatibility),
    with a one-shot DeprecationWarning so operators notice the rename.
    """
    base = Path(base_dir)
    primary = base / RUNS_DIR_TEMPLATE.format(codename=codename)
    legacy = base / LEGACY_RUNS_DIR_NAME
    if primary.is_dir() or not legacy.is_dir():
        return primary
    warnings.warn(
        f"using legacy runs directory {legacy} (rename to {primary})",
        DeprecationWarning,
        stacklevel=2,
    )
    return legacy


def legacy_runs_dir(base_dir) -> Path:
    """The historic runs directory name (for migration tooling)."""
    return Path(base_dir) / LEGACY_RUNS_DIR_NAME


def results_dir(base_dir, codename: str) -> Path:
    """The best-effort-results directory for this device under ``base_dir``.

    Same contract as :func:`runs_dir`: ``<base>/<codename>_results`` wins when
    it exists (or no legacy directory is present); otherwise the historic
    directory, with a one-shot DeprecationWarning.
    """
    base = Path(base_dir)
    primary = base / RESULTS_DIR_TEMPLATE.format(codename=codename)
    legacy = base / LEGACY_RESULTS_DIR_NAME
    if primary.is_dir() or not legacy.is_dir():
        return primary
    warnings.warn(
        f"using legacy results directory {legacy} (rename to {primary})",
        DeprecationWarning,
        stacklevel=2,
    )
    return legacy


def legacy_results_dir(base_dir) -> Path:
    """The historic results directory name (for migration tooling)."""
    return Path(base_dir) / LEGACY_RESULTS_DIR_NAME


def results_rel(*parts: str) -> str:
    """Repo-relative results subpath for the current device.

    Import-time safe (peaks is a constants module): for the default
    device this yields
    ``gfx90c_results/...`` exactly as before; for another profile it yields
    ``<codename>_results/...``. No literal appears in calling code.
    """
    import oto.device.peaks as _peaks
    return str(Path(RESULTS_DIR_TEMPLATE.format(codename=_peaks.CODENAME)).joinpath(*parts))


def runs_rel(*parts: str) -> str:
    """Repo-relative runs subpath for the current device (see results_rel)."""
    import oto.device.peaks as _peaks
    return str(Path(RUNS_DIR_TEMPLATE.format(codename=_peaks.CODENAME)).joinpath(*parts))
