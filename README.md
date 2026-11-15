# oto

**Recovering ROCm functionality for unsupported AMD GPUs.**

oto is a deterministic, benchmark-driven tuning suite that generates
optimised Tensile libraries for AMD GPUs that AMD no longer supports.
Its first target is **gfx90c** (Cezanne Vega 7); **gfx902** (Raven Ridge
Vega 8) is the cross-validation target. The end goal is a reusable
pipeline: any developer with a dropped AMD GPU can apply the same
process to their hardware without starting from scratch.

> *The goal is not just to make one GPU work; it is to build a method
> others can use when ROCm drops the next architecture.*

## Why

ROCm is the only credible open-source alternative to CUDA for GPU compute.
As it matures, AMD periodically drops support for older architectures.
Working hardware becomes software-stranded — not because it lacks compute,
but because the integration pathway is missing. No reproducible,
end-to-end reference exists for a modern Linux distribution.

GCN5 APUs are common in the Indian student and developer demographic,
and platform upgrades have been put on hold due to inflated GPU/RAM
prices. Ryzen laptops and desktops are widespread and affordable. The
existing community resources for getting ROCm working on this hardware
amount to fragmented Reddit threads and closed GitHub issues. This
project fulfils that gap in a way that outlasts the specific hardware:
the GCN5 case is the first traversal; **the methodology is the lasting
contribution.**

## What oto does

oto turns an unsupported AMD GPU into a native Tensile library through a
deterministic pipeline: profile the device, derive hardware ceilings from
first principles, generate a gate-legal candidate deck, benchmark under a
repeat-and-cooldown policy, harvest winners into an append-only SQLite
ledger, mutate, and converge. Every measurement, verdict and report is
reconstructible from that ledger. The library is the deliverable; the
method is the contribution.

The pipeline is a decision tree across recovery strategies — community
baseline workarounds, mixed-version stacks, containerised vendor stacks,
source builds — each isolating a different failure layer, each measured.
Start with the least invasive path, then escalate only when a step adds
diagnostic value.

## Status

- **gfx90c** (Ryzen 5 5650U, Vega 7, 7 CUs): ported, converged,
  library builds and dispatches under PyTorch. **20 WIN / 18 TIE / 0
  LOSS** against the shipped gfx900 floor.
- **gfx902** (Ryzen 5 2200G, Vega 8, 8 CUs): CPU-side pipeline ready
  (ISA triple registered, client built, toolchain contract formalised);
  silicon work pending the owner's API key and TTY.

## Quick start

```bash
python3 -m oto setup --yes          # prepare toolchain + .env + client
python3 -m oto doctor               # honest status of the box
python3 -m oto check candidates --quiet
python3 -m oto agent consult docs/<codename>_starter.md
python3 -m oto verify all
python3 -m oto help
python3 -m pytest -q
```

Full guide: [`docs/getting_started.md`](docs/getting_started.md).

## Documentation

See [`docs/overview.md`](docs/overview.md) for the full documentation map.

Class B (operator) agents: [`docs/operator_runbook.md`](docs/operator_runbook.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

GPL-3.0-or-later — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
Code: GPL-v3. Docs: CC-BY-SA-4.0.