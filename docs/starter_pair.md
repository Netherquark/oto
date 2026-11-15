# Adding a device: the Markdown+JSON starter pair

oto is a device-independent port. A new device enters through a
**starter pair**, never through a code edit:

```
docs/<codename>_starter.md     narrative: what the device is, what you want
docs/<codename>_starter.json   facts: the profile oto loads
```

The markdown says who the device is; the JSON says what it is. Keeping the two in one
file would make either the prose or the machine facts unreadable.

**This file is the master checklist for bringing a device up from zero.** Everything
on the "what must work" path is tagged **PROVEN**,
**BLOCKED** (needs the API key / human verification), or **UNPROVEN**
(silicon-dependent — never assumed). The order below is the order to walk.

## 0. The device-independent bring-up order

Any new device exercises the same gate path. The stages below land in the same order
regardless of the target part; their contents differ.

### Stage A — pre-flight (no GPU, no key)

| Step | Command | What it proves |
|---|---|---|
| A1 | `oto check candidates --quiet` | 280-row deck sane on the ambient profile (280/0 illegal today) |
| A2 | `oto agent consult` (on a stub pair) | Agent pipeline writes a gate-checked `potential_configs.md` |
| A3 | `oto agent index` | Docs index (`docs/docs_index.json`) regenerates |
| A4 | `oto doctor` | Honest status of `.env`/`TENSILE_ROOT`/`ROCM_PATH`/registry |
| A5 | `python3 -m pytest -q` | Suite is green; rehearsal suite covers the class-B path |

These steps are CPU-only and **already runnable**. If A1–A5 pass on your stub,
the repo is ready for a new-device campaign; nothing gfx902-specific has been
added to make that possible.

### Stage B — write the pair and load it

- `docs/<codename>_starter.md` — narrative identity + what you want; it
  loads as the device identity today.
- `docs/<codename>_starter.json` — facts. **A zeroed stub refuses to load**
  (`oto/device/loader.py:load_profile_from_starter` fails loudly). This is the
  gate.
- The agent prints a **directed** research prompt (see `oto/agents/context.guided_question`); with an `OTO_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` the agent fills an `UNVERIFIED` section — with none, the section is simply absent. The agent never invents facts.
- The stub also gates anything downstream: **A real-profile** path is not
  exercisable until the human says "this is an honest gfx902".

### Stage C — human verification gate

A human cross-checks **every** value against first-party sources (AMD ISA
manual, the SKU spec sheet, the rocminfo dump). Only after the human check does
the stub populate into a real profile; promotion to `profiles/<codename>.json`
is a manual copy made by the human.

### Stage D — build on the device itself (TTY only)

- `oto tune` — needs the device's GPU. This step is *never* run in a desktop
  session; it is for a TTY on the target machine.
- `oto report` — produces `<codename>_results/acceptance_report.{json,html}`.
- `oto check library-parity` — the 38/38-style check the reference device has.

**Each step above is expected on a fresh device**; none required code.

**BLOCKED items (true today):**
- `oto/device/tensile_isa.py:ISA_TRIPLES` — does not carry the gfx902 triple.
- `profiles/<codename>.json` — no real gfx902 profile on disk.
- No gfx902 silicon to run Stage D on. Nothing else is blocked.

**UNPROVEN (no claim, ever):** every assumption about gfx902's behavior in
Tensile — legal accepted knob sets, matrix legality, perf. Nothing in the repo
may claim silicon-dependent facts until the human check produces numbers.

## The sync rule

Both halves carry the codename, and they must agree:

```yaml
# <codename>_starter.md
codename: <codename>
```

```json
// <codename>_starter.json
{ "codename": "<codename>", ... }
```

`oto.device.loader.load_profile_from_starter()` enforces this: a mismatch is a hard
error, not a warning. Once the values are verified, the JSON half is promoted to
`profiles/<codename>.json` and oto's `--codename <codename>` path works with zero
code changes.

## Division of labor

| Half | Author | Content |
|------|--------|---------|
| `.md` | you (+ agent research) | codename, target SKU, what the tuning run is for, known quirks, API-key *reference* (env var name, never the key) |
| `.json` | you (+ agent research), then **you verify** | full profile schema (see `profiles/gfx90c.json` for a complete example): ISA tuple, CU count, clocks, LDS, peaks, family shapes, ceilings |

## Getting the facts with agent research

`oto agent generate` runs two doc agents against the pair:

* **agent-1** (`oto/agents/theoretical_limits.py`) — emits
  `<codename>_theoretical_limits.md` (peaks, ceilings, hardware section),
* **agent-2** (`oto/agents/tuning_context.py`) — emits
  `<codename>_tuning_context.md` (knob surface, family shapes).

Research is auto-enabled when an API key is visible in the environment:

| Key in env | Backend | Web research |
|------------|---------|--------------|
| `ANTHROPIC_API_KEY` (or `sk-ant-` prefix) | Anthropic Messages API | server-side `web_search` tool (up to 8 uses) |
| `OPENAI_API_KEY` (or other `sk-` token) | OpenAI chat completions | `gpt-4o-mini-search-preview` (override with `OTO_API_MODEL`) |
| `pplx-` prefix | Perplexity chat completions | `sonar` (override with `OTO_API_MODEL`) |
| `OTO_API_KEY` | whatever it looks like, or `OTO_API_ENDPOINT` if set | follows the same rules |

`OTO_API_ENDPOINT` (explicit) always wins; `OTO_API_MODEL` always overrides
the default model; `OTO_API_TIMEOUT` (default 60 s) and
`OTO_API_MAX_TOKENS` (default 2048) tune the call.

**Everything the agents write under `## Research (UNVERIFIED ...)` is unverified.**
The research path exists to *gather candidate facts*; it does not write the profile.
Numbers reach `profiles/<codename>.json` only after a human checks them against
first-party sources (AMD ISA reference, ROCm release notes, the SKU spec sheet). An
agent-researched profile that ships unverified is a bug, not a feature.

## Stage A–D worked example

For this repo, the worked example is the gfx90c family — see `profiles/gfx90c.json`
and the docs here. New devices follow the same Stage A–D walk.

`docs/gfx902_starter.md` + `docs/gfx902_starter.json` are a stub for a device
oto has neither measured nor validated; they exercise the unverified-refusal path.
See `docs/starter_template.md` for a blank template example.

## Minimal recipe

1. Copy `docs/starter_template.md` and `docs/starter_template.json` to
   `docs/<codename>_starter.{md,json}`.
2. Fill the markdown (what you want from the device, known quirks).
3. Fill the JSON with values you can verify, or leave a stub and research:

   ```
   python3 -m oto agent generate docs/<codename>_starter.md
   ```

4. Transcribe the verified facts from the `## Research (UNVERIFIED ...)`
   sections into the JSON; cross-check every number against a first-party
   source; delete nothing until the JSON loads:

   ```
   python -c "from oto.device.loader import load_profile_from_starter; \
              print(load_profile_from_starter('docs/<codename>_starter.md'))"
   ```

5. `mkdir -p profiles && cp docs/<codename>_starter.json profiles/<codename>.json`
   only after verification. From then on `--codename <codename>` works.
6. Verify end to end on the device itself in a TTY (never inside a
   Wayland desktop session): the tuning run, the report, the library.

## What this deliberately does not do

* It does not invent silicon facts. Empty/unverified fields are marked
  in the JSON by omission; the loader fails loudly on missing keys.
* It does not trust agent output. UNVERIFIED sections are inputs to your
  judgement, nothing else.
* It does not run on a device it cannot see. CPU-only steps (doc generation,
  profile synthesis, gates, tests) are fine anywhere; actual tuning runs belong
  in a TTY on the target machine.

## The bring-up gate, restated

```
   A1  Deck sanity                         — anywhere, no key
   A2  Agent consult                       — anywhere, no key
   A3  Agent index                         — anywhere
   A4  Doctor reports honestly             — reports what is present
   A5  pytest green                        — gates every edit
  ─────  human verification gate  ─────
   C   VERIFIED profile promoted           — a human decision
  ─────  device runs in a TTY only ─────
   D   tune / report / parity              — TTY-driven, GPU-required
```

A new device is ready when Stage A passes on its stub and the silicon is
verified to behave. Everything between is a human's call.
