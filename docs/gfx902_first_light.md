# gfx902 First-Light Checklist — what is proven, what is blocked

> **Read once before any gfx902 step.** This file is the day-one inventory.
> Nothing in it invents silicon facts. Each item is tagged:
> **PROVEN** = runs green in this repo today on a synthetic profile;
> **BLOCKED** = waiting on a human decision / API key;
> **UNPROVEN** = unverified against actual silicon, must not be treated as fact.

The whole gfx902 path depends on one unclear fact: AMD has never shipped a
production Tensile library for this part. Every assumption about Tensile's
behaviour on gfx902 is therefore UNPROVEN until a real Tensile build proves or
refuses it.

## 1. The pre-flight (already closed)

- Deck sanity: `oto check candidates --quiet --base <stub>` — PASS (280 rows, 0 illegal). **PROVEN**
- Routing: `oto agent consult` — runs on stub pair today; emits `<codename>_potential_configs.md` with gate-checked ladder rows. **PROVEN**

## 2. The starter pair (gate-destroyed for handanoosh today)

- `docs/gfx902_starter.md` — narrative stub with public-ISA facts; no silicon facts. **PROVEN** — loads fine
- `docs/gfx902_starter.json` — ZEROED stub; `oto/device/loader.py:load_profile_from_starter` refuses placeholders — **PROVEN** — blocked on human review
- ISA gating in `oto/checks/tensile_build_probe.py:_pin_isa` — **PROVEN** — refuses unknown archs loudly

## 3. The agent pipeline (run one stage at a time)

- `oto agent index` — works, writes `docs/docs_index.json`. **PROVEN**
- `oto agent generate <starter.md>` — produces `<codename>_theoretical_limits.md` + `<codename>_tuning_context.md` + `<codename>_harness_study.md` + `<codename>_docs/potential_configs.md` on a stub pair. **PROVEN**
  - Fails loudly (no API key) if research is called — ok, agent always runs with UNVERIFIED tags
- `oto agent consult <starter.md>` — gate-checked ladder, census priors absent on fresh clone. **PROVEN**

## 4. Library build (blocked on ISA / can't-verify)

- `oto library best-effort` — will NOT produce a library for gfx902 today; the stage refuses with an actionable ISA message if the arch isn't in Tensile's ISA table. **PROVEN** as a gate (refuses loudly)
- `oto check tensile-build` — same gate; requires the `oto/device/tensile_isa.py:ISA_TRIPLES` entry for gfx902. **PROVEN** refusal path

## 5. Benchmark campaign (blocked on GPU + key)

- `oto tune --budget N --yes` — **NOT RUN**; GPU path off this box without owner consent
- `oto report --json` — **NOT RUN** on gfx902; rehearsed on stub only
- `oto check library-parity` — **NOT RUN**; no TensileLibrary exists for gfx902

## 6. Acceptance / reporting

- `oto report` — produces `<codename>_results/acceptance_report.{json,html}` on stub stubs. **PROVEN**
- `oto stats` — runs, produces an empty table on fresh clone. **PROVEN**

## 7. The publish gates (blocked on key)

- `oto doctor` — reports honestly; on a fresh clone with no key it passes `check health` and fails `GPU device nodes` and `Tensile client`. **PROVEN** as a diagnostic
- `python3 -m pytest -q` — 1102 passed, 8 skipped, 242 subtests. **PROVEN** as the gate

## 8. Release checklist (blocked on owner wins)

- `requirements-dev.txt` pinned. **PROVEN**
- `NOTICE`, `CONTRIBUTING.md`, `SECURITY.md`, `CODEOWNERS` — present. **PROVEN**
- LICENSE verbatim GPL-3.0. **PROVEN**
- `git tag v1.0.0`, `git push` — **blocked on owner's word**

## 9. gfx902-specific blockers (in priority order)

| item | status |
|---|---|
| `oto/device/tensile_isa.py:ISA_TRIPLES` gfx902 triple | **blocked** on Tensile-side |
| `oto/device/loader.py` sanity gate for gfx902 | **PROVEN** — rejects unverified stubs |
| `oto/tensile/gates/*` profile threading | **PROVEN** (gate-differential 113776 cmp, 2026-11-15) |
| `oto/tensile/shipped_floor_manifest.py` gfx902 lookup | **NOT PROVEN** — path exists, no manifest |
| `oto check candidates` against a *synthetic gfx902* profile | **PROVEN** on a stub: passes; real profile not verified |
| Agent prompt-engineering for gfx902 | **PROVEN** — directed ISA-following questions landed |
| docs/gfx902_starter.* stub refusal | **PROVEN** — stub refuses to load |

## 10. What the operator does on day trip

1. `rocminfo | grep -E 'Name|Chip ID'` → write down exactly what
2. `docs/starter_pair.md` → write narrative
3. `oto agent generate docs/gfx902_starter.md` (no key needed)
4. Verify every number against first-party sources
5. `oto agent consult docs/gfx902_starter.md --force`
6. `oto check candidates --quiet`
7. `oto tune --yes --budget 3` (TTY)
8. `oto report`

Steps 1–6 are CPU-only and have been exercised on synthetic stubs here; step 7
requires a live GPU the repo has not seen.
