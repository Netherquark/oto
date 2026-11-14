#!/usr/bin/env python3
"""The project's YAML reader: libyaml when it is there, cached by content.

Owns: ``load_yaml`` / ``load_yaml_text`` (parse with the fastest *safe*
loader available) and ``load_yaml_cached`` (the same, memoised by the file's
path, size and mtime so a deck that has not changed is parsed once).

Does NOT own: the YAML *content* (the deck is ``phases.yaml``, the overlay is
``<codename>_results/overlays/phases.seed.overlay.yaml``, the phase configs are
written by oto.tensile.config_writer) or the JSON caches (those are JSON and
are read with ``json``).

Why this exists: the deck and the overlay are re-read by the driver, the
candidate pool, the checks and every test that touches them, and PyYAML's
pure-Python ``safe_load`` was 0.27 s for ``phases.yaml`` -- a tenth of the
test suite's wall clock, spent parsing the same immutable file. libyaml is
8x faster on the same file, and the cache removes the repeats.

The loader choice never changes a verdict: ``CSafeLoader`` implements the same
SafeLoader semantics, and the pure-Python loader is used when libyaml is not
available. ``load_yaml_cached`` keys on (path, size, mtime), so a rewritten
file is re-read.

Public API: load_yaml, load_yaml_text, load_yaml_cached, clear_cache,
HAS_LIBYAML, dump_yaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: True when PyYAML was built with libyaml (the C loader).
HAS_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))

#: The safe loader to use. ``CSafeLoader`` is the C implementation of the
#: SafeLoader; the pure-Python one is the fallback.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

#: (path, size, mtime) -> parsed document.
_CACHE: dict[tuple[str, int, int], Any] = {}


def load_yaml_text(text: str) -> Any:
    """Parse YAML text with the fastest safe loader available.

    Args:
        text: The YAML document.

    Returns:
        The parsed document (None for an empty document).
    """
    return yaml.load(text, Loader=_LOADER)


def load_yaml(path: str | Path) -> Any:
    """Read and parse a YAML file.

    Args:
        path: The file to read.

    Returns:
        The parsed document, or None when the file is empty.
    """
    return load_yaml_text(Path(path).read_text())


def load_yaml_cached(path: str | Path) -> Any:
    """Read and parse a YAML file, memoised by its content stamp.

    Args:
        path: The file to read.

    Returns:
        The parsed document. A file whose size or mtime changed is re-read, so
        a rewritten deck is never served from a stale cache.
    """
    p = Path(path)
    try:
        stat = p.stat()
        key = (str(p.resolve()), stat.st_size, stat.st_mtime_ns)
    except OSError:
        return load_yaml(p)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    doc = load_yaml(p)
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = doc
    return doc


def clear_cache() -> None:
    """Empty the memo (the tests use it to prove the cache is not stale)."""
    _CACHE.clear()


def dump_yaml(payload: Any, path: str | Path) -> None:
    """Write a YAML document the way the project writes them.

    Args:
        payload: The document to write.
        path: The file to write it to.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, default_flow_style=False)
