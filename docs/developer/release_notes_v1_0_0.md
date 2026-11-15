# oto v1.0.0 — Recovering ROCm functionality for unsupported AMD GPUs

Paste this into the GitHub release form when tagging `v1.0.0`.

---

`oto` is a deterministic, benchmark-driven tuning suite that
generates, validates and optimises a `TensileLibrary.dat` for unsupported
AMD hardware. **gfx90c** (Ryzen 5 5650U's Vega 7 iGPU) is the first target.
`oto` is named after the manul (*otocolobus manul*), the stubborn, square-headed
cat of the steppe.

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
- **CLI** — `oto doctor`, append-only SQLite ledger, machine-readable reports, 
  reconstructed acceptance reports with per-cell verdicts.
- **Easy-mode setup** — `oto setup --yes` prepares toolchain, `.env` and client;
  with `--download-rocm python --download-tensile clone` it can also install
  the nightly TheRock stack on request.

## Results on gfx90c

Against the shipped gfx900 Tensile floor: **20 WIN / 18 TIE / 0 LOSS** on the
acceptance corpus. Coverage parity **38/38** shipped cells. Gains of upto 2.78x
over using gfx900 kernels on gfx90c.

## Application level proof with PyTorch: 
YOLO26 object detection runs end-to-end on the gfx90c GPU at roughly **~12 FPS** 
with the custom TensileLibrary.dat on PyTorch 2.12 / ROCm 7.15 with the GPU backend.

## Verified on

- **gfx90c APU (Ryzen 5 5650U, Vega 7).**
- **dnf-provided ROCm 6.4.4 on Fedora 43**
- **TheRock nightly `7.15.0a20260728`**: both the full-SDK and the python-wheel SDK
- **AMD GPU / PyTorch:** `torch 2.12.0+rocm7.15.0a20260728` (hip 7.15.0) —
  YOLO26 static-image inference on both SDK containers, identical detection,
  `cuda:0`; correctness spot-checks vs fp64 CPU references ≤ 4.2e-05.

## Future scope

- **gfx902 cross-validation is pending**

## License

GPL-3.0-or-later for code; docs CC-BY-SA-4.0. See `LICENSE` and `NOTICE`.
