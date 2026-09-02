# Register Tree, Window Driver & Recovery FSM — Design Proposal

> Source Mapping:
> - Future: `SSARegisterTree.{h,cpp}` (committed increment 2a/2b/2c is a *stepping stone* — see [[#12. Relationship to the committed SSARegisterTree]])
> - Future driver/FSM: new component, not yet in tree
> - Related: [[SSA_RA_Coloring]], [[PHI_Coalescer]], [[Architecture]], [[Width_Tiered_Coloring]]

Status: **design proposal** (distilled from the 2026-07-31 brainstorming session
`RADesignSession2.docx`, read critically). Not yet implemented. This proposal
**revises** the shape of the register tree and specifies the window driver, the
recovery finite-state machine (FSM), the callback contract, and the driver loop.

---

## 1. One-paragraph summary

The allocator is an **online sweep in dominance order**. A *window* is positioned
at each homeless value's def; a *register tree* (a forest of tiny per-tuple trees,
one per aligned register group) answers "is there a free physreg of width W here?"
by a flat scan of the width-W level. Because we place values in dominance order on
SSA, **the interference test collapses to `isFree()`** — no `overlaps()`. When no
register is found, the scan has *already* collected context (cross-livers, PHI
density…) as a byproduct; a `NoFreeReg` event drives a **recovery FSM** that moves
the window to find a recognizable failure pattern and invokes a **transform
callback**. Callbacks are **atomic** (all-or-nothing) which makes the driver
**provably terminating**. The whole loop is a `while (!worklist.empty())` with a
no-progress guard.

---

## 2. The register tree — a forest, not one tree

Per aligned register group (e.g. a 128-bit `$vN..$vN+3`) there is a small binary
tree ("pallet"):

```
        [0:3]  128-bit        <- root of one pallet
        /    \
    [0:1]     [2:3]  64-bit
    /  \      /   \
  [0]  [1]  [2]   [3]  32-bit  <- leaves
```

The register file is an **alley** of these pallets: `[0:3] [4:7] [8:11] …`.

**Key realization:** *the bigger the tuple, the closer to the root.* A width-`2^k`
aligned tuple is **exactly one node** at a fixed level. Therefore **search is
level-iteration, not tree descent**: each width is a flat candidate list
(`Level32[], Level64[], Level128[]`), and finding a free tuple is a linear scan of
the matching level. The tree structure exists **only for incremental aggregate
update** (see §3), not for search.

Physical layout: **LEVEL-MAJOR arrays, no pointers** (CORRECTED 2026-07-31 — was
"heap-order `parent = i>>1`"; the V2 implementation deviated and the deviation is
RIGHT, accepted at review). Rationale: V2's whole point is **level-iteration search**
over a flat width-W candidate list, NOT descent. In classic 1-based heap-order the
width-W nodes are SCATTERED at stride 2^(k+1) — the hot scan strides through memory
and fights the prefetcher. In **level-major** each width band is a SINGLE CONTIGUOUS
SLICE `[LevelBase[K], LevelBase[K+1])` — the dense sequential scan §2 actually wants.
Heap-order optimizes descent (which V2 does NOT do); level-major optimizes
level-iteration (which V2 DOES). Index scheme (node at band k, in-level index p,
covers leaves `[p·2^k, p·2^k+2^k)`):
```
leaves band (w=1): [ n0 n1 n2 n3  n4 n5 n6 n7 ]  LevelBase[0]=0
w=2 band:          [ n8    n9      n10   n11  ]  LevelBase[1]=8
w=4 band:          [ n12           n13        ]  LevelBase[2]=12
```
`levelOf(i)`: band k with `LevelBase[k] ≤ i < LevelBase[k+1]`;
`firstLeafOf(i)=(i−LevelBase[k])<<k`; `parent(i)=LevelBase[k+1]+((i−LevelBase[k])>>1)`;
`sibling(i)=LevelBase[k]+((i−LevelBase[k])^1)`; `nodeOf(f,2^K)=LevelBase[K]+(f>>K)`.
The forest-of-pallets is explicit: parent/sibling of a pallet root return InvalidNode.
`vreg → NodeID` is a dense `SmallVector<NodeID>` indexed by `Register::virtRegIndex()`
— not a DenseMap.

**V2 status (2026-07-31):** implemented + unit-tested (7/7) in the ssara-scaffold
worktree, uncommitted. `SSARegisterTreeV2.{h,cpp}` (~700 lines) + test (~390).
Node = `{Owner, Start, End}` (SlotPos uint32, LIS-free / target-independent — real
SlotIndex+LIS wiring is a later increment) + aggregates FreeLeaves + SubtreeMaxEnd
(so getNumFree is one compare) + a Gen tag for release-queue lazy-delete. Two-phase
UP-ONLY fold (occupy leaves descendants stale/"hidden"; isFreeNow pays an O(L=2-3)
ancestor-occupied walk to compensate). Release queue = explicit deterministic min-heap
keyed (End, Node) with Gen lazy-delete. `getNumFree(slot,W)` = dead-by-slot semantics
(occupied-now-but-dead-by-slot counted — the reload-feasibility-at-future-slot query).
DEFERRED (flagged in header): the §4-O2 `LI.covers + dominance` join fallback (only the
fast `End≤slot` compare exists; needs LIS); odd widths / VCC-M0 (§O5). These are later
increments, consistent with the committed SSARegisterTree's scope.

---

## 3. Two-phase update (root→leaf→root)

Assigning `vreg → S0` means S0, S0_1, and S0_1_2_3 are all occupied on that
range. Update walks **down** to address the leaf (collecting the ancestor path),
mutates the leaf, then **up** re-folding each parent from its (already-updated)
child and its unchanged sibling:

```
Summary(parent) = merge(Summary(changedChild), Summary(sibling))
```

Cost = O(tree height) = 2–3 merges for 32/64/128. Any composable aggregate can
ride this fold (free counts, packing pressure, occupancy mask). Stop early if a
parent's aggregate is unchanged.

---

## 4. What a node stores — `{Owner, start, end}`, a denormalized cache

> **AMENDED 2026-08-28.** One `{start, end}` per node cannot express a
> lane-restricted extent (a tuple whose dead lanes should not be claimed) nor a
> gap. See [[Lane_Accurate_Interference]] §4.

A node stores the **owning `Register`** plus a **cached `{start, end}` SlotIndex
pair**. LIS remains the single source of truth; the node's `{start,end}` is a
**denormalized copy** of `LIS.getInterval(Owner)`'s bounds, kept for **cache
locality on the hot scan** (a dense array of small PODs the prefetcher loves,
scanned with pure integer compares instead of `LIS.getInterval` indirection per
candidate).

**Invalidation contract (mandatory):** any callback that mutates an interval
(spill/split) MUST write the node's cached `{start,end}` in the same step it
updates `Owner`. Denormalized data is only safe with disciplined invalidation;
this is the price paid for the scan-speed win. (The `Owner`-only variant is
self-consistent by construction but pays `LIS` indirection per candidate — we
choose the cache + contract.)

- `end` answers "dead here?" for the free-check.
- `start` answers "born before current def?" for **spill-victim eligibility**
  (`start < currentDef`), so both the free-check and victim-check are pure compares.

**Caveat (do NOT lose this):** the `end < slot` integer compare is a
**point-in-linear-region** test, exact on a straight-line segment but **wrong at
CFG merges** — a value live down one path is not dead at `slot` just because its
numeric end passed on another. The fast compare accelerates the common case; at
joins fall back to real `LI.covers(slot)` + **dominance** ("true dominance, not
slot index alone"). See [[#11. Open questions & risks]] O2.

---

## 5. Interference collapses to `isFree()` (the SSA + dom-order dividend)

Homeless values are placed in **dominance order**. Consequence: **nothing is
assigned that *starts after* the current frontier.** So if a physical node is free
*now*, it is free for the whole not-yet-processed future (until we ourselves
assign it). The classical "does this interval interfere with those intervals?"
question **disappears**; it becomes "what is the state of this physreg at the
frontier?" — a two-state automaton per node: `FREE ⇄ OCCUPIED(until end)`.

**Not single-pass — but each inter-reset scan is locally single-pass-equivalent.**
The allocator is multi-pass; the loop is **not** an outer driver wrapping a
single-pass core, it is **implicit in the FSM's accept→reset→rescan cycle**
(§8–§9). The `isFree()`-only invariant only has to hold **within one scan between
two FSM resets**, not across the whole allocation. Every recovery transform is a
PASS, and every PASS forces a **reset that re-establishes the frontier from the
mutated program** — so there is no window in which the tree holds a stale
"free-forever" belief that a mid-run reassignment could contradict (a reassignment
*is* a transform, hence *is* a reset). Multi-pass convergence lives in the
automaton's cycle; the dom-order `isFree()` dividend is *scoped to a scan* and
re-armed by the reset. See O1.

**What "reset" means (precise):** not just FSM state — a full **re-sync to the
mutated program** of {FSM state, node `{start,end}` cache (O3), release queue
(§6)}. All three are re-established from LIS after a transform. Cheap because a
transform only touches a bounded region.

---

## 6. Timeline = a free release queue (space vs. time split)

> **AMENDED 2026-08-28.** The conclusion below — point queries suffice, so the
> interval-augmented structure is not needed — holds within ONE width pass.
> Coloring is width-descending and multi-pass, so the narrow pass's frontier has
> no ordering relationship to definitions committed by wider passes.
> `pickFreePhysReg` already compensates with range tests (`overlaps(VI)` across
> `ColorMap`, plus a `WiderDefs` list). See [[Lane_Accurate_Interference]] §3.

The tree indexes **space** (physregs). **Time** is a release queue, a *byproduct*
of assignment: at assign, `push({end, NodeID})`; at the frontier, pop everything
with `end <= Now` and mark those nodes free. The forest answers "what is free
now?"; the queue answers "what frees next." Nearly O(1) per event; for 32/64/128
the per-event tree update is 2–3 merges.

Point-pressure queries for reload feasibility (§8) are **cheap**: `getNumFree(slot,
W)` = scan the width-W level counting nodes dead at `slot`. This is a **point
query**, not a range query — the online sweep never needs "free over [a,b)", only
"free at a slot" — so the expensive interval-augmented structure is **not needed**.

---

## 7. The window driver & event-emitting scan

> **SUPERSEDED / REFINED 2026-07-31.** The window discipline and the
> driver↔FSM↔callback control flow were fully settled in the increment-2 design
> session. The authoritative version is in `Recursive_Recovery_Fix.md` §"Increment 2".
> Key corrections to what this section originally said:
> - **The FSM does NOT command window movement.** Earlier text ("the FSM commands
>   movement") is WRONG — it creates a back-edge that breaks the directional invariant
>   `window → DFA → callback`. The **window driver is the SOLE mover.**
> - **The ONE window rule:** window = `[uncolored def, first-forward-slot RP<Limit)`,
>   crossing blocks; the driver advances while **RP ≥ Limit**. That predicate is the
>   only thing that moves the window. No FSM movement commands, no callback feedback.
> - **The callback fires ONLY at DFA-ACCEPT** and returns 2-valued Resolved /
>   NotApplicable (the earlier `NeedMoreContext` is REMOVED — "need more context" is
>   just the DFA sitting in an intermediate state while the driver keeps advancing).
> - **Diamond detection is free** — chasing the RP drop necessarily crosses the PHI
>   join (that's where pressure peaks); no dedicated look-ahead.
> - **Lookahead bounded for free** — classify values by "used WITHIN the window?",
>   never chase a crosser to its far-away use site; max-window cap as adversarial backstop.

The window is a **cursor + accumulated local context**, positioned at a homeless
value's def. It grows forward while RP ≥ Limit (the sole move predicate above).

The **scan itself emits events**. While walking the width-W level looking for a
free reg (an unavoidable pass), a busy node whose interval crosses the tight region
emits `CrossLiverDetected` — collected as a *byproduct*, not a separate analysis
pass. Events are discretized coordinate changes:
`EnteredDeficit / CrossLiverDetected / ReachedPHIFrontier / PhiDensityExceeded / …`

Patterns are recognized over the **evolution** of window state along the sweep, not
over CFG shape and not as isolated local `if`s (see [[Architecture]] pattern
matcher).

---

## 8. The recovery FSM & the atomic callback contract

`NoFreeReg` after a scan drives the FSM. Recognizing a pattern yields a
**proposal**; the callback executes it.

**PASS is a hard contract.** If the FSM reaches an accept state, the callback MUST
transform and return true, else `report_fatal_error` — a PASS the callback can't
honor is a model bug, not bad luck. Therefore **applicability is part of
recognition**: don't accept "there is a deficit + live-through", accept "…and at
least one eligible spill candidate exists" (a coordinate like
`NumEligibleCandidates > 0`).

**`false` ≠ allocator failure.** `false` = "this hypothesis rejected; matcher stays
available." The FSM keeps moving / matching other patterns.

**The callback owns victim selection.** It has the spill API and the full context;
the FSM only recognizes *configuration + region*. Do not encode `spill v17,v23`
in the state — encode `Pattern=CrossSpill, Region=[entry,exit], deficit satisfied,
uses-outside satisfied`; the callback picks the vregs.

**Atomicity (the termination guarantee):**

> A callback returns true **only if** it leaves the program in a strictly better,
> fully legal state: the homeless LI resolved **and** every reload it introduced
> placed where **RP ≤ Limit** (checked via `getNumFree(reloadSlot, W)`, §6).
> Otherwise it **changes nothing** (transactional rejection — a true no-op) and
> returns false. **A callback must never leave the worklist larger than it found
> it.**

Chosen for v1 (option 1). The alternative (option 2: feed reload remnants back
into the worklist) risks non-termination and is deferred — it would require
replacing the no-progress guard with a potential-function argument.

Composition of transforms is still available two ways **without** breaking
atomicity: (a) a *smarter* callback resolves a multi-value composition **inside**
one transaction (it has all the context); (b) **cross-round** composition falls
out for free — value J fails round 1 and rotates to the back; value K succeeds and
frees registers in the shared tight region; J is retried next cycle against the
relieved state and now succeeds. (b) is safe precisely because it re-tries
*existing* worklist entries against an improved state — it never *grows* the
worklist (unlike option 2).

Example FSM excursion (divergent diamond):
`Scanning --CrossLiverDetected*--> Scanning --NoFreeReg[HasCrossLivers]-->
TrySpillCrossLivers`. If that callback returns false (all reloads land back in the
tight region), the FSM enters `ExpectingPHIFrontier`, moves **forward** until a
PHI-frontier event, and invokes `spillPhiWeb`. The fixed
`crossLiver-false → ExpectingPHIFrontier` transition is a **guarded search hint**
(safe because both the frontier event *and* the callback's self-check gate it), not
a blind fallback.

---

## 9. The driver loop (terminating)

```cpp
worklist = domOrdered(Homeless);
sinceProgress = 0;
while (!worklist.empty()) {
  if (sinceProgress >= worklist.size()) break;   // full cycle, no progress -> unrecoverable
  LI = worklist.pop_front();
  reg = scanForFreeReg(LI, W);                    // emits CrossLiver etc. on the way
  if (reg) { assign(LI, reg); sinceProgress = 0; continue; }
  FSM.consume(NoFreeReg);
  advanceWindowUntil(patternMatched || noPatternExpected);  // SelectionDAG-style
  if (patternMatched && callback(LI)) {           // atomic: LI resolved (+maybe others), reloads clean
      FSM.reset();
      sinceProgress = 0;                          // real progress (worklist shrank / reg freed)
      continue;                                   // restart from front, dom order
  } else {
      worklist.push_back(LI);                     // rotate to back
      sinceProgress += 1;
      FSM.reset();
  }
}
```

**Termination:** every iteration either shrinks the worklist (success) or
increments `sinceProgress` (failure); the worklist never grows (atomic contract);
`sinceProgress` reaching the current worklist size = a full cycle with zero
progress = provably unrecoverable → stop. This **replaces both** `MaxRounds` and
the identical-set "no-progress break" (the latter was too strict — a *crawling*
set fooled it; this guard cares whether anything *happened*, not whether the set
*looks* identical).

**Window reposition:** on both success and fail, the next iteration positions the
window at the **next worklist entry's own def** — the forward excursion of
`ExpectingPHIFrontier` is discarded, never inherited.

**Progress = worklist shrank OR a physreg was freed** (a callback that spills
*others* is progress even if it didn't assign LI) → reset `sinceProgress`.

**"Tried" is per-cycle, not persistent:** a value that failed can succeed after a
later transform frees registers; don't permanently abandon it within the loop.

---

## 10. Dead-state / window-growth floor

`advanceWindowUntil(… || noPatternExpected)` must have a reachable dead state, or a
value with no matching pattern drags the window to end-of-function (compile-time
blowup). Dead state =

```
noPatternExpected == (pressure recovered below limit)          // the failure region ended
                     OR (no new event on last expansion)       // fixpoint
                     OR (FSM state has no accept-reachable edge)// exhausted
```

The **pressure-recovered** clause is the hard floor: once the window leaves the
region where RP ≥ limit, the failure that triggered the excursion is over — nothing
left to explain, so stop.

---

## 11. Open questions & risks

- **O1 — RESOLVED: multi-pass, loop implicit in the FSM.** Earlier framed as a
  binary (single-pass vs. recovery-rounds); that was a false dichotomy. The
  allocator **is multi-pass**, but the loop is not a separate outer control
  structure — it is the FSM's **accept→reset→rescan cycle**. `isFree()`-only
  interference (§5) is valid because it is scoped to **one scan between two
  resets**, and every transform (= every reassignment) is a PASS that forces a
  full re-sync reset. So multi-pass does **not** reintroduce `overlaps()`. The
  remaining obligation is the re-sync discipline (O3), not a design choice.
- **O2 — slot compare vs. true dominance.** The cached `end < slot` fast path is a
  linear-region approximation; correctness at CFG joins needs `covers` + dominance
  (§4 caveat). Must not let the fast compare masquerade as the full liveness test.
- **O3 — re-sync discipline (the real O1 obligation).** A reset must re-establish
  {FSM state, node `{start,end}` cache, release queue} from LIS. Two sub-parts:
  (a) *node cache* — every interval-mutating callback rewrites the node's
  `{start,end}` (a missed update = stale death point = miscompile-class bug);
  (b) *release queue* — a callback that shortens/splits a victim must fix its
  queue entry (lazy-delete + generation tag, or re-push), else a stale death event
  fires at the old `end`. Consider a debug-only cross-check
  (`node.end == LIS.getInterval(Owner).endIndex()`). This discipline is what makes
  the multi-pass FSM loop sound (O1); it is *mandatory*, not optional.
- **O4 — atomic-spill insufficiency.** v1 atomic callbacks reject compositions only
  solvable in two dependent steps within one transaction; those show up as fails
  where Greedy succeeds. Acceptable (cross-round pickup often recovers them); the
  forensic log should cluster "atomic-spill-insufficient" cases to size the loss.
- **O5 — odd widths & non-tree scalars.** The clean 32/64/128 forest doesn't cover
  96/160/224 (no single node) or VCC/M0 (outside the aligned tree). Same D2/D3 gap
  as [[Architecture]]; needs overlapping-index / composite nodes / side-tracking.
- **O6 — "no discrete patterns" tangent (rejected).** The session drifted to
  "maybe there are only continuous decision surfaces, no patterns"; self-corrected.
  Patterns ARE discrete, structural, hand-specified predicates (divergent diamond,
  cross-spill). ML ranks *instances/parameters/ordering of overlapping matches* —
  it does **not** replace recognition. Do not let the continuous-surface framing
  leak into the design.

---

## 12. Relationship to the committed `SSARegisterTree`

The committed increments (2a core occupancy, 2b packing pressure, 2c
`pickFreeAligned`) implement an **occupancy structure over abstract leaves** with
its *own* bitvector/counter state and O(log N) descent pick. The tree in this
proposal is a **different object**: `{Owner, start, end}` per node backed by LIS,
level-iteration search (not descent), a release queue, and event-emitting scan.

**The committed tree is a validated stepping stone, not the final shape.** It is
correct, unit-tested, and the current **shadow integration** uses it fine for
divergence logging. This proposal is its *next* form. A future increment migrates
the node representation and search model; the shadow's divergence data (tree vs.
real allocator) is exactly the signal that will guide when/where to flip.

---

## 13. The ML end-state (offline FSM synthesis)

The training/replay formalization is in [[SSARA ML training formalization]]
(memory) — the **track** = `obs0 + [(callbackID, Region)]` as one format for
replay + demonstration + matcher output; replay = policy injection on the
decide/execute seam. The ambition recorded from this session: the neural net
**optimizes the FSM offline** (states, transitions, incidence matrix) under a
multi-criteria cost `J = allocation_quality − α·#states − β·#transitions − …`, then
a **deterministic FSM** is distilled and shipped. *"The neural network is not part
of the compiler; it is part of the compiler development process."* The compiler
keeps a deterministic, inspectable automaton — no black box in the allocation path.
