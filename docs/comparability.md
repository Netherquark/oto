# Multi-run / single-run comparability — the like-for-like rule

**Status: triage complete; fixes landed in `f6aef2c` (R2-C7).** This doc records
what was wrong, what was fixed, how the rule works today, and what residual
gaps remain so nobody re-litigates or re-breaks it.

## Why this exists

The 2026-10-22 like-for-like regrade (potential_configs.md §R50) measured the
same kernel reading **2.1–4.2x differently** under a one-problem invocation than
under the family-wide one. A verdict pairing a 1-problem measurement against a
family-wide floor measures the *protocol*, not the kernel. Corpus-wide
verification on 2026-10-23 (all 3802 floor CSVs) showed every gfx900
reference-floor phase was invoked family-wide, so `family` is the graded basis
wherever a floor is compared against.

The analyzer's own advice from that regrade: §R53 — even a 3-problem "trio"
container is swap-prone across runs at fixed problem order (one DD trio read
77.8/19.6 from one run, 30.3/80.5 from another). Pairwise thinking does not
rescue partial forms either.

## The four invocation forms

Defined once in `oto/metrics/protocol.py` (`classify`, `protocol_of`,
`like_for_like`). A record carries its invocation form as `protocol`, stamped
by the kernel_db builder; the four forms:

| form | meaning | admission |
|---|---|---|
| `family` | one invocation covered every graded cell of the family (declared list wins, so a phase that lost a shape to a Tensile rejection still classifies by what it was ASKED to run) | **admitted** to graded bases |
| `single` | exactly one problem | config evidence only; never a graded basis against the floor |
| `partial` | more than one problem but not the family cell list (trio/pair containers, narrow spans) | excluded from graded bases |
| `unknown` | not derivable (registry-only rows without recorded shape lists; unattributable family; pre-protocol-stamp caches) | excluded from graded bases |

`PROTOCOLS` is the format. Do not invent new spellings.

## The rule, as enforced today

1. **kernel_db** stamps `protocol` per record (declared shapes win).
2. **`ab_records`/`ab_audit`**: when pairing an arm's best record for a cell,
   stamped protocols must match exactly (`like_for_like`); a stamped vs an
   unstamped record is honestly *unmatched*. Two never-stamped records fall
   back to the legacy count-equality check.
3. **`coverage_map`** admits only the family protocol by default
   (`--protocol`, default `family`); `--protocol any` opts out.
4. **`regression_matrix`** — every DB row is tagged with its run id; by
   default only `protocol == 'family'` rows are admitted (`--any-protocol`
   opts out). `meta` reports `protocol` and `excluded_protocol_rows`; each
   matrix entry carries its `deck` / `floor` / `all_time` run ids.
5. **`potential_configs_gen`** corpus section splits native vs floor counts.

## Bugs found in the triage and their disposition

| # | where | bug | fix (f6aef2c) |
|---|---|---|---|
| 1 | `oto/harness/regression_matrix.py` | every DB row admitted — single-problem rows (inflated 2-4x) won all-time cells and fed vs-floor verdicts | default like-for-like filter; `--any-protocol` opts out; rows tagged with run id; `meta` gains `protocol` + `excluded_protocol_rows`; entries carry `deck`/`floor`/`all_time` run ids |
| 2 | `oto/harness/occupancy_bounds.py` | hardcoded floor run id `gfx900_ref_locked_52149f315d` — a rename/vanish silently produced empty floor results | locked reference preferred, falls back to any `gfx900_ref_*` present, prints chosen runs; nonexistent floor → exit 1 with message; cache read uses a `with` handle |
| 3 | `oto/tools/potential_configs_gen.py` | corpus counts mixed native and floor sides | corpus section splits native vs floor counts |
| 4 | `oto/harness/candidate_pool.py` | mutable-fallback default argument | fallback normalised via `None` sentinel |
| 5 | `oto/harness/candidate_pool.py` | unused imports (`FAMILY_SHAPES`, `_pad_rows`) | dropped |

All of the above is pinned by `tests/test_comparability.py` (8 tests: admission
rule, floor discovery, run tagging, per-side counts).

## Residual state / known gaps (honest list)

* **Pre-protocol-stamp caches classify as `unknown`** and are *not* admitted to
  graded bases unless `--any-protocol` / `--protocol any` is passed. They still
  contribute to synthesis and config-evidence hunts, flagged `unknown`. We do
  not re-stamp them retroactively — a stamp would require the YAML
  `ProblemSizes` they never carried.
* **No runtime probe of the *current* GPU clock or clock-coverage floor is
  part of admission** — the like-for-like rule is about invocation width only.
  Clock-steadiness checks live elsewhere (`ab_delta` / `analytics`).
* **Floor identity is content-based, not id-based**: the floor is defined by
  the `gfx900_ref_*` runs present in kernel_db, locked first. If your kernel_db
  has no `gfx900_ref_*` runs, the audit exits 1 rather than silently grading
  against nothing.
* **`UNKNOWN` is not a verdict.** Tools surface it; nothing here asserts it
  matches or mismatches anything.

## How to re-check after touching any of this

```bash
python3 -m pytest tests/test_comparability.py tests/test_ab_audit.py tests/test_protocol.py -q
python3 -m oto.harness.regression_matrix --help           # must show --any-protocol
python3 -m oto.harness.regression_matrix [--any-protocol]   # admit non-family protocols only for deck generation
```

If you add a new DB-reading entry point, it must adopt the same default:
`family` admits, everything else abstains, `--any-protocol` opts out — and
it must report the chosen runs and the excluded row count.
