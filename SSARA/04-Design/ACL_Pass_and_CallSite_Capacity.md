# Around-Call-Liver (ACL) Pass + Call-Site Callee-Saved Capacity Gate — Design

Two coordinated changes that together fix the **cross-call physreg-exhaustion**
crash class (§4.7 of [SSA_RA_Coloring](SSA_RA_Coloring.md)). The spiller gate makes the around-call
live set *fit*; the coloring pass *places* the survivors in the only registers
they may legally use.

Both rest on one fact: **a value live across a call may occupy only callee-saved
registers** — caller-saved regs are clobbered by the call regmask, so a cross-call
value colored there would be undefined after the call. The coloring stage already
enforces this per-value (the `IsFree` CallSite check in `pickFreePhysReg`,
[SSA_RA_Coloring](SSA_RA_Coloring.md#47-cross-call-color-constraint)); what is missing is (a) a
spiller that guarantees the set *fits* callee-saved capacity, and (b) a coloring
order that settles cross-call values before the general population competes for
those slots.

## Status

🔧 **Proposed — NOT IMPLEMENTED.** Neither Part 1 (spiller call-site
callee-saved capacity gate) nor Part 2 (two-phase ACL coloring partition) exists
in the tree: there is no `ACLSet`, no `CScap`, and `color()` is still a single
width-descending dominance-order walk (no two-phase partition). What *is*
committed is (a) the whole-file budget cap
([SSA_SPILLER_DESIGN](SSA_SPILLER_DESIGN.md#register-budget-cap-by-allocatable-file-size)) and (b)
the per-value cross-call constraint — `pickFreePhysReg`'s `IsFree` CallSite check
already rejects caller-saved registers for a value live across a call
([SSA_RA_Coloring](SSA_RA_Coloring.md#47-cross-call-color-constraint)). This document is the
**priority** next step; it supersedes the deferred precolored-tuple gate for the
ABI/call portion
([SSA_SPILLER_DESIGN](SSA_SPILLER_DESIGN.md#precolored-pr-tuple-feasibility-gate-downscoped-deferred-2026-07-15)).

## Motivation (measured)

`tuple-allocation-failure.ll @kernel` — an `amdgpu_kernel` with **7 calls** —
aborts `Failed to find free physreg` on **SReg_64**: cross-call-live SGPR values
exhaust the callee-saved SGPR range. The whole-file budget gate
(`SUM(RP) < limit`) does not see the tighter callee-saved sub-budget at the call
sites, so the spiller inserts nothing and the allocator later cannot place the
set. Of the ~35 analysable physreg crashes, ~5 have this real-call shape
(mcexpr-knownbits, preserve-wwm-copy-dst-reg, tuple-allocation-failure,
undef-handling-crash-in-ra, whole-wave-register-copy) — see
`REMAINING_CRASHES_CLASSIFICATION`.

## Part 1 — Spiller: call-site callee-saved capacity gate

At each call site C, for each register file F (VGPR, SGPR; AGPR later):

```
ACLwidth(C, F) = Σ width(v)   over vregs v live across C, in file F
CScap(F)       = | allocatable(F) ∩ callee-saved(F) |
if ACLwidth(C, F) > CScap(F):
    Belady-spill cross-call-live values in F (furthest next use first)
    until ACLwidth(C, F) ≤ CScap(F)
```

- **`CScap(F)` is order-derived, not hardcoded.** Compute from
  `RegClassInfo.getOrder(RC)` intersected with `getCalleeSavedRegs`, so it honors
  reserved registers and the occupancy budget. (For reference the raw gfx90a CSR
  lists are VGPR 112 / SGPR 44 / AGPR 224, but the allocatable-∩ number is the one
  the allocator can actually use.) Computed once per function.
- **Reuses the existing Belady machinery** (`getVMPsToSpill` / next-use), scoped to
  the cross-call-live subset and the call site as the pressure point.
- **Additive to the existing peak gate.** A value can need spilling for
  callee-saved capacity even when whole-file RP is under limit — this gate fires
  at call sites specifically.

## Part 2 — Coloring: two-phase ACL partition

`ACLSet` = vregs whose `LiveInterval` is live across any `CallSites` index
(computed once in `color()`, reusing the `CallSites` list already built there).

Split the width-descending walk into two phases; each is a full
dominance-order, width-descending walk, so each keeps PEO optimality **on its own
subset**:

1. **Phase 1 — ACL.** Color only `ACLSet`. Cross-call values are rejected from
   caller-saved by the existing `IsFree` CallSite check, so they settle into
   callee-saved automatically — **no sub-order, no reservation**.
2. **Phase 2 — ordinary.** Color the rest. Phase-1 assignments are already in
   `ColorMap`, so `seedOccupiedAtBBEntry` marks them occupied at block entry and
   ordinary values fill everything still free (the callee-saved slots ACLs did not
   use, plus all caller-saved). "CS top used, everything above is free" falls out
   of the occupancy bitvector — **nothing is reserved, no `lastACLidx` math**.

**Occupancy fix required.** Today the mid-block re-marking of already-colored defs
only handles *wider* defs ([SSA_RA_Coloring](SSA_RA_Coloring.md#45-handling-wider-defs-in-narrower-passes)).
Phase 2 must also re-mark a **same-width** phase-1 (ACL) def — occupied at its def,
freed at its kill — so an ordinary same-width value does not reuse a live ACL slot.
Extend the def loop: if `Reg` is already in `ColorMap` (from phase 1), treat it
like an already-colored wider def (`markOccupied` / kill-free), do not recolor.

## Why this is theory-safe (vs the reverted global biases)

Earlier prototypes biased the *global* color choice (cross-call → callee-saved for
all vregs at once) and regressed — they perturbed the single dominance-order walk
that Hack's optimality proof depends on. This design is a **partition**: two
disjoint subsets, each colored in its own dominance-order width-descending walk.
Neither phase reorders the other's PEO, so each is optimal for its subset. See the
theory constraint in [SSA_RA_Coloring](SSA_RA_Coloring.md#47-cross-call-color-constraint).

## Implementation & verification order

1. **Part 1 first** (spiller gate) — it is what prevents the crash; measure alone.
2. **Part 2** (ACL coloring partition) — places the survivors; measure stacked.
3. Corpus vs `/tmp/corpus-budgetfix2` (baseline 47 crashes). Require **0 new
   crashes**, no occupancy/scratch regression; watch the ~5 ACL cases above.

**Open question to settle by measurement.** Because the `IsFree` check already
forces each cross-call value into callee-saved per-value, Part 1 alone (spill to
fit CS capacity) may clear several cases with the *existing* coloring placing the
survivors. Part 2 then improves packing and removes ordinary-vs-ACL contention.
Measure Part 1 alone before committing to Part 2.

## Scope / caveats

- **Reduces, does not eliminate** the cross-call class: if the around-call live set
  *cannot* fit callee-saved even after spilling everything spillable (e.g. the set
  is unspillable precolored/inline-asm values), it still fails — that residual
  needs AGPR coloring ([SSA_RA_Coloring](SSA_RA_Coloring.md#48-agpr-coloring-gap-av-class-values-are-pinned-to-vgpr)).
- **Per file** (VGPR / SGPR disjoint); AGPR folded in with §4.8.

## Source touchpoints

| File | Change |
|---|---|
| `AMDGPUSSARegisterSpiller.cpp` | Part 1: `CScap` per file (once), call-site capacity gate in the RPO walk, Belady spill of cross-call subset |
| `AMDGPUSSARegisterAllocator.cpp` | Part 2: `ACLSet` from `CallSites`; two-phase `color()`; same-width already-colored def occupancy in the width walk |
