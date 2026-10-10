"""Everything Tensile-facing: the candidate pipeline and its CPU legality gates.

Submodules:
  oto.tensile.library    kernel-name parsing, shipped gfx900 manifest, tiers
  oto.tensile.candidate  candidate generation / deck precedence
  oto.tensile.gates      the three CPU legality gate families (imported by,
                         never interleaved with, the candidate generator)
  oto.tensile.legality    the manifest-derived legal prior
  oto.tensile.synthesis  coverage-guided candidate synthesis (manifest + db)
"""
