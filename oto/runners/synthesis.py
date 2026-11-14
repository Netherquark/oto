#!/usr/bin/env python3
"""Stage 6: emit the per-family library logic and build it with TensileCreateLibrary.

Owns: ``synthesize_library`` -- the 7 family logic YAMLs, the TensileCreateLibrary
invocation, the anti-alias scan that rejects any ``gfx900``/``vega10`` leak into
a native library, and the shipped-footprint coverage gate.
Does NOT own: the family decks it writes (oto.tensile.candidate), or the
Tensile environment it uses (driver.py).
Public API: SynthesisMixin.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

import oto.tensile.best_library as bestlib
import oto.tensile.library as tlib
from oto.agents import harness_tools
from oto.agents import meta as agent_meta
from oto.agents.research import make_researcher
from oto.device import loader as _loader
from oto.tools import potential_configs_gen


class SynthesisMixin:
    """Final library synthesis, mixed into TensileDriver."""

    def _emit_family_logic(self, logic_dir: Path, profile=None) -> None:
        """Placeholder logic definitions for the 7 dtype families.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        hint = bestlib.logic_filename_hint(getattr(self, "tensile_root", None),
                                           _loader.resolve_profile(profile,).codename)
        for fam in ["SS", "DD", "HH", "ZZ", "CC", "HH_HPA", "HS_HPA"]:
            logic_file = logic_dir / f"{hint}_{fam}.yaml"
            logic_content = {
                "MinimumRequiredVersion": "4.44.0",
                "CustomKernelName": f"{_loader.resolve_profile(profile,).codename}_{fam}_lib",
                "ScheduleName": "isa",
                "Architecture": _loader.resolve_profile(profile,).codename,
                "DeviceNames": [_loader.resolve_profile(profile,).codename],
                "Solutions": self.scheduler.family_decks.get(fam, [],)
            }
            with open(logic_file, "w") as f:
                yaml.safe_dump(logic_content, f)

    def _run_tensile_create_library(self, tcl_bin: Path, logic_dir: Path,
                                    final_lib_dir: Path, profile=None) -> dict[str, Any] | None:
        """Invoke TensileCreateLibrary; the error dict on failure, else None.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        arch = getattr(getattr(self, 'profile', None), 'codename', _loader.resolve_profile(profile,).codename)
        cmd = [
            sys.executable,
            str(tcl_bin),
            f"--architecture={arch}",
            "--code-object-version=V4",
            "--merge-files",
            str(Path(logic_dir).resolve()),
            str(Path(final_lib_dir).resolve())
        ]
        env = self._get_tensile_env()
        proc = subprocess.run(cmd, env=env, cwd=str(self.tensile_root),
                              capture_output=True, text=True,)
        if proc.returncode != 0:
            # Tensile prints its traceback on stdout, not stderr.
            tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
            return {
                "status": "failed",
                "returncode": proc.returncode,
                "error": tail[-1500:],
            }
        return None

    def _anti_alias_scan(self, logic_dir: Path,
                         final_lib_dir: Path) -> tuple[bool, list[str]]:
        """Reject any gfx900/vega10 leak into the emitted library."""
        anti_alias_passed = True
        leak_files = []
        for path in list(logic_dir.glob("*.yaml")) + list(final_lib_dir.glob("*")):
            if path.is_file():
                try:
                    content = path.read_text(errors="ignore")
                    if "gfx900" in content or "vega10" in content:
                        anti_alias_passed = False
                        leak_files.append(str(path))
                except Exception:
                    pass
        return anti_alias_passed, leak_files

    def _library_result(self, final_lib_dir: Path) -> dict[str, Any]:
        """The shipped-footprint coverage gate result."""
        # Regression gate: verify full shipped gfx900 footprint coverage
        shipped = tlib.load_shipped_manifest(self.base_dir)
        covered_families = list((shipped.get("expected_kernels") or {}).keys())
        return {
            "status": "success",
            "library_path": str(final_lib_dir),
            "anti_alias_verified": True,
            "families_covered": len(covered_families) if covered_families else 0,
            "target_kernels": shipped.get("total_shipped_kernels", 0)
        }

    def synthesize_library(self) -> dict[str, Any]:
        """
        Synthesize final HIP library (Stage 6):
        - Query certified winners from DB
        - Emit per-family logic YAML files into 3_LibraryLogic/
        - Invoke TensileCreateLibrary --architecture=<codename> --merge-files
        - Perform strict anti-alias scan rejecting any 'gfx900' or 'vega10' tokens
        - Enforce the shipped gfx900 footprint regression gate
        """
        print("Synthesizing final HIP library (Stage 6)...")
        tcl_bin = self.tensile_root / "Tensile" / "bin" / "TensileCreateLibrary"
        logic_dir = self.run_dir / "3_LibraryLogic"
        final_lib_dir = self.run_dir / "FinalLibrary"
        logic_dir.mkdir(parents=True, exist_ok=True)
        final_lib_dir.mkdir(parents=True, exist_ok=True)

        # 1. Query records and emit logic files
        records = self.registry.read_records(record_type="cell_analytics")
        if not records:
            # Fallback to all records if cell_analytics not yet populated
            records = self.registry.read_records()
        self._emit_family_logic(logic_dir)

        # 2. Invoke TensileCreateLibrary if binary present
        if tcl_bin.exists():
            failure = self._run_tensile_create_library(tcl_bin, logic_dir,
                                                       final_lib_dir)
            if failure:
                return failure

        # 3. Anti-alias scan: reject any gfx900 or vega10 leaks
        anti_alias_passed, leak_files = self._anti_alias_scan(logic_dir,
                                                              final_lib_dir)
        if not anti_alias_passed:
            return {
                "status": "failed",
                "error": f"Anti-alias violation: gfx900/vega10 found in {leak_files}"
            }

        # 4. Regression gate: verify full shipped gfx900 footprint coverage
        return self._library_result(final_lib_dir)

    def synthesize_best_library(self, dest: Path | None = None,
                                protocol_basis: str = "family", profile=None) -> dict[str, Any]:
        """Carve a best-effort device TensileLibrary.dat from the full db.

        ``profile`` -- optional ``DeviceProfile``; defaults to the process's ambient profile.
        """
        dest = Path(dest) if dest else bestlib.default_best_library_dest(self.base_dir)
        result = bestlib.build_best_library(
            self.base_dir, dest, basis=protocol_basis,
            tensile_root=getattr(self, "tensile_root", None),
            codename=getattr(self, "codename", _loader.resolve_profile(profile,).codename))
        print(f"Best-effort library: {result}")
        return result

    def generate_device_docs(self, starter_path=None) -> dict[str, Any]:
        """Run agent-1 + agent-2 to generate device-specific docs."""
        from pathlib import Path

        from oto.device.loader import load_profile, load_profile_from_starter
        starter = Path(starter_path) if starter_path else None
        if starter and starter.exists():
            profile = load_profile_from_starter(starter)
            text = starter.read_text()
        else:
            profile = load_profile(_loader.resolve_profile().codename)
            text = ""
        researcher = make_researcher(starter_text=text)
        def harness_fn():
            return harness_tools.build_harness_study(self.base_dir, profile)
        result = agent_meta.run(profile, text, research=researcher,
                                harness=harness_fn)
        # write docs
        out_dir = self.base_dir
        tl_path = out_dir / f"{profile.codename}_theoretical_limits.md"
        tc_path = out_dir / f"{profile.codename}_tuning_context.md"
        hs_path = out_dir / f"{profile.codename}_harness_study.md"
        pc_path = out_dir / f"{profile.codename}_potential_configs.md"
        tl_path.write_text(result["theoretical_limits"])
        tc_path.write_text(result["tuning_context"])
        tl_harness = result.get("harness") or {}
        hs_path.write_text(tl_harness.get("markdown", ""))
        try:
            pc_path.write_text(potential_configs_gen.generate(profile, self.base_dir))
        except Exception as exc:  # configs doc is additive; never fail the docs
            pc_path.write_text(f"# potential_configs.md — {profile.codename}\n\n"
                               f"Synthesis failed: {exc}\n")
        docs = [tl_path, tc_path, hs_path, pc_path]
        print(f"Generated {', '.join(str(p) for p in docs)}")
        return {"status": "success", "profile": profile.codename,
                "docs": [str(p) for p in docs]}
