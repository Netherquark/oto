# Docs ecosystem audit — what to whittle, remove, or move to docstrings

**Status: PROPOSAL. Nothing here has been applied — except the factual
corrections listed in §7**, which were made on 2026-10-12 while finishing
Refactor 1 (stale module names/paths and forbidden corpus counts; no structural
whittling). Each item names a file, a line range, the fact it currently states,
and what should happen to it. The boundary being applied is `docs/README.md`:

> If the fact would still be true after the code were rewritten in another
> language, it belongs here. If it is a fact about *this* function's
> contract, it belongs in the docstring.

Three dispositions are proposed:

* **DOCSTRING** — the fact describes a code contract (a return value, a field
  name, a module's contents, a knob a function forwards). It should move into
  the module it describes.
* **TRIM** — the fact is true but no longer load-bearing, or duplicates the
  owner MD. Reduce to a pointer.
* **ARCHIVE** — the fact is historical narrative. History has two homes
  (`changelog.md` and the frozen `prior_*` files, per `claude.md` §8.1). Remove
  from live docs.

Ordered by risk: TRIM and ARCHIVE first (deletions), then DOCSTRING (moves),
because a move needs a docstring to move *into*.

---

## 1. TRIM — duplicates (same fact, two homes)

`claude.md` §3 already names one canonical home per MD. Every item below is a
fact that currently has two.

### 1.1 `knowledge_base_final.md` vs `knowledge_base.md` — the whole file

`knowledge_base_final.md` (506 lines) and `knowledge_base.md` (603 lines) both
claim to be the baseline knowledge base. `claude.md` §3 does not list
`knowledge_base_final.md` at all, which means it is an orphan nobody owns.

* **Proposal: ARCHIVE `knowledge_base_final.md` in full.** It is dated
  "loaded 2026-09-15" in its own header (line 5) and every table in it is
  superseded: §3.2 quotes `port_tensile.py` at "1,362 lines (53KB)" (line 83)
  when the file is now 3,626; §5.1 quotes best-performance figures that
  `results.md` §2 owns; §11 is a complete `--auto` post-mortem that
  `results.md` §10–12 now covers. Move the two facts that have no other home
  into their owner (§4.3's corpus shape → `results.md` §1; §10's V1–V10 chart
  specs → delete, they were never built) and delete the file.
* **Risk: none** — nothing imports it and no test reads it.

### 1.2 `README.md` `## 4. Module Overview` (L217–233) and `## 5. Validation Tools` (L235–284)

A file inventory and a CLI catalogue, both in README prose. The inventory is
wrong the day the package changes: it names 11 flat root modules
(`port_tensile.py`, `scheduler.py`, …) that no longer exist at those paths after
the `oto/` package split.

* **Proposal: DOCSTRING.** Replace both sections with a pointer to
  `oto/README.md` (new — a generated package map) plus the two invocations an
  operator actually needs (`python3 port_tensile.py --help`,
  `python3 check_candidates.py --help`), which cannot go stale because they are
  answered by argparse at runtime.
* Keep `## 5`'s "CPU-only, no GPU needed" framing — that is a project fact (no
  benchmark run during code development, `claude.md` §5) that no code file
  states.

### 1.3 `README.md` `## 2. Driver Architecture` (L21–83)

Describes the 7-stage internal pipeline in prose + ASCII, naming the module that
implements each stage, and transcribes the manifest phase counts
(`L28: "(434 phases: SS 105 · HH 40 · …)"`).

* **Proposal: TRIM to the diagram only.** The stage list survives because it is
  the shared vocabulary every other MD uses ("Stage 6", "Stage 7"), but the
  per-stage module attribution is a code fact — after the split those
  attributions are `oto/runners/*` and are documented in each module docstring.
* **Delete line 28's phase-count parenthetical.** It is a corpus count
  transcribed into prose, which `claude.md` §5 explicitly forbids, and it is
  already stale (the live manifest is 418 lines, not 434 phases).

### 1.4 `implementation_plan.md` `## The Driver Architecture` (L226–413) and `### 1`–`### 7` (L415–523)

This is a ~300-line internal design spec for a module that now exists and has
docstrings. `L452: "| CLI | argparse + one port_tensile.yaml | stdlib argparse |"`.

* **Proposal: ARCHIVE, keeping §4 (reference-floor contract) and §6 (migration
  order).** §4 is still load-bearing: the floor-is-recalled-never-re-run rule
  is a correctness contract. §6 ("do not rewrite blind") is still the rule the
  refactor followed. The seven stage subsections and the seven design subsections
  are now the module docstrings of `oto/runners/*` — they should be checked for
  facts the docstrings do not yet carry, those facts moved in, and the sections
  deleted.
* The ASCII flowchart at L290–413 is the one part with no natural docstring
  home; it is genuinely a project-level orientation artifact. **Keep it.**

### 1.5 `implementation_plan.md` `## Triaged fixes` (L526–628) and all of `## Option H` (L631–1115)

A register of code bugs keyed to code locations. `L563-565` names
`_write_phase_config` and `execute_phase`; `L575` names
`CandidateGenerator._estimate_occupancy`; `L706` quotes `scheduler.py:379`.

* **Proposal: ARCHIVE the triage, keep the rule.** Each entry is a fixed bug
  and its fix; the fixes are in the docstrings now, and the post-mortems
  belong in `changelog.md`. What survives here is the *rule* each entry
  established (e.g. "the same problem has bitten twice, so add a test"), and
  those rules are already in `claude.md` §5.
* `Hplan.9 Exit criteria` (L1037–1076) and `Hplan.7 Acceptance criteria`
  (L1017–1029) are live gate definitions, not history. **Keep those two.**

### 1.6 `results.md` `## 10` (L114–250) and `## 9`/`## 11`

`results.md` is the "measured evidence" ledger and it now contains 200+ lines
of code post-mortem. `L108` explains a `_write_phase_config` early-return;
`L122-124` explains an arm-scope asymmetry; `L134-137` explains a delta bug;
`L148` lists the eight `--native-agg` bases.

* **Proposal: split the file at the seam.** The *numbers* (what was measured,
  what the verdict was) stay — that is `results.md`'s sole purpose. The
  *mechanism* paragraphs (why the arm diverged, what the bug was) move to
  `changelog.md` as entries dated with the fix. `L148`'s basis list is a code
  contract and belongs in `oto/metrics/ab_delta.py`'s `_stat` docstring —
  where it already lives.
* The `## 9` and `## 11` root-cause paragraphs follow the numbers in both
  cases; only the root-cause sentence is code documentation, and it is already
  in `ab_audit.repeat_dispersion` / `occupancy_feasible`. Trim those two
  paragraphs to a pointer.

### 1.7 `gfx90c_tuning_guide.md` `## 1. Knob surface` (L21–41)

Column 4 of this table is literally the code that implements forwarding:
`L23: "| knob | what it does | legality gate | forwarded by `_write_phase_config` |"`,
and cells say `"yes (NEW, Group C)"`.

* **Proposal: DOCSTRING.** The whole table moves to `oto/tensile/config_writer.py`
  as the module docstring of the fork-parameter section — the file already owns
  every one of these facts and already has a comment per knob. Keep in
  `gfx90c_tuning_guide.md` the *tuning* read (which knob matters, in which
  regime), which is §4 and §5 and is not a code fact.
* Same for `## 6. Occupancy model vs emitted reality` (L148–174): the model is
  `oto/tensile/gates/occupancy.py`'s docstring already. Keep the measured
  table.

### 1.8 `knowledge_base.md` `### 9.1` (L440–459), `### 9.2` (L461–478), `## 10.2` (L525–552)

JSON field semantics, a background-thread repainter's `BaseException` catch,
and a database table schema. `L445-448` is a field table; `L466-467` explains
why the thread exists; `L531-532` describes the `records` table.

* **Proposal: DOCSTRING for §9.1/§9.2.** Field semantics live in
  `oto/metrics/report_models.py`; the live panel's thread and `BaseException`
  rationale is already in `oto/metrics/render_status.py`'s `LiveStatus`
  docstring. §10.2 (append-only mechanics) is the **exception**: it is the
  canonical statement of the Data Preservation Law and `claude.md` §5 names it
  as such. **Keep all of §10.2.**

### 1.9 `potential_configs.md` — two sections numbered "5", two numbered "2"

`## 2. Per-cell evidence` (L154) vs `## 2. gfx90c impossible-underperforming configs` (L70);
`## 5. Mutation strategies` (L412) vs `## 5. Kernel-type patterns` (L384).

* **Proposal: TRIM.** Renumber §2 (L154) → §2b or fold it into §3, and renumber
  the second §5 (§412, the db_mutator strategies) → §6 while the existing §6
  (Candidate deck, L489) → §7. The numbering collision makes the file
  uncitable: "potential_configs.md §5" is ambiguous today.

### 1.10 `potential_configs.md` §8.1 (L582) and §8.4 (L638)

`L584: "Legality is dtype-locked (`scheduler.assembly_class_valid:1408–1457`)"` —
a source file and a line range in prose. `L639` describes compiler codegen.

* **Proposal: DOCSTRING.** The line range is not just stale, it is now wrong
  (the function moved to `oto/tensile/gates/assembly.py`). The legality rule it
  points at is already that module's docstring. Replace with a pointer.
  *(Module name corrected on 2026-10-12, line range dropped; §7.)*

### 1.11 `oto/harness/README.md` — a runbook in neither system

`claude.md` §3's ownership table does not list it, and `docs/README.md` defines
the ecosystem as "this directory + the root `*.md` files", so a hand-written MD
under `oto/` is owned by nothing. Paragraph by paragraph:

* **L1–8 intro** — "the machinery that was built ad-hoc in `/tmp` (now deleted
  as a source of truth)". The `/tmp` history is **ARCHIVE** (→ `changelog.md`);
  the "CPU-only, never benchmarks" contract restates `claude.md` §5 — **TRIM to
  a pointer**.
* **`## Layout` (L10–25)** — a hand-maintained module inventory plus cache
  paths. This is exactly what `oto/README.md` now generates and what §1.2 moved.
  **DOCSTRING/TRIM**: module list → `oto/README.md`; keep only the cache paths
  (data artifacts, not code facts).
* **`### 1`–`### 5` workflow (L27–127)** — a genuine operator runbook with no
  code-file home. **Keep**, after the 2026-10-12 path fix.
* **L68–72 "Published state (2026-10-07): 16 wins / 13 ties / 9 losses …"** —
  dated measured state, which `results.md` owns. **ARCHIVE → `results.md` /
  `changelog.md`**, leave a pointer.
* **L19 / L101 "38-cell" / "38 shipped cells"** — a corpus count; `results.md`
  §12 owns the number. **TRIM to a pointer.**
* **L110 "45/45 rows pass today"** — a live count. **Delete.**
* **Ownership: either move this file under `docs/`** (and add it to
  `docs/README.md`), or extend `claude.md` §3 to name it as the harness package's
  runbook. Today it is an orphan.

### 1.12 `incomplete_work.md` — history in the open-work register

`claude.md` §3 names this file's sole purpose as "Open-work register
(status-keyed)", but §4.3–§4.13 are *RESOLVED* dated post-mortems. `claude.md`
§8.1 puts history in `changelog.md`.

* **Proposal: ARCHIVE §4.3–§4.13 to `changelog.md`.** Keep §4.14–§4.16 (still
  cited by the floor/hold decisions) and §5.1 (live Refactor 1 status and the
  function-length backlog). The file then means "open work" again.
* These historic blocks also carry deleted module names (`scheduler.py`,
  `gfx90c_common.py`, `telemetry.py`, `registry.py`, …). **Archive rather than
  rename** — renaming keeps dead narrative alive and is churn.

### 1.13 `claude.md` `## 3` — the ownership table is stale

The table *is* the routing contract, so a wrong row routes an agent to the wrong
home.

* **L73 lists `scratch.md`, which does not exist** in the tree. Delete the row.
* **The table omits four live MDs** — `gfx90c_tuning_guide.md`,
  `kernel_tuning_research.md`, `complex_gemm_research_brief.md`,
  `knowledge_base_final.md` — plus the user-only `todo.txt`/`command.txt` and the
  intentionally-untracked `proposal.md`. Add a sole purpose for the three that
  stay (do **not** add `knowledge_base_final.md`; §1.1 archives it).
* **L82 names `docs/design_language.md` while the file is still at root** —
  reconcile with §2.5's move.
* Otherwise **keep the whole file**; §2.1/§3/§5/§8.1 are in §5's do-not-touch
  list.

### 1.14 `complex_gemm_research_brief.md`

* **§1–§5 (L11–80)** — Tensile complex-MAC instruction counts. **DOCSTRING** into
  `oto/tensile/gates/assembly.py` (the complex rules); the MD keeps a pointer.
  (Already a row in §3.)
* **§6 (L82–91) "Measured gfx90c complex GEMM (first-party, this repo)"** —
  measured evidence, which `results.md` owns. **TRIM to a pointer.**
* **§7–§8 (L93–120)** — external 2023–2026 history and "exotic paths against the
  4-FMA wall". Genuine research with no code home; **keep** (trim the survey to
  the load-bearing conclusions) or archive if `assembly.py`'s docstring already
  states them.

### 1.15 `docs/` self-reference — the audit quotes line numbers

`docs/README.md` forbids quoting a line number anywhere in the ecosystem, yet
this audit keys almost every item to a line range (`L217–233`, `L21–83`, …).
That is tolerable for a *working* audit, but **every range goes stale the moment
a section is edited** — this pass moved `README.md` §2 and replaced §4, and §1.2
/§1.3/§4 now name ranges that no longer match. Before this proposal is actioned,
replace each `L…` with a section anchor (`## 4 Module Overview`) so the audit can
survive its own edits.

---

## 2. ARCHIVE — historical narrative in live docs

`claude.md` §8.1: "History has exactly two sanctioned homes: `changelog.md`
(append-only) and the frozen `prior_*` files. Live docs state current fact only."

### 2.1 `implementation_plan.md` `### A. Frozen baseline` (L74–81) and `### Technical findings (2026-09-19)` (L211–224)

Both state what a dated past run proved. The 0/11/0 parity pair and the HS_HPA
rejection root cause are conclusions with dates attached.

* **Proposal: ARCHIVE to `changelog.md`.** Keep the suspension value (the A–G
  suite verdict list, the HS_HPA `SolutionStructs` GLVW cause) — those are
  load-bearing rules — but move the run identifiers and dates.
* **Careful: do not archive `### B. The replicated footprint` (L83–90).** The
  2,285-kernel number is a *current* contract fact and `mapping.md` §1 already
  owns it; this section is a duplicate and should be trimmed to a pointer, not
  archived.

### 2.2 `knowledge_base.md` §8.2 `### Config legality is a 4-gate preflight` (L405–424)

Describes the four gates and the `overflowedResources == 4` failure.

* **Proposal: DOCSTRING + TRIM.** The gate semantics are now
  `oto/tensile/gates/*/__init__`'s job and each gate module documents itself.
  What is worth keeping in prose is the *routing* ("a phase dying with
  `Generating kernel source resulted in error 4` is a legality-gate miss, not
  bad luck") — that is in `claude.md` §2.1 already. **Trim to a pointer.**

### 2.3 `adversarial_review.md` `## 2` (L67–92) and `## 3` (L94–116)

A code-audit register by charter, but written as implementation constraints
("byte = `json.dumps(dict)` through the single append path", "exactly one
`append_record()`").

* **Proposal: DOCSTRING for §2, keep §3.** §2's eight prohibitions are the
  architecture rules of `oto/ledger/registry.py`; move them there and trim §2 to
  the four that are *policy* rather than code (no `printf` JSON, no fork-lock,
  no inferred controls, no self-terminating run-all). §3's checklist is a
  live audit procedure with no docstring home. **Keep.**

### 2.4 `tensile_tuning_context.md` — the whole file (85 lines)

A focused philosophy doc. §Scope, §Core Strategy, §AI Must Not Decide,
§Correctness Gate, §Reward Hacking are each a single paragraph of genuinely
load-bearing project philosophy. But `implementation_plan.md` §Objective,
§AI Must Not Decide, §Correctness Gate and §Reward Hacking state the same
paragraphs.

* **Proposal: keep the file, TRIM `implementation_plan.md`'s copies to
  pointers.** This file is the concise statement and is the better home; the
  plan is allowed to cite it. **Do not merge in the other direction** — that
  would put philosophy in a plan that is supposed to be executable.

### 2.5 `design_language.md` — the whole file (463 lines)

A design-language spec for the HTML report. It is not code documentation and
not project documentation: it is the visual contract of one artifact.

* **Proposal: keep, but move it under `docs/`** (→ `docs/design_language.md`)
  and add the pointer to `docs/README.md`'s owner table. Its `## Output`
  section (L457–462) is an instruction to a code generator and should be
  deleted — that is a prompt fragment, not a project fact.
* The acceptance-report colour mapping at L210–211 names
  `report.py _cell_status_section`. **DOCSTRING** that mapping into
  `oto/metrics/cell_status.py`; L210–221 becomes a pointer.

### 2.6 `gfx90c_theoretical_limits.md` §1 `DataType` sub-block (L39–47)

`L40-44` quotes `Tensile/DataType.py` directly, and `L46` calls out
`oto.tensile.gates.vgpr_model.FAMILY_BYTES_PER_ELEMENT` as wrong.

* **Proposal: DOCSTRING + TRIM.** The byte-width table is
  `oto/tensile/gates/vgpr_model.py`'s docstring already (it says "do not
  hand-edit without updating the test"). `L46`'s "and is wrong" claim is now
  false — the table was fixed to `ZZ: 16` — so that sentence must be deleted
  before it misleads a reader into re-fixing a fixed thing.

---

## 3. DOCSTRING — facts that belong inside the code

These are not deletions; each is a move. For each, the fact should land in the
docstring of the module that owns it, and the MD should keep a one-line pointer.

| From | Lines | Fact | Lands in |
|---|---|---|---|
| `README.md` `## 2` | 21–83 | per-stage module attribution | `oto/runners/__init__.py` |
| `README.md` `## 4` | 217–233 | module inventory | `oto/README.md` (generated) |
| `README.md` `## 5` | 235–284 | tool exit contracts | each `oto/checks/*` and `oto/tools/*` docstring |
| `README.md` `## 7` | 299–315 | `.env` key table | `oto/runners/toolchain.py` |
| `impl_plan` stages | 228–289 | stage scope | `oto/runners/{driver,phases,reference,auto,reporting,cli}.py` |
| `impl_plan` `### 2` | 436–455 | do-not-reinvent table | `claude.md` §5 (already there); TRIM the copy |
| `impl_plan` `### 7` | 512–523 | on-disk artifact layout | `oto/ledger/registry_core.py` |
| `impl_plan` Triaged | 526–628 | bug register | `changelog.md` (ARCHIVE) + docstrings |
| `impl_plan` Option H | 631–1115 | ledger design | `oto/ledger/*` docstrings; keep §7/§9 |
| `kb_final` `### 3.x` | 65–113 | architecture + file inventory | whole file ARECHIVED |
| `kb_final` `## 8` | 300–314 | dependency graph | `oto/README.md` (generated) |
| `knowledge_base.md` `### 9.1` | 440–459 | JSON field semantics | `oto/metrics/report_models.py` |
| `knowledge_base.md` `### 9.2` | 461–478 | live panel internals | `oto/metrics/render_status.py` |
| `results.md` `## 9/10/11` | 103–288 | code root causes | `changelog.md` + the gate docstrings |
| `tuning_guide` `## 1` | 21–41 | knob forwarding table | `oto/tensile/config_writer.py` |
| `tuning_guide` `## 6` | 148–174 | occupancy model | `oto/tensile/gates/occupancy.py` |
| `tuning_guide` `## 7` | 176–191 | `check_candidates --floor` mechanics | `oto/checks/candidates.py` |
| `tuning_guide` `## 8` | 193–210 | cell_knob_diff output | `oto/harness/cell_knob_diff.py` |
| `potential_configs` `§5.1–5.5` | 412–486 | db_mutator strategy mechanics | `oto/tensile/synthesis/db.py` |
| `potential_configs` `§8.1/§8.4` | 582–643 | legality line ranges | `oto/tensile/gates/assembly.py` |
| `adversarial_review` `## 2` | 67–92 | 8 code prohibitions | `oto/ledger/registry_core.py` |
| `design_language` L210 | 210–221 | cell colour mapping | `oto/metrics/cell_status.py` |
| `theoretical_limits` L39 | 39–47 | element byte widths | `oto/tensile/gates/vgpr_model.py` |
| `kernel_tuning_research` `### 2.3/3.3/§4` | 49–92 | Tensile knob mechanics | `oto/tensile/gates/*` + `config_writer.py` |
| `complex_gemm_brief` `## 1–5` | 11–80 | complex MAC instruction counts | `oto/tensile/gates/assembly.py` (the complex rules) |

`kernel_tuning_research.md` §1 (hardware model) and §2.1 (bank-conflict
formula) are **not** code documentation — they are sourced hardware facts and
should stay. Only the "what Tensile actually does" paragraphs describe a code path.

---

## 4. Numbers transcribed into prose

`claude.md` §5 forbids writing a corpus count down "anywhere". These are the
ones currently in the docs ecosystem:

| File | Line | The number | Disposition |
|---|---|---|---|
| `README.md` | 28 | "434 phases: SS 105 · …" | **APPLIED** (§7) — live manifest is 418 lines |
| `README.md` | 250 | "434 checked, 0 illegal" | **APPLIED** (§7) — `check_candidates.py` prints it live |
| `impl_plan.md` | 29 | per-family phase counts | delete, point at `allruns.py` |
| `impl_plan.md` | 84 | "2,285 kernels" | **keep** — `mapping.md` §1 owns it and it is a contract |
| `impl_plan.md` | 774 | "53-case test" | keep (a test count, not a corpus count) |
| `kb_final.md` | 5 | "3,208 measurements / 320 cells" | archived with the file |
| `potential_configs.md` | 57 | "19 WIN / 18 TIE / 1 LOSS" | keep — `results.md` §12 owns it; this is a citation |
| `potential_configs.md` | 154 | "38 cells" | duplicate of §57; trim to a pointer |
| `results.md` | 101 | "1,881/404 = 2,285" | keep — chain totals |
| `tuning_guide.md` | 264 | "335-phase sizing" | **delete** — the number moved |
| `results.md` | 245–251, 283–288 | `<!-- DERIVED:… -->` placeholders | **delete** — five placeholders that nothing fills |

---

## 5. What must NOT be touched

Called out explicitly because each looks deletable and is not:

1. **`knowledge_base.md` §10 in full** — the Data Preservation Law. `claude.md`
   §5 names it canonical.
2. **`mapping.md` in full** — the replication contract, and `claude.md` §3 names
   it authoritative for what footprint to replicate.
3. **`gfx90c_theoretical_limits.md` §5** — the acceptance bars.
4. **`user must never re-derive peaks`** — `oto/device/peaks.py`'s comment is the
   guard; `gfx90c_theoretical_limits.md` §0 states the rule.
5. **`claude.md` §2.1** — the "don't re-derive what the tooling answers" table.
   It is the single highest-value paragraph in the docs tree.
6. **`claude.md` §5**'s corpus-count rule and `todo.txt` user-only rule — both
   have bitten repeatedly; trim is not safe.
7. **`changelog.md`** — append-only by charter. Never trimmed.
8. **`prior_INSIGHTS_CAVEMAN_ULTRA.md` / `prior_RESEARCH_ARCHIVE.md`** — frozen.

---

## 6. Proposed order of execution

1. ARCHIVE `knowledge_base_final.md` (nothing imports it, highest line saving).
2. TRIM `README.md` §§2, 4, 5 to pointers + delete the two stale counts.
   *(The two counts and the §4 link remap are applied; the pointer replacement
   is not — §7.)*
3. ARCHIVE `implementation_plan.md` Triaged-fixes + Option H narrative;
   keep Hplan.7/§9 and the ASCII flowchart.
4. Split `results.md` at the numbers / mechanism seam; root-cause paragraphs to
   `changelog.md`.
5. DOCSTRING the knob/occupancy/legality tables into the modules that already
   own them, replacing the tables with pointers.
6. Renumber `potential_configs.md` §2 and §5 to un-collide them.
7. Move `design_language.md` under `docs/`; delete its `## Output`.

After each step: `python3 plans/verify_all.py` still green, and
`grep -rn "<deleted fact>" *.md` returns nothing.

---

## 7. Applied 2026-10-12 — factual corrections only

Made while finishing Refactor 1. These are **accuracy fixes**, not the
structural whittling proposed above; the deleted/duplicated *content* is
untouched and still lives where §1–§6 say it should be reviewed.

* **Stale flat-module names → package paths** in live docs: `gfx90c_common.*` →
  `oto.device.peaks.*`; `scheduler.<gate>` → `oto.tensile.gates.*`;
  `report.py`/`analytics.py`/`policy.py`/`agent.py`/`registry.py`/
  `tensile_library.py`/`auto_prompt.py`/`telemetry.py`/`mutator.py` →
  `oto/metrics/*`, `oto/ledger/*`, `oto/tensile/*`, `oto/runners/*`.
* **Stale CLI invocations**: `python3 run_status.py --watch` →
  `python3 -m oto.metrics.run_status --watch`; `python3 ab_audit.py` →
  `python3 -m oto.metrics.ab_audit`; `harness/<tool>.py` and
  `python3 -m harness.<tool>` → `python3 -m oto.harness.<tool>`.
* **`README.md` §4 module table** — links remapped from the deleted flat modules
  to their `oto/` homes. §2's stage boxes re-aligned (the longer package labels
  overflowed the ASCII frames) and its `"434 phases"` sub-box removed; §5's
  "434 checked / 434 passed" sentence replaced with a "each tool prints it live"
  sentence. These are the §1.2/§1.3/§4 TRIM items for `README.md` — **applied**,
  so §1.2/§1.3 lose only the "replace §4 with a pointer" half.
* **`docs/docstrings.md`** — the convention's own example cited deleted
  `scheduler.py:1220`; it now cites
  `oto.tensile.gates.vgpr_model.MEASURED_VGPR_BY_DTYPE`. (`ldspad_feasible`
  was checked against `oto/tensile/gates/occupancy.py` and is the real name, so
  an earlier "typo fix" of it was reverted.)
* **Corrupted module paths** left by an earlier bulk rewrite, now repaired:
  doubled `oto/metrics/oto/metrics/*`, `oto/ledger/oto/ledger/*`,
  `oto/runners/oto/runners/*` and `oto/oto/harness/*` (in `README.md` and
  `oto/harness/README.md`); `db_oto/ledger/mutator.py` →
  `oto/tensile/synthesis/db.py` (where `DBMutator`/`FORWARD_KNOB_DOMAINS` live);
  `test_oto/runners/auto_prompt.py` → `test_auto_prompt.py`;
  `tests/test_oto/ledger/mutator.py` → `tests/test_mutator.py`; and the bare
  `scheduler.py` / `report.py` left in `adversarial_review.md` /
  `design_language.md`.
* Dead module references in `oto/**/*.py` comments/docstrings (the 12 sites
  logged in `incomplete_work.md`) corrected to the live names.
* `oto/__init__.py` module docstring lost its `"~40 importers"` corpus count.

Still **not** applied, deliberately: any file that moves, merges, splits or is
deleted; the `knowledge_base_final.md` archive; the `results.md` /
`implementation_plan.md` splits; and every corpus count listed in §4 that is not
one of the two `README.md` items above.

