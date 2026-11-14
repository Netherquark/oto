"""Device facts: hardware identity and the cell vocabulary.

The only oto package allowed to hold device facts, and the home of the
device seam: a driver that used to know gfx90c by name now reads one
``DeviceProfile`` at startup and works on any supported device. Concrete
pieces: ``loader.py`` (profile resolution via ``current_profile()``;
``resolve_profile()`` is the choke point explicit ``profile=`` kwargs use),
``profile.py`` (the frozen ``DeviceProfile`` shape), ``kernel_vocabulary.py``
(kernel-name parsing + cell identity) and ``tensile_isa.py`` (build-proof ISA
triples).
Owns: the profile dataclass and its nested policies, the profile loaders,
the codename -> ISA triple table, and the cell/kernel vocabulary.
Does NOT own: any legality rule (oto.tensile.gates), any measurement or
statistics (oto.metrics.*), or the driver's behaviour (oto.runners.*).
No numeric hardware fact may exist outside ``profiles/<codename>.json``.
Public API: none at import time; this package re-exports nothing. Callers
use ``oto.device.loader.current_profile()`` for device facts and
``oto.device.kernel_vocabulary`` for cell identity.
"""
