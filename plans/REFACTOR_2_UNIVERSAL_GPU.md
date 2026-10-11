# Refactor 2 — Universal GPU (arch-independent oto) Implementation Plan

**Status: IMPLEMENTATION PLAN (planning only, no code written).** This is the
end-to-end plan to make oto device-independent: the user provides an AMD GPU
codename + an API key, and oto auto-detects the hardware, synthesises a
device-specific docs ecosystem via two agents, and runs the full tuning
workflow against that device — with gfx90c as the first (and validation) target.

**Companion:** `REFACTOR_1_CODEBASE_ORG.md` (the device-agnostic re-organisation
this plan builds on). Execute Refactor 1 first; this plan assumes the `oto/`
package layout and the `oto/device/` seam exist.

---

## 0. The vision in one paragraph

oto today is a gfx90c program with a Tensile toolchain glued on. Every device
fact — 7 CUs, 1800 MHz, 64 KB LDS/CU, the FP64 1:16 rate, the family shapes,
the assembly gates — is a hardcoded constant in `gfx90c_common.py`,
`scheduler.py`, or `port_tensile.py`, and every device doc is a hand-maintained
gfx90c `.md`. The refactor makes **the device a data profile, not a code path**:
a `DeviceProfile` (loaded from a starter file the user fills in) drives the
gates, the ceilings, the family shapes and the docs. A user drops in a codename
+ API key + starter file, and oto (1) detects/validates the hardware, (2) runs
**agent-1** to write the device's theoretical-limits doc, (3) runs **agent-2**
to write the tuning-context doc, and (4) runs the whole existing workflow
against that profile. gfx90c becomes `profiles/gfx90c.json` — one target among
many — and the entire refactor is validated by proving gfx90c still behaves
exactly as it does today.

---

## 1. The core abstraction: `DeviceProfile`

A single frozen dataclass is the **only** place device facts live. Every gate,
ceiling, shape list and doc generator reads from it. No `gfx90c` string appears
outside `oto/device/` and the profile files.

```python
# oto/device/profile.py
@dataclass(frozen=True)
class DeviceProfile:
    codename: str                 # "gfx90c"
    isa: tuple[int, int, int]     # (9, 0, 12)
    num_cus: int                  # 7
    simds_per_cu: int             # 4
    lanes_per_simd: int           # 16
    max_waves_per_cu: int         # 40
    max_clock_mhz: int            # 1800
    lds_per_cu_kb: int            # 64
    l2_size_kb: int               # 1024
    vgpr_per_cu: int              # 65536
    has_mfma: bool                # False
    has_dp4a: bool                # False
    has_packed_bf16: bool         # False
    global_load_byte_cap: int     # 16
    peak_gflops: dict[str, int]   # {"FP32": 1613, ...}
    family_shapes: dict[str, list[int]]   # {"SS": [256, ...], ...}
    realistic_ceilings: dict[str, float]  # {"SS": 1118.7, ...}
    family_dtype_char: dict[str, str]     # {"SS": "S", ...}
    family_dtypes: dict[str, str]          # {"SS": "FP32", ...}
    family_bytes_per_element: dict[str, int]  # {"S":4,"D":8,"H":2,"C":8,"Z":16}
    # Assembly-gate policy (which dtypes allow GSU, VW floors, etc.)
    assembly_gates: AssemblyGatePolicy
    # The theoretical-limits data (memory roofline, boundary thresholds)
    theoretical: TheoreticalLimits
```

`AssemblyGatePolicy` and `TheoreticalLimits` are nested frozen dataclasses so
the gate logic and the doc generator read the same source of truth.

### 1.1 The profile is data, not code

`profiles/<codename>.json` is the on-disk form. `gfx90c.json` is generated
once from the current `gfx90c_common.py` constants (a one-time mechanical
extraction, verified by the test suite). A new device = a new JSON file + a
starter-file run; **no code changes**.

---

## 2. The starter file (user input)

The user provides a **starter file** (Markdown + a small YAML/JSON block) that
is the *only* per-device input a human writes. It is deliberately small — the
agents fill in everything else. Formalised contents:

```markdown
# <codename> starter

## Hardware (from rocminfo / rocm-smi / sysfs — required)
- codename: gfx90c
- isa: (9, 0, 12)
- num_cus: 7
- max_clock_mhz: 1800
- lds_per_cu_kb: 64
- l2_size_kb: 1024
- has_mfma: false
- has_dp4a: false
- has_packed_bf16: false
- global_load_byte_cap: 16

## Memory (required)
- type: DDR4 / HBM2 / ...
- bandwidth_gb_s: <measured or spec>
- coherent_host_access: false

## Workload (required — the cells oto must cover)
- families: [SS, DD, HH, CC, ZZ, HH_HPA, HS_HPA]
- family_shapes: {SS: [256, ...], ...}   # or "use the shipped gfx900 grid"

## API key (required for the doc agents)
- api_key: sk-...        # or $ENV_VAR name

## Optional overrides
- realistic_ceilings: {SS: 1118.7, ...}   # else agent-1 derives them
- spoof_reference: gfx900                # the floor to beat (default: none)
```

**Formalisation rules:**
- The YAML/JSON block is parsed by `oto/device/starter.py`; the Markdown is
  passed through to the agents as context.
- `family_shapes` may be `"shipped"` (use the reference library's grid) or an
  explicit list — this is the parity contract (knowledge_base §6.1), so it is
  always explicit.
- The API key is read from the block or an env var; it is never written to
  disk in the repo (the agents receive it in-process).

---

## 3. The two-agent docs ecosystem

The docs ecosystem splits into **general** (device-independent, versioned with
the code) and **device-specific** (generated per profile by the agents).

### 3.1 General oto docs (hand-maintained, in the repo)

`claude.md` (entry contract), `design_language.md`, `README.md`, the workflow /
methodology sections of `knowledge_base.md`, `implementation_plan.md` (the
*process*, not the gfx90c results), and the code-organisation docs. These
describe **how oto works** and never name a device constant.

### 3.2 Device-specific docs (agent-generated, per profile)

| doc | agent | contents |
|---|---|---|
| `<codename>_theoretical_limits.md` | **agent-1** | the device's ALU peaks, memory roofline, boundary thresholds, realistic ceilings — the acceptance bars. Generated from the starter file + first-party web research + (if available) a compile-only ISA oracle. |
| `<codename>_tuning_context.md` | **agent-2** | the tuning cookbook: knob surface, measured patterns, the ranked experiment plan, the resolution ladder. Generated from the theoretical-limits doc + the starter file + the research pass. |

**agent-1 (theoretical limits)** runs first. It:
1. reads the starter file's hardware block;
2. (API key) researches first-party specs (AMD product page, ISA reference,
   ROCm docs) for the codename — the same sources the gfx90c doc cites;
3. derives per-family ALU peaks from `num_cus × simds × lanes × clock × FMA`;
4. writes `<codename>_theoretical_limits.md` with the §0-§7 structure the
   gfx90c doc already has (so the acceptance bar is identical in form);
5. emits the `DeviceProfile` (ceilings, peaks, gates) as JSON for the code.

**agent-2 (tuning context)** runs after agent-1. It:
1. reads the theoretical-limits doc + the starter file;
2. (API key) runs the research pass (the `kernel_tuning_research.md` model:
   hardware model, LDS bank conflicts, occupancy theory, knob mechanics);
3. writes `<codename>_tuning_context.md` (the knob surface, M1-M4, measured
   patterns, the ranked plan) — the analogue of `gfx90c_tuning_guide.md`.

Both agents are **read-only on the repo's general docs** and write only their
device-specific doc + the profile JSON. The API key is used for the research
web-calls; no key material is persisted.

---

## 4. Codebase generalisation (file by file)

The rule: **a `gfx90c` / `5650U` / `1800` / `7` literal may not appear outside
`oto/device/` and `profiles/`.** Every current constant moves into the profile
or is derived from it.

| file | change |
|---|---|
| `gfx90c_common.py` | **Deleted.** Its contents split: device constants -> `profiles/gfx90c.json` + `DeviceProfile`; the generic resolvers (`kernel_typecode`, `family_from_kernel_name`, `cell_key`, `cube_side`, `shipped_cells`) -> `oto/device/resolvers.py` (device-independent). |
| `scheduler.py` | The gates take a `DeviceProfile` (dependency-injected). `LDS_BUDGET`, `VGPR_BUDGET`, `FAMILY_BYTES_PER_ELEMENT`, `MEASURED_VGPR` become profile fields. `assembly_class_valid`'s gfx90c rules (complex GSU, half GSU, VW floor) become `AssemblyGatePolicy` predicates parameterised by `has_mfma` / dtype. |
| `port_tensile.py` | `_write_phase_config` reads the profile for the gates; the `--arch` flag is replaced by auto-detection (§5). The `_TENSILE_VALID_PARAMS` set is already arch-independent (it's the Tensile param surface) — it moves to `oto/tensile/config_writer.py` unchanged. |
| `legality.py` | The manifest-derived prior is already device-independent (it reads the shipped manifest); it only needs the profile for the dtype tables. |
| `analytics.py` / `report.py` / `ab_audit.py` / `run_status.py` | Read ceilings / peaks from the profile instead of `gfx90c_common`. |
| `harness/*` | `kernel_db.py`, `generate_candidates.py`, etc. take the profile for family shapes / ceilings. |
| `db_mutator.py` | Already device-agnostic (reads kernel_db); no change beyond the profile seam for family shapes. |
| `mutator.py` / `agent.py` | No device constants; unchanged. |

The `MEASURED_VGPR` table is the one genuinely device-*measured* table. It
stays a measured constant but moves to `profiles/<codename>_measured.json`
and is loaded as profile data (it is re-measured per device by
`harness/measure_vgprs.py`, which already reads real Tensile output).

---

## 5. `port_tensile.py` universalisation (auto-detect + run)

The runner becomes arch-independent:

1. **Detect.** On startup, read the GPU codename from `rocminfo` (or accept
   `--codename`). Resolve the `DeviceProfile` from `profiles/<codename>.json`
   (falling back to the starter file if the profile is absent).
2. **Validate.** Cross-check the detected hardware against the profile
   (num_cus, clock, ISA). Mismatch -> warn and continue (the profile is the
   authority for ceilings; the detected HW is the authority for what runs).
3. **Run.** The entire existing pipeline (deck -> seed overlay -> A/B floor ->
   harvest -> mutate -> converge) runs against the resolved profile. The
   gfx900 reference-floor recall is parameterised by the profile's
   `spoof_reference` field (gfx90c uses `gfx900`; another device uses its own
   reference or none).
4. **No `--arch` flag.** The codename is an input (starter file / CLI), not a
   hardcoded branch.

---

## 6. Tests generalisation

The 26 test files are gfx90c-specific today (they assert 7 CUs, 1800 MHz,
gfx90c gates). Generalise by:

1. **Profile fixture.** A `tests/conftest.py` fixture loads `profiles/gfx90c.json`
   as the default profile; tests that assert device facts read the fixture, not
   literals.
2. **Parameterise the gate tests.** `test_occupancy_gate.py`,
   `test_legality_prior.py`, `test_cell_attribution.py` run against a
   `DeviceProfile` (gfx90c first, then a synthetic second profile to prove
   the gates are profile-driven, not hardcoded).
3. **The gfx90c suite is the regression.** The refactor is done when the entire
   gfx90c suite passes unchanged against the profile-loaded code — i.e. the
   profile reproduces today's constants exactly.
4. **A second profile** (e.g. a synthetic gfx906 or gfx900) is added to prove
   the gates generalise: the same tests run against it and assert the
   profile-specific outcomes.

---

## 7. Automated `potential_configs.md` generation (API key -> agentic consultations)

The user's end goal: *"ingest an API key from the user and automatically
generate a final potential_configs.md ... with least trial runs."* This is a
new **meta-agent** that orchestrates the whole campaign:

1. **Ingest** the starter file (codename + API key + hardware).
2. **Run agent-1** -> theoretical limits (§3.2).
3. **Run agent-2** -> tuning context (§3.2).
4. **Run the oto workflow** (deck -> seed -> A/B -> harvest -> mutate ->
   converge) against the profile, exactly as today but device-independent.
5. **Synthesise** the final `potential_configs.md` from the measured results:
   the verdict anatomy, the occupancy audit, the ranked plan — the sections the
   current hand-written `potential_configs.md` has, but generated from the
   run's own kernel_db + ledger, with the research citations the agents
   collected.

The meta-agent is a thin orchestrator: it calls the two doc-agents, then the
`oto.runners.auto` loop, then a `potential_configs` generator that reads the
run outputs. The "least trial runs" goal is served by the DB-hooked mutator
(Refactor: `db_mutator.py`) which guarantees novel, wall-targeted mutants every
iteration, so the campaign converges in fewer GPU-hours.

---

## 8. Migration plan (gfx90c first — the validation target)

The refactor is **tested on gfx90c** to prove no functionality is lost. Order:

1. **Refactor 1** (codebase org) — land the `oto/` package. gfx90c behaviour
   unchanged (675 tests green).
2. **Extract `DeviceProfile`.** Create `profiles/gfx90c.json` from the current
   constants. Route `scheduler.py` / `port_tensile.py` / `analytics.py` /
   `report.py` through it. **Gate: the gfx90c suite passes unchanged** — this
   proves the profile reproduces today's constants exactly.
3. **Generalise the gates.** `assembly_class_valid`, `occupancy_feasible`,
   `ldspad_feasible` take the profile. Add a synthetic second profile and
   parameterise the gate tests.
4. **Universalise `port_tensile.py`.** Auto-detect + `--codename`. Gate: a
   gfx90c run behaves identically to today.
5. **Delete `gfx90c_common.py`.** Its resolvers move to `oto/device/resolvers.py`;
   its constants live only in `profiles/gfx90c.json`. Gate: `grep -rn gfx90c
   oto/` shows hits only in `oto/device/`.
6. **Two-agent docs.** Wire agent-1/agent-2 to generate
   `gfx90c_theoretical_limits.md` / `gfx90c_tuning_context.md` from the starter
   file. Gate: the generated docs match the current hand-written ones in
   structure and acceptance bar.
7. **Automated potential_configs.** Wire the meta-agent. Gate: it produces a
   `potential_configs.md` for gfx90c from a fresh run.
8. **Second device.** Add a non-gfx90c profile (e.g. gfx900 or gfx906) and run
   the whole workflow against it. This is the proof of universality.

## 9. Acceptance criteria (end-to-end)

1. **gfx90c parity.** The entire current gfx90c workflow (deck, seed overlay,
   A/B floor, harvest, mutate, converge, report) runs against the profile-loaded
   code with **identical behaviour** — the 675-test suite passes unchanged.
2. **No device literals in code.** `grep -rnE "gfx90c|5650U|1800|NUM_CUS = 7"`
   over `oto/` returns nothing; device facts live only in `profiles/` and
   `oto/device/`.
3. **Auto-detect.** `port_tensile.py` detects the GPU codename and resolves the
   profile with no `--arch` flag; a wrong/mismatched profile warns.
4. **Starter-driven.** A new device is added by dropping a starter file +
   profile JSON into `profiles/` — **zero code changes**.
5. **Two-agent docs.** agent-1 + agent-2 generate the device docs from the
   starter file + API key; the acceptance bar is identical in form to today's.
6. **Automated potential_configs.** The meta-agent produces a final
   `potential_configs.md` from a run with the research citations attached.
7. **Tests generalised.** The gate/attribution tests run against two profiles
   (gfx90c + a synthetic) and assert profile-specific outcomes.

## 10. Risks and mitigations

- **The profile is only as good as the starter file.** Mitigation: agent-1
  validates the starter's hardware block against first-party research and
  flags contradictions; the detected HW is cross-checked at runtime.
- **The measured VGPR table doesn't transfer.** It is re-measured per device by
  `harness/measure_vgprs.py` (already device-independent — it reads Tensile
  output). Until re-measured, the profile carries a conservative default and
  the gates fail safe (refuse, never admit).
- **The gfx900 spoof-floor is gfx90c-specific.** It becomes the profile's
  `spoof_reference` field; a device with no reference runs native-only (the
  `--native` path that already exists).
- **Scope.** This is a large refactor. Mitigation: Refactor 1 first (mechanical,
  test-guarded), then the profile extraction (test-guarded by gfx90c parity),
  then the agents. Each step is independently shippable.
