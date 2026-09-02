# Demand Oracle and Cumulative Spill Planning

## Source Mapping
- **Component**: SSA Register Allocator — spill planning stages
  (`costOfSpilling`, `preSpillToLimitWidthAware`, `reduceRegionPressure`,
  `findTightRegions`, `relieveTightRegion` in `AMDGPUSSARegisterAllocator.cpp`).
- Depends on: [[Lane_Accurate_Interference]] §5 (`isSpanFree`, canonical
  decomposition), §7 (reference-oracle-and-validator pattern), §9 (candidate order
  from `getOrder`), §10 (staging and gates).
- Reframes: [[Spiller_GCNRPTarget_Redesign]] (keeps its bug finding, drops its
  scalar framing).
- Tier axis from: [[Width_Tiered_Coloring]] (a tier is a (pool, width) pair).

## Status

🔬 **AGREED DIRECTION (2026-09-02), not implemented.** Recorded from a design
discussion, in the user's two-point framing:

1. Remove scalar register-pressure metrics entirely. There is to be **one**
   register-demand oracle, backed by the register tree, answering demand against
   capacity per width tier at a slot.
2. Stop selecting spill candidates one at a time against a credited per-candidate
   relief score. Relief is not additive, so selection must be over **sets**, with
   the effect **measured** by re-querying the oracle.

## 1. Why the scalar metric has to go

A dword count cannot express run structure or alignment, and those are what decide
colorability. A slot can sit at or under a dword limit and still be uncolorable
because the free units are neither contiguous nor legally aligned; over-limit slots
routinely colour fine. The scalar number is therefore not a conservative
approximation of the real constraint — it is a different quantity that happens to
correlate.

[[Lane_Accurate_Interference]] §9 contains the phenomenon in miniature, in its
argument against level scans: with leaf 0 occupied, leaves 1 and 2 free and leaf 3
occupied, an aligned view reports no width-2 block while `v[1:2]` is free and legal.
A dword count over the same state reports two free units and says nothing about
whether any of them are usable together. Both errors are structural, not tuning.

Where scalar metrics sit today: the `ExcessDrop`/`Relief` crediting in
`costOfSpilling`, the private hull-based pressure model inside
`reduceRegionPressure`, the spiller's `VGPRLimit`, and every
`GCNUpwardRPTracker` dword sum feeding them.

## 2. Point 1 — one demand oracle

At a slot $S$, for each tier $(pool, w)$ in **descending width order**:

- **Demand** — the number of values live at $S$ that require that tier.
- **Capacity** — the number of disjoint legal placements still available: walk
  `RegClassInfo::getOrder(RC)` and count starts for which `isSpanFree(start, w, [S,E))`
  holds, with wider tiers already placed.
- **Deficiency** — $\max(0, \text{Demand} - \text{Capacity})$, in **runs**; in
  register units it is runs $\times\, w$.

Descending order is required because wider tiers constrain narrower ones and not
conversely. The tier axis is (pool, width), not register class and not raw width,
per [[Width_Tiered_Coloring]].

This is not a new primitive. `getNumFree(SlotPos, Width)` is specified in
[[RegisterTree_Driver_FSM]] §6, and `isSpanFree(first, w, [S,E))` — the only query
the allocator needs — in [[Lane_Accurate_Interference]] §5. The oracle is a *caller*
of them, per tier, in a loop.

### Prerequisites, already recorded

- **Leaf axis must be hardware register index**, not `getOrder` ordinal. A span needs
  consecutive hardware registers, and allocation order is not hardware order once
  registers are reserved. Today's shadow indexes by ordinal and explicitly refuses to
  assume contiguity there — harmless at its width-1 scope, wrong for any span query
  ([[Lane_Accurate_Interference]] §5).
- **`isSpanFree` must read only the free-extent aggregates**, never `NodeAllocated`,
  which records that one exact aligned block was claimed by one call — something an
  unaligned span never is.
- **Span queries at arbitrary starts and non-power-of-two widths** are staging step 2
  of [[Lane_Accurate_Interference]] §10 and do not exist in any tree yet: `isSpanFree`
  appears in that document and in **no code**, neither the committed
  `SSARegisterTree` nor `SSARegisterTreeV2`.

### Odd widths and unaligned starts are closed

A run of any width at any legal start is the canonical decomposition of its leaf
range into maximal aligned nodes, ANDed. Over four leaves a 3-wide run is
`isFree(leaf 1) AND isFree(node 2..3)`; the run starting at 0 is
`isFree(node 0..1) AND isFree(leaf 2)`. No phase arrays, no doubled tree, no storage
beyond what the nodes already hold. CLOSED 2026-08-29 in
[[Lane_Accurate_Interference]] §5 and §11.

**Documentation defect:** [[RegisterTree_Driver_FSM]] §11 still lists **O5 — odd
widths & non-tree scalars** as open, needing "overlapping-index / composite nodes /
side-tracking". That is superseded by the decomposition above and should be marked
closed by reference. Its staleness caused the decision to be re-derived from scratch
on 2026-09-02.

### Validate before granting authority

Same pattern as [[Lane_Accurate_Interference]] §7: run the oracle as a shadow first,
logging per slot and tier its deficiency beside the colourer's actual outcome.
Directional severity, because the two error directions are not equally bad:

- oracle says feasible, colourer fails at that tier — **unsound**, must reach zero;
- oracle says deficient, colourer succeeds — **pessimism**, bucket and understand.

## 3. Point 2 — cumulative (set) planning

Relief is **not additive**. Whether two evictions yield a usable run depends on
adjacency: two candidates each freeing one 32-bit unit produce a 64-bit run if their
units are adjacent and legally aligned, and produce nothing if they are not. A
per-candidate score therefore cannot be summed, and a greedy walk that credits
scores as it goes is measuring a quantity that does not compose.

Consequences for the planner:

- Selection is over **sets** of candidates, not one candidate at a time.
- The effect of a set is obtained by **re-querying the oracle** after applying it,
  never by crediting a stored per-candidate number.
- The objective is a **minimal set that drives deficiency to zero at every
  over-subscribed slot, per tier**, ordered by cost — next-use distance, loop depth,
  resulting spill traffic.
- Deficiencies observed so far are small, typically one or two runs, so a bounded
  exact search over the cheapest few candidates is affordable, with
  greedy-plus-remeasure as the fallback beyond the bound.

This is the same defect [[RegisterTree_Driver_FSM]] §11 names as **O4 —
atomic-spill insufficiency**: "v1 atomic callbacks reject compositions only solvable
in two dependent steps within one transaction; those show up as fails where Greedy
succeeds." Set selection with measured effect subsumes O4 rather than sitting beside
it.

## 4. Loop-carried liveness — correction recorded

A value defined **anywhere** in a loop, including in the latch, is live across the
**whole** loop, because the back edge carries it. Linear slot-order reasoning
misrepresents this: the value appears at slots textually earlier than its definition,
and any model that reads its extent as a forward hull over the slot axis gets it
wrong.

This is the phenomenon the `case3` veto in `costOfSpilling` gropes at — it rejects a
candidate with uses inside the region's loop on the grounds that a reload before the
region re-adds pressure. The veto is the wrong instrument for it, but **the proposal
to remove `case3` is withdrawn** until the demand model represents back-edge liveness
correctly; removing it while the model is still hull-based would trade a known
pessimism for an unknown unsoundness.

Implication for the oracle: liveness at a slot must be taken from the interval, which
already carries loop liveness correctly, and never from a hull or from slot ordering.

## 5. Measurement debt

`SpillPlan::NewPeak` (predicted peak) and the measured post-spill peak are printed at
both planning stages as of 2026-09-02; **no data has been collected yet**.

Figures from the 2026-09-02 session — pre-spill optimistic in 34% of events, median
84 and maximum 144 dwords, against region-rp at 20% and median 8 — compared summed
`ExcessDrop` (a sum over over-limit slots) with a measured **peak** (a maximum). Those
are different quantities and the comparison is invalid. **Do not quote those numbers
as the model's error.** They are retained only to record why the instrumentation was
added.

## 6. What this changes in existing plans

- [[Spiller_GCNRPTarget_Redesign]] proves a real bug — the spiller caps `VGPRLimit`
  at the `VGPR_32` file count, which is wrong for `av_` values on unified-file
  targets, so it sheds tuples Greedy places in AGPRs. Keep that finding. Its
  remedy, `GCNRPTarget`'s two-ceiling model, is still a scalar dword model and is
  therefore not the destination under point 1.
- `costOfSpilling`'s veto structure: the `test2-peruse` feasibility gate was removed
  2026-09-02 (it measured pre-existing pressure rather than pressure *change*, so it
  vetoed every candidate in exactly the regions that needed one — a deadlock);
  `case3` removal is withdrawn per §4; `reloadRPBeforeUse` is now dead code, its only
  caller having been the removed gate.
- `reduceRegionPressure`'s private hull model is superseded by oracle queries. Its
  catalogued defects — hull collapse over liveness holes, CFG-blind regions summing
  mutually exclusive paths, credited rather than measured relief — are all instances
  of the two points above, and [[Lane_Accurate_Interference]] §11 already requires the
  region model to follow occupancy into lane accuracy.

## 7. Sequenced work

1. Leaf axis to hardware register index.
2. Span queries: `isSpanFree` at arbitrary starts and non-power-of-two widths.
3. Oracle as a **shadow**, logging per-slot per-tier deficiency beside colourer
   outcome; unsound disagreements to zero.
4. Replace the planner's scalar metric with oracle queries.
5. Set selection with measured effect, replacing credited per-candidate relief.

### Gates

- **The 83-command planner workload first.** Of roughly 7,400 `llc` runs over the
  AMDGPU corpus, only 109 processes / 83 distinct (test, mcpu) commands reach
  `relieveTightRegion`; `findTightRegions` runs on every function but finds
  relievable work in 1.5% of them. The corpus is therefore about 98.5% noise for any
  spill-planning change, and the 83-command sweep covers every function that
  exercises this code. Instruments: `scripts/ssara_trace.py` and
  `scripts/corpus/planner83/`.
- **`cf512` as the under-spilling canary** — an earlier, more accurate pressure model
  under-spilled and broke it. A more accurate oracle spills *less*, so this is the
  expected failure direction.
- **Corpus by per-test bucket transition** at `--timeout 300` against
  `archive-rescuebound-0828`, for crash transitions only.
- **The SSARA and SSASpiller lit suites are NOT a gate** (user ruling, reaffirmed
  2026-09-02). They encode expectations of the abandoned NUA + EarlySpiller + old-RA
  design, and of allocator output being actively rewritten.

## 8. Open

- **Cost function for set selection** is unspecified: how next-use distance, loop
  depth and spill traffic combine into the order the bounded search walks.
- **Evaluation points.** Whether the oracle must be evaluated at every slot or only
  at region peaks, and what that costs in the 1.5% of functions that reach planning.
- **Whole-width versus lane-accurate is orthogonal** to both points. Do not combine
  the two changes; the lane-accuracy work has its own staging in
  [[Lane_Accurate_Interference]] §10.
