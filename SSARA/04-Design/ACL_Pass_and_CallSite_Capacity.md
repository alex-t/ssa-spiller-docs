# Around-Call-Liver (ACL) Pass + Call-Site Callee-Saved Capacity Gate — Design

Two coordinated changes that together fix the **cross-call physreg-exhaustion**
crash class (§4.7 of [[SSA_RA_Coloring]]). The spiller gate makes the around-call
live set *fit*; the coloring pass *places* the survivors in the only registers
they may legally use.

Both rest on one fact: **a value live across a call may occupy only callee-saved
registers** — caller-saved regs are clobbered by the call regmask, so a cross-call
value colored there would be undefined after the call. The coloring stage already
enforces this per-value (the `IsFree` CallSite check in `pickFreePhysReg`,
[[SSA_RA_Coloring#4.7 Cross-Call Color Constraint]]); what is missing is (a) a
spiller that guarantees the set *fits* callee-saved capacity, and (b) a coloring
order that settles cross-call values before the general population competes for
those slots.

## Status

⚙️ **IMPLEMENTED behind `-amdgpu-ssa-acl-coloring` (default off), committed
`41850d69` on `claude-sandbox` (uncommitted→committed 2026-07-16).** Both Part 1
(spiller preserved-RP gate) and Part 2 (two-phase ACL coloring partition) now
exist. Corpus with the flag on: **44 crashes vs 47 baseline** (−4 fixed, +1 new
= net −3); default-off path is unchanged. Remaining +1 (`init.whole.wave-w32`) is
a distinct, non-ACL `ExpandPostRA`/`expandSGPRCopy` bug.

Deviations from the original Part 1/2 sketch below, learned by measurement:
- **ACL priority set = real regmask calls only.** `CallSites` in `color()` also
  collects implicit allocatable-physreg defs (e.g. `implicit-def $vcc` — VCC *is*
  allocatable), which flooded the ACL set on call-free code and caused downstream
  `SplitCriticalEdge`→`removeSegment` crashes. Fix: the ACL priority partition
  derives only from `MI->isCall()` sites; `IsFree` still checks *all* clobber
  sites for per-register legality. Do **not** skip `dead` defs (a `dead $vcc`
  still writes VCC → still a legal clobber for `IsFree`).
- **Part 1 is now the per-call form (Part 1b below), NOT the point-gate.**
  Committed `de7cc9d0` on `claude-sandbox`: the per-instruction preserved-RP gate
  + re-classify fixpoint was replaced by the four-pass `processACLCalls` design.
  Corpus unchanged (44, identical crash set), fixpoint eliminated. The
  integration patch (`github/patches/amdgpu-ssa-acl-four-pass.diff`, verified
  `git apply --check` clean against `ssara`) carries this state.

## Motivation (measured)

`tuple-allocation-failure.ll @kernel` — an `amdgpu_kernel` with **7 calls** —
aborts `Failed to find free physreg` on **SReg_64**: cross-call-live SGPR values
exhaust the callee-saved SGPR range. The whole-file budget gate
(`SUM(RP) < limit`) does not see the tighter callee-saved sub-budget at the call
sites, so the spiller inserts nothing and the allocator later cannot place the
set. Of the ~35 analysable physreg crashes, ~5 have this real-call shape
(mcexpr-knownbits, preserve-wwm-copy-dst-reg, tuple-allocation-failure,
undef-handling-crash-in-ra, whole-wave-register-copy) — see
[[08-Worklog/2026-07-14-phicoalescer/REMAINING_CRASHES_CLASSIFICATION]].

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
only handles *wider* defs ([[SSA_RA_Coloring#4.5 Handling Wider Defs in Narrower Passes]]).
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
theory constraint in [[SSA_RA_Coloring#4.7 Cross-Call Color Constraint]].

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
  needs AGPR coloring ([[SSA_RA_Coloring#4.8 AGPR-Coloring Gap: AV-class values are pinned to VGPR]]).
- **Per file** (VGPR / SGPR disjoint); AGPR folded in with §4.8.

## Part 1b — IMPLEMENTED: four-pass spiller with a dedicated ACL pass

> **Status: IMPLEMENTED** (committed `de7cc9d0` on `claude-sandbox`; integration
> patch `github/patches/amdgpu-ssa-acl-four-pass.diff`). This section describes
> the shipped design and the point-gate it replaced.

**Why the old point-gate respilled.** The original Part 1 gate fired per
instruction wherever `computePreservedRP(MI) > k_cs`, shed 1–2 slots there, and
re-ran the whole pass up to 8× (a fixpoint) because reload vregs it created
re-entered the pinned set. Measured on `tuple-allocation-failure` (probes
`[XCALL]`, `[NEXTCALL]`, `[SPLITCAND]`): the gate fired at ~7 scattered peaks
between calls, each shedding 1–2, picking farthest-next-use values **measured
from the peak** — often the wrong ones (they don't reduce pressure *at the
call*). The "8" was arbitrary; each iteration just retried without knowing why it
still exceeded. The four-pass design below removed it.

### The four-pass structure

The preserved-RP (ACL) spilling becomes a **dedicated pass per file, run before
that file's ordinary (total-RP) pass** — mirroring the coloring side, which
already colors ACL (phase 0) before ordinary (phase 1). Order:

```
1. ACL_SGPR   preserved-RP gate, SGPR   (processACLCalls, SGPR)  → spills → VGPR lanes
2. main_SGPR  total-RP gate, SGPR        (processFunction, SGPR)  → more SGPR spills → more lanes
   -- countSGPRSpillVGPRs(): VGPRLimit -= lanes(total);  VGPRPreservedCap -= lanes-crossing-calls --
3. ACL_VGPR   preserved-RP gate, VGPR    (processACLCalls, VGPR)
4. main_VGPR  total-RP gate, VGPR        (processFunction, VGPR)
```

- **ACL before main, within each file:** ACL spilling frees callee-saved
  registers, so the following total-RP walk sees the relief and won't redundantly
  spill the same values. ACL needs only the preserved dimension; running it first,
  isolated, keeps its per-call logic free of total-RP nibbling.
- **`processACLCalls()` is a separate function** (not `processFunction` + a flag):
  ACL is a **per-call** loop, not the per-MI RPO forward walk, so it doesn't fit
  the existing walk shape. `processFunction` loses its preserved-RP branch and
  becomes total-RP only.
- **Lane accounting sits between pass 2 and pass 3.** Both SGPR passes create SGPR
  spills → VGPR lanes, so `countSGPRSpillVGPRs()` runs once after pass 2. It debits
  **both** budgets: `VGPRLimit` (total, as today) **and** `VGPRPreservedCap` by the
  lanes that **cross calls** — those lanes are VGPR around-call-livers (the SGPR
  value was ACL precisely because it crossed a call), so they occupy callee-saved
  VGPRs and must be visible to ACL_VGPR (pass 3). This closes the "SGPR→VGPR-lane
  transfer invisible to VGPR preserved-RP" gap; the four-pass order is what makes
  it fixable (all lane-producing spilling is done before pass 3).

### `processACLCalls()` — the per-call algorithm

**Store vs free are decoupled.** Store-at-definition is a hard invariant (EXEC
safety — [[Decisions#Store at Definition]]). But where the register becomes
**free** is a separate knob: `KillIdx` in `spillAndReload`.
`buildDomGroupsForSpill` collects only uses **reachable from `KillMI`**
(`DT->dominates(KillMI, Use) || isUseReachableFromDef`), so uses *above* the kill
keep the original register and are not reloaded. A value can thus be freed *across
a specific call* by placing `KillIdx` after its last pre-call use — **no store
move, no EXEC analysis.**

**Classification relative to a call C** (only the third class is unspillable):
- **clean for C** — no use in `(def, C]` needing a register at C. `KillIdx =
  slot(C)`; freed def→C in one shot, one reload after C.
- **both-sides for C** — a use before C and after C. `KillIdx = slot after the last
  pre-call use`; register held def→preUse (not across C), freed across C, reloaded
  after C. Store still at def.
- **used-at-C** (call operand/target, e.g. the `SI_CALL` pointer `%148`) — must be
  in a register *at* C; no `KillIdx < C` frees it without breaking that use.
  **Unspillable for C** → the infeasibility floor.

```
processACLCalls(file F):
  for each call C in program order:
      cross  = pinned vregs live across C, in F
      floor  = Σ width(v) for v in cross used AT C          # unspillable
      excess = Σ width(cross) − k_cs(C, F)
      if excess <= 0: continue
      if floor  >  k_cs(C, F): emit "infeasible at C" diagnostic; stop (no fixpoint)
      cand = (cross \ used-at-C), ordered clean-first then by next-use distance
      for v in cand:
          spillAndReload(v, KillIdx = clean(v) ? slot(C) : afterLastPreUse(v, C))
          excess -= width(v)
          if excess <= 0: break
```
- **No fixpoint, no iteration cap.** Each spill removes one crosser of C; a clean
  spill births no crossing reload, a both-sides spill births a between-calls reload
  whose crossing of the *next* call is naturally counted when that call is
  processed — bounded by #calls, deterministic.
- **Reuses unchanged:** `spillAtDefinition` (store@def), `getVMPsToSpill` ordering,
  `buildDomGroupsForSpill` / `emitReloadsAndRepairSSA`. **New:** `processACLCalls`
  itself, and choosing `KillIdx` relative to C (the shipped path hardcodes
  `KillIdx = trigger MI` in `spillAndReload` ~line 1074).

**Open — settle by measurement, not reading:** whether `getEffectiveKillBB`
loop-hoisting behaves with a call-anchored `KillIdx`; and the cross-block
both-sides case where `afterLastPreUse` and C are in different blocks with
divergent CF (the kill block must dominate the post-call uses).

## Source touchpoints

| File | Change |
|---|---|
| `AMDGPUSSARegisterSpiller.cpp` | Part 1 (shipped, to be removed): per-MI preserved-RP gate + `maxPreservedClique` fixpoint. Part 1b: new `processACLCalls()` (passes 1 & 3); `processFunction` becomes total-RP only (passes 2 & 4); `countSGPRSpillVGPRs` also debits `VGPRPreservedCap` by call-crossing lanes; four-pass `runOnMachineFunction` |
| `AMDGPUSSARegisterAllocator.cpp` | Part 2 (shipped): `ACLSet` from `CallSites` (real calls only); two-phase `color()`; same-width already-colored def occupancy |
