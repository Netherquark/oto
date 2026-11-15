# oto v1.0.0 — Recovering ROCm functionality for unsupported AMD GPUs

Paste this into the GitHub release form when tagging `v1.0.0`.

---

**ROCm is the only credible open-source alternative to CUDA.** AMD drops older
architectures on a schedule, and the large installed base — GCN5 (Vega) was cut
at ROCm 5.7 — is left software-stranded with no reproducible reference for
getting it back. `oto` is a deterministic, benchmark-driven tuning suite that
generates, validates and optimises a `TensileLibrary.dat` for unsupported
hardware. **gfx90c** (Ryzen 5 5650U's Vega 7 iGPU) is the first target — and
the method is the contribution: enumerate the strategies, benchmark each viable
path, document the failure modes, hand the next GPU a playbook instead of a
starting-from-zero.

This is a systematic pipeline, not a one-off workaround: the deliverable is the
library, the method is the contribution.

## Ships in v1.0.0 (gfx90c)

- **The full convergence pipeline** — enumerate candidates (gate-legal deck) →
  benchmark → ledger → mutate → converge, for both the SGEMM-ethos and the
  complex-half-precision families, plus ZZ/double. The agent layer proposes;
  the hardware decides; Tensile's compilation and validation gate every kernel.
- **Best-effort `TensileLibrary.dat`** for the target device, dispatched under
  PyTorch with your GEMM calls — the library is built by oto, tuned by the
  hardware, and used transparently.
- **Legality before tuning.** Every benchmarked kernel is checked against
  Tensile's own scalar CPU reference (`NumElementsToValidate=128`, always);
  builds are proven CPU-only before any GPU is engaged.
- **An honest CLI** — `oto doctor` (0 FAIL expected), append-only SQLite ledger
  (`run_registry.db`), machine-readable reports (`--json` everywhere it
  matters), reconstructed acceptance reports with per-cell verdicts.
- **`oto verify all`** evergreen equivalence checks; drift manifest for every
  deliberate divergence; a docs registry that keeps the whole ecosystem
  enforceably fresh.
- **Easy-mode setup** — `oto setup --yes` prepares toolchain, `.env` and client;
  with `--download-rocm python --download-tensile clone` it can also install
  the nightly TheRock stack on request (nothing downloads without asking).

## What the run says (gfx90c)

Against the shipped gfx900 Tensile floor: **20 WIN / 18 TIE / 0 LOSS** on the
acceptance corpus. Coverage parity **38/38** shipped cells. Every one of those
benchmarks was validated by Tensile itself (`NumElementsToValidate=128`), not
by oto's own numbers.

**The app-level proof** is PyTorch: on a Ryzen 5 5650U, YOLO26 object
detection runs end-to-end on the gfx90c GPU through the custom library at
roughly **~12 FPS** (owner-measured, 640px inference, NMS on CPU). That is an
end-to-end anecdote, not a tuning benchmark. Boxes, batch norm and the forward
pass are on `cuda:0`; torchvision's bundled NMS carries no usable gfx90c
kernel image, so only NMS crosses to the CPU. Right now it runs the
rebuilt-library path with MIOpen's GEMM solver (MIOpen's missing CK
grouped-conv for gfx90c means the default conv path needs the GEMM solver
instead — this is called out in the docs, not hidden).

## Verified on

- **gfx90c APU (Ryzen 5 5650U, Vega 7).**
- **dnf-provided ROCm 6.4.4** — the original port host (the Oct-29bring-up);
  key for home setup with distro packages, older ABI.
- **TheRock nightly `7.15.0a20260728`** in both forms: the **extracted dist
  tarball SDK** (full-SDK, `include/amd_smi` + CMake present, client built
  against it; GPU probes pass) and the **1.4 GB python-wheel SDK**
  (`_rocm_sdk_core`, the reference configuration for `.env`; build proofs and
  GPU legality probes pass; `oto doctor` 22 ok / 1 advisory / 0 fail).
- **AMD GPU / PyTorch:** `torch 2.12.0+rocm7.15.0a20260728` (hip 7.15.0) —
  YOLO26 static-image inference on both SDK containers, identical detection,
  `cuda:0`; correctness spot-checks vs fp64 CPU references ≤ 4.2e-05.

## Getting it

```bash
git clone <this repo>
python3 -m oto setup --yes          # guided: toolchain + .env + client
python3 -m oto doctor               # expect 0 FAIL
python3 -m oto tune               # on the TTY, on the target silicon
python3 -m oto verify all
```

Reading order after setup: `docs/human/getting_started.md` →
`docs/overview.md` → `docs/README.md` (class-tagged registry).

## Honest limits

- **Campaign hardware is gfx90c.** Bring-up was on this APU; other AMD GPUs
  follow the same method, but nothing else ships silicon-verified in this
  tag.
- **No uncontrolled perf claims.** Single uncontrolled runs (clocks floating)
  exist in the register; they are labeled as such and are not a tuning verdict.
  Perf verdicts come from clock-controlled runs on the target.
- **Power users of gfx90c should know**: NMS runs on CPU in the yolo26 example;
  MIOpen CK grouped-conv is absent (GEMM solver path is required); the system
  ROCm 6.4.4-built best-effort library hangs the gfx90c GPU — use the rebuilt
  library from `gfx90c_results/best_effort_library_rocmlibs/`, never the Oct-29
  artifact.
- **GPU work is user-TTY.** oto never dispatches a GPU from a headless session.

## License

GPL-3.0-or-later for code; docs CC-BY-SA-4.0. See `LICENSE` and `NOTICE`.
`oto` is named after the manul (*otocolobus manul*), the stubborn, square-headed
cat of the steppe — a machine for turning stranded hardware back into hardware.
