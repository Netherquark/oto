# Documentation tooling options for oto
owner: oto maintainer
last-reviewed: 2026-11-15
review-interval: 90d


Decision support for: how to render oto's code-level (docstring) and
ecosystem-level (Markdown) documentation into something browsable. Pick one,
or combine a couple. This document changes nothing on disk — it is a decision
tree, not a proposal. (Your own `todo.txt:43` flags this as a pending item:
"port over documentation (except crucial docs ecosystem case by case) to
doxygen or something or rewrite full docs with caveman ultra" — this file lists
what "or something" means.)

## Where oto stands today

* **Docstrings are prose-first**, not a marked-up format. Module docstrings
  carry three clauses: `Owns:` / `Does NOT own:` / `Public API:`. Function
  docstrings open with a one-line summary, then optional plain `Args:` /
  `Returns:` blocks and a `Why:` rationale that cites `file:line`. They are
  English, not reStructuredText, and not Google/NumPy field lists. Almost no
  docstring in the tree meets a parser's expectation of a parameter section;
  the few `Args:` blocks that exist are informal.
* **The ecosystem docs are hand-authored Markdown** (`docs/*.md`), with a
  class-tagged registry `docs/README.md` and an enforced test that every
  tracked `.md` is registered there (`tests/test_docs_registry.py`).
  `docs/cli.md` is byte-pinned to the parser by `tests/test_docs_cli.py`.
* **No documentation build exists.** There is no `docs/conf.py`, no
  `.readthedocs.yaml`, no API tree, no generated artifact in the repo.
* **Audience:** the owner plus agent sessions (Class A developers, Class B
  operators), not a broad open-source readership yet. GPU legs are
  whitelist-gated, so no doc tool may pip-install the GPU stack at build time.
* **License context:** GPL-3.0. Everything is fine legally; distribution
  target is not decided.
* **Tensile itself uses Sphinx** (its `docs/.readthedocs.yaml`, reST).
  Readers comfortable with Tensile docs will find Sphinx familiar; oto would
  still not be reST, so the familiarity is thematic, not textual.

Any choice has to live with these facts, especially the first one: **the
prose docstring style is a deliberate, load-bearing decision, not a defect to
fix.** A tool that expects `param`/`returns` field lists will render your
docstrings as flat prose — which is exactly what they are, so that's an
acceptable degradation, not breakage — but never expects the tool to
*understand* them.

## The realistic option set

### 1. pdoc (`pip install pdoc`) — the zero-friction reference renderer

What it is: the successor to plain `pydoc -m pydoc.topics`; renders a static
HTML site directly from the live objects. `pdoc oto` → `_site/`.

Pros:

* One command; understands everything Python itself understands: annotations,
  dataclasses, re-exports, properties, the `oto.*` mixin composition (it reads
  the class at *name* resolution time, so mixin members show up).
* Handles prose docstrings as prose (Markdown-ish): paragraphs, code fences,
  line structure all survive; `Args:`-style blocks degrade to literal text.
* Markdown output also supported (`pdoc --output-format markdown oto`) —
  useful anywhere else you feed Markdown.
* Tiny dependency (pdoc + markdown-it-py); fully offline; CPU-only; CI-cheap.
* No theme craft required; the default theme is legible.
* Does not touch your source layout, docs ecosystem, or the byte-pinned CLI.

Cons:

* Output is a *reference dump*, not a curated manual. No landing page, no
  narrative, no navigation beyond modules/classes.
* Alphabetical member ordering; no say in presentation order or grouping.
* `Owns` / `Does NOT own` / `Public API` are not understood as semantics —
  they render as emphasis-free sentences (readable, just undecorated). You
  can add a small custom Jinja template (pdoc supports one) to promote them.
* Cross-links between modules are inferred from `oto.*` name mentions when
  they resolve — usually works, occasionally needs a nudge.
* No PDF output; the story for print is "browser's print-to-PDF".

Effort: half an hour to first page; less if you accept alphabetical order.
CI fit: one workflow step, or committed `_site/` published via GitHub Pages.

### 2. MkDocs + mkdocs-material + mkdocstrings (Python side via Griffe)

What it is: the pretty docs site; Markdown-native with full theming
(search, dark/light, nav). `mkdocstrings` embeds live Python objects from
your package into the pages; Griffe parses the docstrings.

Pros:

* Best-if-you-want-a-*site*: navigation, instant search, polish, all offline;
  GitHub Actions publishes it for free.
* Your existing `docs/*.md` can be wired straight into `mkdocs.yml`'s nav —
  the byte-pinned `docs/cli.md`, the registry page, the runbooks — so the
  ecosystem and the rendered docs don't diverge into two universes.
* mkdocstrings renders prose docstrings as prose; the few `Args:` blocks
  degrade gracefully; type annotations are read from signatures.
* Cheap ongoing authoring: edit one MD, warning-free build ≈ done.

Cons:

* Second source of truth for what the nav *is* (you curate it). If the
  registry `docs/README.md` and `mkdocs.yml` drift apart, nobody diffs them.
* Griffe wants Google/NumPy-ish parameter sections to make `Parameters`
  headings; your prose Args degrade to plain paragraphs unless the module is
  rewritten — no enforcement though, so drift is invisible (like now).
* No built-in *correctness* checks beyond isolated warnings; it won't catch a
  broken `oto.*` mention (use `mkdocs build --strict` + `mkdocs-validate` —
  still warnings-level, not hard errors, for most link paths).
* Another config file at repo root; another thing for the owner to maintain.

Effort: half a day to a polished first site (including nav wiring); one
afternoon if you accept the default theme.

### 3. Sphinx (+ autodoc / MyST-Parser / napoleon / autosummary)

What it is: the classic Python documentation engine. reStructuredText (or
Markdown via MyST-Parser) + `autodoc` reads docstrings live.

Pros:

* The most capable Python doc species: intersphinx to cross-reference stdlib
  and `sphinxcontrib.*` targets, `autosummary`-driven API pages, `graphviz`
  for import/call graphs, epub/PDF/man outputs, `sphinx -W` hard-fail builds,
  extension ecosystem for everything (spelling, coverage, extlinks).
* Upstream Tensile documents in Sphinx/reST, so your readers see a familiar
  shape — worth something for a port-oriented project.
* Strictly the best citation/cross-reference story if you later want the docs
  to *prove* code claims.
* MyST-Parser accepts CommonMark, so ecosystem MDs can be included verbatim.

Cons:

* The config surface is the real cost, not the installing: `conf.py`,
  extension versions, theme choice, intersphinx mapping, myst settings. And
  every extension is a maintenance obligation.
* Your docstrings are *not* reST/napoleon parseable in the structured sense:
  `:param:` roles will render your `Args:` fine only if autodoc is told your
  style is "plaintext"; `Owns`/`Does NOT own` stay flat text again. Expect
  to keep prose docstrings and accept the flat output.
* Mixin composition: `ConvergenceAgent` inherits nearly all its methods from
  mixins on another module; autodoc shows inherited methods with `:inherited-members:`
  but cross-module grouping is awkward.
* Docs tend to accrete: "could also include results, could include …", until
  the whole suite is transposed into doc pages nobody reads. Must be curated.
* Sphinx-human-resources remain the bottleneck for any serious polish.

Effort: a day-ish to a basic-but-correct site, much longer to polished.
Best when you reach the point where you want CI-hard docs that can't silently
drift.

### 4. Doxygen — the wrong-shaped tool, but a common question

What it is: the C/C++ classic with a Python back-end.

Pros:

* Superb *call graphs* — if oto had C++ HIP client sources in-tree, this
  would matter. Today's option for that: produce the graph from the Tensile
  subtrees only, treating `oto/` via a second, Python-native tool.
* Handles mixed-language corpora (Python + CMake + LaTeX TeX) in one project.
* Mature and widely deployed; CI integration is a solved problem.

Cons:

* Python support is heuristic (lexical), not object-level; re-exports and
  mixins render poorly or wrongly.
* **It expects field-list docstrings** (`\param`, `\return`); prose
  docstrings render as wall-of-text paragraphs, worse than pdoc.
* The generated graph over a mixin-heavy package is pretty much fiction:
  dynamic attribute chains aren't traced, call edges go to definitions rather
  than to composed instances.
* Default output aesthetics are dated; theming is hit-or-miss.
* Three config artifacts (`Doxyfile`, filters, stylesheet) for zero benefit
  over option 1 on this codebase.

Effort: a day with worse output. **Not recommended** for this repo's shape.

### 5. Hosted/proprietary site builders (GitBook, Docsify, Docusaurus, Starlight)

* GitBook: zero-infra hosting; but external dependency, proprietary UI, and
  docs never leave their silo. Not for a GPL repo whose docs must live with
  the source.
* Docsify: renders the repo's Markdown directly, CDN-loaded, no build step —
  cheapest possible site, still ships a JS toolchain and weak offline story.
* Docusaurus (Meta) / Astro Starlight (Vercel): the modern static-site
  frameworks with MDX. Beautiful, versioned, blog-able. But they expect you to
  build *their* site, not reuse your docstrings; API pages come from a
  separate generator or manual page. Overkill for this audience.

Effort: varies; all are poorer fits than 1–3 for a docstring-first project.

### 6. PDF/print route (Pandoc + LaTeX)

If you ever want one document handed out:
`pandoc` can splice `docs/*.md` into a single PDF including a generated API
section (pdoc Markdown output). Zero infrastructure, runs in CI, but print is
the artifact of choice only for audits/releases.

### 7. "Just read it" routes (pydoc, `oto help`, the byte-pinned docs)

No build at all: `python3 -m pydoc oto.tensile.gates.occupancy`, `oto help
<command>`, the existing `docs/cli.md`. Zero maintenance; zero publishable
artifact; what this repo does right now. Worth including since option 1
strictly subsumes it.

## Comparison matrix

| Tool | First page | Prose docstring fit | CI fit (CPU-only) | Ecosystem MD reuse | Curation burden | Typical role |
|---|---|---|---|---|---|---|
| pdoc | 0.5 h | excellent (as prose) | trivial | no (API only) | low | API reference, GH Pages |
| MkDocs+material+mkdocstrings | 0.5 day | good (as prose) | easy | yes (nav) | medium | full docs site |
| Sphinx+MyST+autodoc | 1+ day | fair (flat text) | moderate | yes (MyST, `include::`) | high | hardened manual + PDF |
| Doxygen | 1 day | poor | easy | no | high | mixed C/C++ + Python (not here) |
| GitBook/Docusaurus | 0.5 day | n/a (no docstrings) | varies | yes | high | hosted community site |
| Linux man/docbook | 1 day | poor | easy | no | very high | none needed |

## Decision checklist

1. Who reads this — your own agents on this box, or people you publish to?
2. Is the artifact a *site*, a *reference*, or a *PDF*?
3. How much do you want to touch prose docstrings? (Answer: ideally none.)
4. Must `docs/*.md` render in the same site? (docs registry test must still
   pass — docs must stay registered, Class-tagged, and in lockstep.)
5. Where does it live — build artifact, `gh-pages`, RTD, or committed HTML?
6. Does CI enforce `--strict`/warnings-as-errors? (Recommend: only if the
   build stays warning-free.)
7. Is the authoring loop `mkdocs serve` / `python3 -m pdoc` acceptable for you?
8. Does the doc build pull `requirements-docs.txt` (new extras file) or just
   the plain runtime set?

## Consequences for the repo either way

* A rendered API artefact would duplicate what `oto/README.md` and the
  docstrings carry — the two must not contradict each other (the docstrings
  win; the generated page is a view).
* Any new doc file you commit under `docs/` registers in `docs/README.md`
  with a `Class` tag, per the `test_docs_registry.py` contract.
* `docs/cli.md` remains byte-pinned to the parser; no tool regenerates it.
* Whatever you choose, keep `Requirements` minimal: one
  `requirements-docs.txt` at the root; never touch `requirements.txt` for
  docs.
* GPU is never required for any of these; fake profiles suffice (e.g.
  `profiles/gfx90c.json` for namespace resolution). Cite no measurement data.

## Recommendation tiers (in order of value density)

1. **pdoc** now — one command, one site artifact, zero source-tree changes,
   and it works the moment you run it. If you want this site indexed on GH
   Pages, subscribe option 1 with a two-line CI job.
2. If you want the full story — registry + runbooks + API in one searchable
   site — **MkDocs + material + mkdocstrings**, reusing every existing MD,
   accepting the nav-curation cost.
3. If you reach twenty-plus users or want CI-proof PDF — **Sphinx+MyST** — do
   it later, after the docstring ecosystem settles; swap engine without
   rewriting content.
4. **Not Doxygen, not a JS site builder** today: neither engages with your
   prose docstrings, and both multiply the moving parts.

The honest summary: your docstrings are designed to be read in code, not
parsed; pick a renderer that treats them as readable text and do not let any
tool coerce them into field lists.
