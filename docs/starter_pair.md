# Adding a device: the Markdown+JSON starter pair

Refactor 2 turns oto into a device-independent port. A new device enters
through a **starter pair**, never through a code edit:

```
docs/<codename>_starter.md     narrative: what the device is, what you want
docs/<codename>_starter.json   facts: the profile oto loads
```

The markdown says who the device is; the JSON says what it is. Keeping the two
in one file would make either the prose or the machine facts unreadable.

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

`oto.device.loader.load_profile_from_starter()` enforces this: a mismatch is
a hard error, not a warning. Once the values are verified, the JSON half is
promoted to `profiles/<codename>.json` and oto's `--codename <codename>` path
works with zero code changes.

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

**Everything the agents write under `## Research (UNVERIFIED ...)` is
unverified.** The research path exists to *gather candidate facts*; it does
not write the profile. Numbers reach `profiles/<codename>.json` only after a
human checks them against first-party sources (AMD ISA reference, ROCm
release notes, the SKU spec sheet). An agent-researched profile that ships
unverified is a bug, not a feature.

## The gfx902 pair (you're verifying on gfx902 next)

`docs/gfx902_starter.md` + `docs/gfx902_starter.json` are the worked
example in this repo. What is known from public sources:

- LLVM's AMDGPU docs map `amdgpu9.02` to `gfx902` (xnack- and xnack+
  encodings exist), i.e. a Vega-ISA part — the GCN 5 family, same ISA
  lineage the gfx90c tuning work was done on.
- Public GPU tables list GFX902 as RAVEN (Raven Ridge / Picasso),
  used in Ryzen 2000/3000(G/GE) APUs.

Everything else — exact SKU CU count, clocks, peaks, family shapes —
is a **research question for the agents, verified by a human against
first-party sources**, then transcribed into `profiles/gfx902.json`.
The shipped `.json` stub deliberately fails the loader's unverified
-profile sanity check, so it cannot be tuned against by accident.

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
