# oto

**Recovering ROCm functionality for unsupported AMD GPUs.**

ROCm is the only credible open-source alternative to CUDA for GPU compute. As it
matures, AMD periodically drops support for older architectures. This leaves a
large installed base of capable hardware — GCN5 (Vega) was cut at ROCm 5.7 —
software-stranded, with no clear upgrade path and no community resource
explaining how to recover one.

`oto` is a deterministic, benchmark-driven tuning suite that recovers missing
ROCm/Tensile functionality on unsupported AMD GPUs. Its first target is
**gfx90c** (Cezanne Vega 7); **gfx902** (Raven Ridge Vega 8) is the
cross-validation target. The methodology generalises: the pipeline — enumerate
the strategies, benchmark each viable path, document the failure modes —
applies identically when ROCm eventually drops RDNA1 or any other architecture.

## Why

GCN5 APUs are common in the Indian student and developer demographic, and
platform upgrades have been put on hold due to inflated GPU/RAM prices.
Existing community resources amount to fragmented Reddit threads and closed
GitHub issues. No reproducible, end-to-end reference exists for a modern
Linux distribution. The goal is not just to make one GPU work; it is to build
a **reusable method** others can apply to their hardware without starting from
scratch.

## What oto does

`oto` turns a software-stranded AMD GPU into a native, tuned Tensile library:

```
profile → derive ceilings → gate-legal deck → benchmark → ledger → mutate → converge
```

oto generates candidate kernels through Tensile; the compiler validates and the
hardware decides. The agent layer proposes — it never decides. Every
measurement, verdict and report is reconstructible from an append-only SQLite
ledger. The deliverable is the library; the method is the contribution.

## Status

- **gfx90c** (Ryzen 5 5650U, Vega 7): ported, converged, library builds and
  dispatches under PyTorch. **20 WIN / 18 TIE / 0 LOSS** against the shipped
  gfx900 floor.
- **gfx902** (Ryzen 5 2200G, Vega 8): CPU-side pipeline ready (ISA triple
  registered, client builds against the nightly ROCm stack, operator flow
  rehearsed on a synthetic device). Silicon work pending.

## The plan

1. Build the agentic search engine — candidate generation, mutation,
   experiment-memory, convergence detection.
2. Maximise gfx90c against its hardware ceilings.
3. Validate the methodology on gfx902 — the pieces that must be derivable
   from hardware constraints, ISA capabilities and Tensile semantics alone.
4. Generalise: an explicit-constraint description of any AMD GPU the suite can
   natively reason against.
5. Open-source the suite and upstream the gfx90c tuning data.

## Getting started

```bash
python3 -m oto setup --yes   # prep toolchain + .env + client (easy mode)
python3 -m oto doctor        # honest status of the box
```

Then, reading from the same page:

```bash
python3 -m oto tune             # convergence loop (a TTY on the target GPU)
python3 -m oto tune --dry-run   # preview without touching anything
python3 -m oto check candidates --quiet
python3 -m oto verify all
python3 -m oto help
```

Full walkthrough (setup → bring-up → campaign):
**[docs/getting_started.md](docs/getting_started.md)**

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)**.

## Documentation

Birds-eye view of every document in the project:
**[docs/overview.md](docs/overview.md)**
(class-tagged registry: [docs/README.md](docs/README.md));
operator agents converge a library via [docs/operator_runbook.md](docs/operator_runbook.md).

## License

GPL-3.0-or-later — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
Code: GPL-v3. Docs: CC-BY-SA-4.0.

`oto` is named after the manul (*otocolobus manul*).
