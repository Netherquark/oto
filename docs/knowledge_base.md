# Knowledge base — template (populated by the agent per device)

> **TEMPLATE — copy and fill per device.** Do not edit the golden example; populate this file for your target.

> **Status: TEMPLATE, NOT POPULATED.** This file ships as device-independent
> scaffolding. It becomes a real knowledge base only when an agent on a new
> target has audited *that* target and pinned its sources — an FFI-populated
> doc, not a paste of the gfx90c one.
>
> The gfx90c port's knowledge base lives in `docs/gfx90c_knowledge_base.md` —
> consult it as a golden reference / worked example **only if needed**, and
> never copy its numbers as architecture truth for another device. The KB
> exists so that no agent treats one part's port mechanism, ISA, or
> knob surface as another's.

## 1. What a knowledge base is (and is not)

The knowledge base is the **WHAT layer**: the facts of *this device's* Tensile
port and ecosystem — what the library is, what the port mechanism is, what the
knob surface is (source-audited), what measurement discipline applies. It
contains architecture truth for one target, not measurements (those live in the
device's `results.md`), not plans (those live in `incomplete_work.md` / the
changelog), not history (that lives in `changelog.md`).

## 2. The golden example — `docs/gfx90c_knowledge_base.md`

That file is the gfx90c port's WHAT-layer, built over months of live work:
the Tensile model, the topology, the 3-entry native port shim, the footprint
contract, the measured kernel-lever table, the measurement science and the
data-preservation law. Read it to learn *how to derive a KB* — what sections
exist, what each proves, what an honest evidence label looks like. Never read
it as license to transplant a number.

## 3. Required sections (populate in this order)

1. **What Is Tensile** — the pipeline (generator → client → merge), the
   ownership split (config semantics are Tensile's; the port only makes the
   ISA exist in Tensile's eyes).
2. **Repository topology** — the pinned tree(s): Tensile checkout, hash,
   branch, local patch (if any) — as *this* target ports it.
3. **The port mechanism** — the *minimal* bookkeeping the port needs (for
   gfx90c it was three entries, not nine — read `docs/gfx90c_knowledge_base.md`
   §3 as the case for minimalism).
4. **GlobalParameters & problem semantics** — what the knobs mean.
5. **Solution space** — the kernel-name token vocabulary for this library.
6. **Shipped footprint** — the replication target if adapting a shipped
   library (the measured family matrix, from the *device's* installed
   library).
7. **Kernel levers that matter** — the knob surface, source-audited against
   the *pinned* checkout, not the wiki: defaults table from the same commit,
   then which knobs are never varied vs never set (two different things), and
   which mechanisms are verified-but-unmeasured.
8. **Measurement science** — the port's protocol (like-for-like, rulers,
   median-of-seeds, sweep order, tie bands, TTY-only, hang safety).
9. **Reporting toolchain** — how the report is produced and consumed (only
   pointers; the pipeline owns the semantics).
10. **Data preservation law** — append-only, never-rewrite, resumability —
    canaries for any agent writing here forever.
11. **Glossary** — the device's token vocabulary.

## 4. How the agent populates it — the order is load-bearing

1. Probe, never recall: `rocminfo | grep -i isa`, `rocm-smi`, Tensile's
   `GetAsmCaps` (test-assembled on the real clang), the installed library's
   per-family `.dat` footprint.
2. Pin evidence: Tensile commit, ROCm version, the exact files read, the
   exact AsmCaps keys — every claim tagged
   **VERIFIED / PARTIAL / UNVERIFIED / REASONING**.
3. Derive, never inherit, same rule as ceilings:
   peak tables come from the port's own derivation;
   the KB records *what the part is*, not what another part was.
4. Every mechanism in §7: state "mechanism VERIFIED in source, gain
   UNMEASURED on this target" — mechanism facts ≠ performance facts.
5. Ship with **0 unlabeled claims**; anything unverifiable is `not found
   (read: …)` and is a legitimate, complete answer.
6. Append never rewrite; date-stamp the file; every number has a `source:` line.

## 5. Hard rules for whoever fills this in

- **No KV inheritance across devices** — ISA, peaks, knob surface, defaults,
  footprint, clocks: derive per target.
- **The KB is not the results ledger** — numbers measured on the target live in
  the device's results doc; the KB supplies the frame those numbers hang on.
- **Tensile defaults from the pinned checkout only** — wiki defaults are
  marked wiki; versions drift; "unset ≠ off" always, always.
- **Data preservation** — prose is append-only; an old claim that became
  false is annotated, never deleted; superseded designs are kept.
- **One KB per port** — this file is the template; the per-device KB is
  `docs/<codename>_knowledge_base.md`.

## 6. When this file is empty

It stays empty by default — empty means the port's WHAT-layer was never
derived. The gfx90c golden example: `docs/gfx90c_knowledge_base.md`. Context
for a new target: `docs/starter_pair.md`, then `oto agent consult` for a
scaffold, then the campaign (`docs/operator_campaign.md`) — research per
`docs/operator_campaign.md` §18.
