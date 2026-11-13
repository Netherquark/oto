#!/usr/bin/env python3
"""A content-keyed memo for the pure legality gates.

Owns: ``config_key`` (a stable, hashable key for a config dict) and
``memo_gate`` (a decorator that caches a pure ``(config) -> (ok, reason)``
gate by the config's *content*).

Does NOT own: the gates themselves (oto.tensile.gates.assembly,
oto.tensile.gates.loads, oto.tensile.gates.occupancy), the candidate
orchestrator (oto.tensile.candidate), or the corpus (oto.harness.kernel_db).

Why: the gates are pure functions of their config, and the *test suite* asks
the same question thousands of times -- the deck's rows, the frontier sweep
and the coverage map all re-validate the same geometries. `test_generate_candidates`
spent 60 s and `test_tile_frontier` spends most of its time re-deriving
verdicts that were already derived. The memo is keyed by content, so a config
that changes gets a new verdict and a config that does not gets the old one.

The cache is bounded: a long mutating run must not grow it without limit, so
it is cleared when it passes ``MAX_ENTRIES`` (the gates are cheap enough to
re-derive). It is per-process, which is what a parallel test run wants: each
worker keeps its own.

Public API: config_key, memo_gate, MAX_ENTRIES.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any

#: The cache is cleared when it passes this many entries. A deck sweep asks a
#: few thousand distinct questions; a long mutating run can ask tens of
#: thousands, and re-deriving a verdict is cheaper than holding it.
MAX_ENTRIES = 50_000


def config_key(config: dict[str, Any]) -> str:
    """A stable key for a config dict's *content*.

    Args:
        config: A Tensile solution dict (any JSON-ish mapping).

    Returns:
        A string that changes whenever any value changes. ``default=str``
        keeps an exotic value (a tuple, a Path) from raising -- it stringifies
        instead, which is still content-addressed.
    """
    return json.dumps(config, sort_keys=True, default=str)


def memo_gate(fn: Callable[[dict[str, Any]], tuple[bool, str]]
               ) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    """Cache a pure ``(config) -> (ok, reason)`` gate by the config's content.

    Args:
        fn: The gate to memoise. It must be pure: same config, same verdict,
            always. The three legality gate families are (they read the config
            and the module's own constants, and nothing else).

    Returns:
        The cached gate. ``cache_clear()`` empties it (the tests use it to
        prove the memo does not change a verdict).
    """
    cache: dict[str, tuple[bool, str]] = {}

    @functools.wraps(fn)
    def wrapper(config: dict[str, Any], *args, **kwargs) -> tuple[bool, str]:
        # Profile-aware calls are not memoised (they depend on device state).
        if args or kwargs:
            return fn(config, *args, **kwargs)
        key = config_key(config)
        hit = cache.get(key)
        if hit is not None:
            return hit
        result = fn(config)
        if len(cache) >= MAX_ENTRIES:
            cache.clear()
        cache[key] = result
        return result

    wrapper.cache_clear = cache.clear  # type: ignore[attr-defined]
    wrapper.cache_size = lambda: len(cache)  # type: ignore[attr-defined]
    return wrapper
