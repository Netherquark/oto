"""oto -- one-shot deterministic convergence for native device Tensile libraries.

The public API of the project re-exported here so a caller never has to know
which subpackage a symbol moved to. Names are deliberately the ones the codebase
used before the package split (``TensileDriver``, ``CandidateGenerator``,
``Mutator``, ``ConvergenceAgent``, ``AnalyticsEngine``, ``AcceptanceReporter``,
``SQLiteRegistry``), so existing importers keep working across the move.

Layout -- one responsibility per package, named for it:

    oto.device     hardware peaks + canonical cell/family vocabulary
    oto.tensile    the Tensile-facing candidate pipeline and its legality gates
    oto.ledger     durable state + the mutation/convergence state machine
    oto.metrics    turning benchmark rows into verdicts, reports and status
    oto.runners    the driver, phase runner, reference floor, auto loop, CLI
    oto.checks    operator diagnostics (check_* family)
    oto.tools      offline corpus analysis (consolidate / allruns / verify_run)
    oto.harness   the analysis harness (kernel_db, regression matrix, ...)

See ``docs/README.md`` for the boundary between this docs ecosystem and the
docstrings inside the package, and ``docs/docstrings.md`` for the module and
function docstring convention.

Owns: the public API of the project -- the historical flat names, resolved
lazily (PEP 562) so ``import oto`` never pays for the whole tree and never
triggers the driver's ``load_dotenv`` side effect.
Does NOT own: any of those symbols' implementations (they live in the
subpackages, and each module's docstring says which), the hardware facts
(oto.device), or the docs ecosystem (docs/).
Public API: TensileDriver, CandidateGenerator, Mutator, ConvergenceAgent,
AnalyticsEngine, AcceptanceReporter, SQLiteRegistry, __version__.
"""

from oto._version import __version__  # single source of truth for the CLI

__all__ = [
    "AcceptanceReporter",
    "AnalyticsEngine",
    "CandidateGenerator",
    "ConvergenceAgent",
    "Mutator",
    "SQLiteRegistry",
    "TensileDriver",
    "__version__",
]


def __getattr__(name):
    """Resolve the public re-exports lazily (PEP 562).

    A module-level import of every subpackage would make ``import oto`` pay for
    the whole tree and, worse, would import the driver (and its ``load_dotenv``
    side effect) before a caller that only wants ``oto.device.peaks`` asked for
    it. Lazy resolution keeps ``import oto`` cheap and side-effect free.
    """
    if name == "TensileDriver":
        from .runners.driver import TensileDriver

        return TensileDriver
    if name == "CandidateGenerator":
        from .tensile.candidate import CandidateGenerator

        return CandidateGenerator
    if name == "Mutator":
        from .ledger.mutator import Mutator

        return Mutator
    if name == "ConvergenceAgent":
        from .ledger.agent import ConvergenceAgent

        return ConvergenceAgent
    if name == "SQLiteRegistry":
        from .ledger.registry import SQLiteRegistry

        return SQLiteRegistry
    if name == "AnalyticsEngine":
        from .metrics.analytics import AnalyticsEngine

        return AnalyticsEngine
    if name == "AcceptanceReporter":
        from .metrics.report import AcceptanceReporter

        return AcceptanceReporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
