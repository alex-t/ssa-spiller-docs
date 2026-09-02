# Recursive Coloring-Time Recovery — Fix for the `width-N remainder` Crash Cluster

> Source Mapping: AMDGPUSSARegisterAllocator.cpp (runOnMachineFunction recovery
> dispatch ~4230-4355; trySplitColorViaBlocker :2064; trySelfSplitColor :2256;
> colorOneInPlace :1083). Related: [[project_coloring_feasibility_gap]] (memory),
> RegisterTree_Driver_FSM.md.

Status: **INCREMENT 1 DONE + DEFAULT ON** (2026-07-31). Committed `09f4138d484b`
(fix) + `f26f39073374` (flag default ON). Corpus cycle 2 measured: **crashes 68→27,
dominant cluster `width-1 remainder` 48→5, ZERO true regressions**; SSARA lit 12→10.
Flag `-amdgpu-ssa-recursive-recovery` now default ON (pass `=false` for old behavior).
Remaining cost = compile-time on ~10 pathological many-colorfail functions
(bitcast_v64i8_to_* = 83 colorfails/fn; full 512bit file 127s forensic-off) — the
target of **increment 2** below. See [[project_ssara_resume_after_weekend]] for the
cycle-2 numbers and the timeout investigation.

## Root cause (proven from captured obs0, bitcast_v16i32_to_v64i8)
The point-of-failure recovery has a **non-terminating floor**. Dispatch today:
1. `trySplitColorViaBlocker` (spill/split around a live-through blocker) — gated
   `EnableSplitLiveRanges`, DEFAULT OFF → skipped on the default path.
2. `trySelfSplitColor` — same gate, skipped.
3. PHI-web spill — `EnablePhiWebSpill`, SUSPECT.
4. **spill-homeless floor:** `spillOneVMP(Failed)` then `ColorInPlace(Failed stub)`
   + `ColorInPlace(each reload redef)`.

The floor is NOT terminating: spilling the homeless creates **reload redefs**, and
those reloads hit `assert(colorOneInPlace(reload))` — because the reload
re-saturates the same region (H1). obs0 shows both ends: the span_free colorfail AND
the fatal ColorInPlace at 64/64-full occupancy.

## User's clarifications (2026-07-31) — these override stale memory
1. **No pre-spiller pass exists.** The "C1a up-front must-spill gate" framing is
   dead — spilling is inline at coloring time.
2. **Up-front spilling is blind to per-point occupancy** ("how many to spill?" is
   unanswerable without doing the coloring). The decision MUST be reactive, at the
   failure point, with real occupancy.
3. **`report_fatal_error "needs more up-front spilling"` (:2301) is now MISLEADING**
   — must be deleted/changed (there is no up-front spiller to feed).
4. **The recovery IS:** at no-free-width-N → spill/split AROUND blockers; else spill
   the homeless itself. And the floor must actually resolve.

## The fix — recursive recovery (user-chosen)
Make spill-homeless a **fixpoint**: a reload redef that can't color re-enters the
same recovery. Four parts:

### Part 1 — factor dispatch into `recoverUncolorable(Register R) -> bool`
Pure refactor (behavior-neutral): move the dispatch chain (blocker-split →
self-split → [web] → spill-homeless) into one method returning whether R was
resolved. Callers currently inline in runOnMachineFunction (~4236-4355) call it.

### Part 2 — recurse on reload redefs
In the spill-homeless floor, instead of `ColorInPlace(reloadRedef)` (which asserts),
do: `if (!colorOneInPlace(reloadRedef)) recoverUncolorable(reloadRedef);`. A reload
redef is a FRESH, strictly SHORTER value ([reload-pt, next-use]) → well-founded
recursion on live-range length. Same for the stub.

### Part 3 — honest terminal floor (replaces the assert + misleading fatal)
Recursion bottoms out at a single def-use-adjacent point. The ONLY genuine terminal
is **true point-over-pressure**: > limit values live at one instant (can't fit 65
live in 64 regs at a point — no recovery exists). Detect that explicitly and emit an
honest diagnostic WITH THE REAL NUMBERS (live count vs limit at the point), NOT
"needs more up-front spilling". Everywhere else recovery must make progress.
- Replace `assert(OK && "width-1 remainder must be colorable")` (:4288) — recursion
  removes the assert; if the honest floor is hit it's a real report_fatal_error with
  point-pressure numbers (or a graceful bail, TBD).
- Replace the :2301 `report_fatal_error "...needs MORE up-front spilling"` message
  (in trySelfSplitColor's MustColor) with the honest point-over-pressure message, or
  route it through recoverUncolorable too.

### Part 4 — enable blocker-split/self-split on the DEFAULT recovery path
User point 4 tier-1 ("spill/split around blockers") must run by default, not behind
`EnableSplitLiveRanges`. Under the new flag, the dispatch tries blocker-split +
self-split unconditionally (they're the right first move; they return false cleanly
when inapplicable). Keep the SUSPECT PHI-web path gated separately.

## Termination argument (must hold — worse than the assert if it loops)
- Each reload redef has a STRICTLY SHORTER live range than its source (reload lives
  [reload-pt, next-use]); recursion is well-founded on range length.
- Bottoms out at def-use-adjacent single points.
- Genuine terminal = point-over-pressure (>limit live at an instant) → honest error;
  no recovery exists there by counting.
- Blocker-split/self-split only RELOCATE (spill a blocker across, keep reload in its
  own PR) → they free a through-lane without growing the problem.
- INVARIANT: every recovery step either colors R, or reduces R to strictly-shorter
  reload redefs, or hits the honest point-over-pressure floor. No step grows live
  ranges. ⇒ terminates.

## Rollout / safety
- **New flag** (e.g. `-amdgpu-ssa-recursive-recovery`, default OFF) wraps parts 2-4.
  Default path stays byte-identical until corpus-gated. Part 1 (refactor) is
  behavior-neutral and can be unconditional.
- **Verify:** clears `bitcast_v16i32_to_v64i8` (tahiti) — the captured crasher; then
  the bitcast series 512-960bit; then `--rerun-failed` over the cycle-1 `failed.txt`
  to count how many of the 48 width-N crashes it clears + zero new.
- **Corpus gate** before flipping default (user authorizes the run).

## Two increments (sequencing decided 2026-07-31, user chose "floor first")
This fix is INCREMENT 1 of 2. They compose; they are not alternatives.

### Increment 1 (THIS doc, in flight) — mechanical terminating floor
Make recovery terminate: recursive spill-self as the always-safe completeness
guarantee. Dispatch stays **try-and-see** (call trySplitColorViaBlocker → if false
trySelfSplitColor → if false spill-homeless-recursively). Each strategy discovers
its own inapplicability by attempting and returning false. This is the SAFETY NET —
verifiable now against the captured crasher, flag-gated. It is NOT wasted under
increment 2: even a perfect classifier needs a provably-terminating "no pattern
matched" floor, and that floor IS recursive spill-self.

### Increment 2 (NEXT — FULLY SPECIFIED 2026-07-31) — window driver + DFA + classify-before-dispatch
The [[project_recovery_pattern_classifier]] design, applied here. Replace
try-and-see with **classify the failure first, dispatch to the strategy whose
precondition PROVABLY holds**. The session below closed every open control-flow
question; this is a complete, terminating spec.

#### The ONE window rule (the whole driver)
> **Window = `[uncolored def slot, first-forward-slot where RP < Limit)`, crossing
> block boundaries, growing along the scan/dominance path. The driver advances
> forward while RP ≥ Limit. That predicate is the SOLE window mover.**

Everything else is observation *within* that window. Consequences:
- **Initial window** = `[def, first RP<Limit forward)`. NOT clamped to block end
  (the diamond's PHI join is in the *next* block; clamping would hide it).
- **What initiates a window move?** RP ≥ Limit — a driver-internal predicate. Nothing
  else. No look-ahead-for-crosser-uses trigger, no callback feedback.
- **Diamond detection is FREE.** The PHI join in a divergent diamond IS where pressure
  peaks (all incoming values live at the join edge). "Extend until RP<Limit"
  necessarily crosses the PHI frontier — pressure doesn't drop until past the join.
  So the diamond becomes visible as a byproduct of chasing the RP drop; NO dedicated
  look-ahead step.
- **Lookahead is bounded for free.** You never chase a crosser to its use site. You
  classify each value live in the window by "used WITHIN the window?" — a bounded
  question (window = tight region). A crosser used 40k instrs away is still just
  "no interior use" without reaching the use. Backstop: a max-window cap → if RP never
  recovers within the cap, treat as genuine over-pressure (honest terminal / floor).

#### Directional invariant: window → DFA → callback (NO back-edge)
The event stream is one-directional. The callback must NOT drive the window.
Achieved by: **the callback fires ONLY when the DFA reaches an ACCEPT state.**
- While the pattern is incomplete (cross-livers seen, join not yet reached), the DFA
  sits in an INTERMEDIATE state → no callback → the driver keeps advancing (this
  "window growth" is just "DFA hasn't accepted yet", not a callback request).
- The 3-valued `NeedMoreContext` return I earlier proposed is REMOVED — "need more
  context" is not a callback outcome, it's the DFA being intermediate. Callback return
  collapses to 2-valued: **Resolved / NotApplicable**. Neither moves the window:
  - `Resolved` → program changed → DFA.reset(), driver repositions to next uncolored.
  - `NotApplicable` (accept was a false match) → DFA.reset(), driver CONTINUES its
    existing forward scan (does not rewind).
- DFA `DEAD` (pressure recovered / pattern impossible) → reset, driver keeps scanning.

Loop shape:
```
while (driver has program left):
    event = driver.nextEvent()          # window advances, emits state-delta events
    state = DFA.consume(event)           # pure: event -> state, NO window control
    if state == ACCEPT(pattern):
        r = callback(pattern)            # callback fires ONLY here
        DFA.reset()
        if r == Resolved: driver.repositionToNextUncolored()
        # NotApplicable: driver continues forward from here
    elif state == DEAD: DFA.reset()      # driver keeps scanning
    # else intermediate -> loop; driver advances == "window grows"
```

#### Feasibility proof: cheap classify picks ONE strategy; heavy proof in that callback
Two tiers of precondition:
- **Cheap structural** (DFA/scan, near-free byproduct): is there a cross-liver? is
  Failed width-1? span_free=0? does the cross-liver terminate at a PHI-join ahead?
- **Heavy feasibility** (reload placement RP≤limit via getNumFree): runs INSIDE the one
  chosen callback, ONCE — not N times across trial strategies.
The v64i8 hot case (83 width-1 colorfails/fn) is classified structurally straight to
direct-spill — it NEVER pays the heavy reload check and NEVER tries
blocker-split/self-split. That is the compile-time win (try-fail-fail ×83 →
classify-cheap→dispatch-once).

#### Pattern taxonomy + preconditions (dispatch priority order)
1. **Cross-liver blocker** — ∃ live-through blocker over the tight region, reloads land
   where RP≤limit, AND **does NOT terminate at a PHI-join ahead** (the diamond
   disqualifier — computed structurally, refutes the doomed attempt without a callback).
2. **Self-split** — Failed IS the long liver (livethru=0), point-feasible, clean split
   boundary.
3. **Width-1 span_free-unsound** — width-1, span_free=0, no blocker → direct spill (the
   v64i8 case; the ~⅔ compile-time win).
4. **Genuine point-over-pressure** — >limit dwords live at an instant → honest terminal.
5. **No pattern** → **recursive spill-self floor** (increment-1 completeness guarantee).

#### Divergent diamond → spill-self floor + LOG (user decision 2026-07-31)
The diamond's correct strategy is web-spill, but web-spill is UNPROVEN (§ web-spill
below). Decision: **detect the diamond structurally (disqualifies cross-liver, avoids
the doomed attempt), route to the recursive-spill-self floor (safe), and EMIT a
forensic `strategy-deferred` event** so the analyst can validate the precondition and
quantify the cost of not web-spilling. Event carries the diamond SIGNATURE (join block,
phiCount, crossLivers+widths, tightRegion) + the TAKEN cost (spill-self spills/reloads/
sites). Framed as "classifier INDICATED web-spill; NOT validated" — a hypothesis for
the analyst, not ground truth (same discipline as pilot-pair confidence markers). This
closes the loop: defer the risky strategy AND generate the exact data to decide whether
to un-defer it (increment 2b).

#### Loop-carried web = a SECOND web sub-pattern (discovered 2026-08-03 from stage-1 smoke)
Digging the stage-1 window smoke on `bitcast_v16i32_to_v64i8` surfaced this
(the "digging bugs sharpens the classifier" model). A **loop-carried value** —
defined in the loop body, live across the back-edge, consumed by the loop header
PHI — is STRUCTURALLY the same shape as a divergent-diamond web: PHI root +
operands forming a value-merging network. Evidence: `%951` (def bb.3) feeds
`%952 = PHI undef,%bb.0, %951,%bb.3`; `%954` feeds `%953 = PHI %952,%bb.1,
%954,%bb.2`. The window walk correctly follows the back-edge one hop to the header
(endSlot < startSlot because the header is earlier in layout — NOT a walk bug).
- **Taxonomy grows:** web-spill has TWO structural sub-cases — **diamond-web**
  (join PHI across mutually-exclusive EXEC arms) and **loop-web** (header PHI across
  a back-edge). Both detected structurally; both route to the deferred web-spill slot.
- **Detection (cheap, structural):** the failed value feeds a PHI whose corresponding
  operand arrives via the back-edge block where the window stopped.
- **Handling in increment 2 (parallel to the diamond):** detect loop-web → route to
  the recursive-spill-self FLOOR (safe; web-spill impl still deferred/unproven) →
  emit `strategy-deferred: web-spill (loop-carried)` with the loop-web signature
  (header PHI, back-edge block, carried value) for the analyst. Web-spill ACTION
  admitted only in increment 2b, gated on validated precondition.
- **Window stop-reason is an ENUM** (not two bools): `StopReason { RPRecovered,
  ForkDivergence, BackEdge, Cap }`. A window stops for exactly one reason; BackEdge
  is the loop-web signal (distinct from ForkDivergence) and must not be lumped in.
  The visited-set guard is KEPT (prevents a real multi-hop loop from spinning) but a
  single back-edge hop to a header is now a CLASSIFICATION, not a give-up.

#### Web-spill = designed slot, unfilled (safety)
The old web-spill regression ("Use not jointly dominated by defs") was a CATEGORY
ERROR — web-spill dispatched on a value that wasn't a divergent diamond (the invalid
RegS/RegE fallback path). The classifier's structural diamond detector IS the missing
provable precondition. But admit web-spill only AFTER validating (against corpus obs0)
that the diamond detector fires exactly on real diamonds and nowhere else. Increment 2:
slot declared, unfilled, diamond routes to floor + logs. Increment 2b: admit web-spill
gated on the validated diamond precondition.

Composition: **classifier chooses the strategy by provable precondition; the
increment-1 recursive spill-self is the always-safe fallback for the "no precondition
matched" arm.** Validate each precondition against the cycle-1/cycle-2 forensic obs0
(captured cross-liver / span_free / occupancy facts are exactly the classifier's inputs).

## Open sub-questions
- Honest terminal: hard `report_fatal_error` with numbers, or graceful "genuinely
  infeasible, spill to scratch and continue"? (SSARA's premise says coloring must
  succeed; a genuine point-over-pressure means the function needs >limit regs at a
  point — that's a real limit, arguably a legitimate hard error. Decide.)
- Recursion depth bound as a backstop (defensive cap + honest error if exceeded)?
- Does blocker-split-on-default regress the tuple-fragmentation cases it was gated
  away from? (The 2026-07-21 corpus bisect: split ON fixed 5 colorfails, +3
  downstream-known regressions. Re-measure under recursion.)

## Stage-2 design decisions (2026-08-03 session — deep dive on web-spill feasibility)

Context: cycle-3 analyst found the recovery population is BIMODAL — RPRecovered
(local RP-spike, ~50%) vs ForkDivergence (PHI-web, ~31%); BackEdge/Cap never fire.
So stage-2 dispatch is a FLAT 3-branch `classify()`, NOT an FSM (YAGNI — no temporal
sequence to recognize; the window collection already did the "recognition").

### Decisions locked
1. **classify() = flat 3-branch** (in RA), not an FSM:
   - `WebPhi != 0`      -> web-spill
   - `!Crossers.empty()`-> cross-liver spill
   - else (default)     -> SelfContained floor (self-split, then recursive memory-spill)
   Strict dispatch (option A): the matched strategy runs; on failure FALL THROUGH to
   the floor. Self-split lives ONLY in the floor now (not a per-strategy retry).
2. **self-split / spill-self are NOT patterns** — they are the "no precondition
   matched" floor (the crosserCount==0 population, ~17%). Already built (increment 1).
3. **Mutual exclusion is a pure CFG property — NOTHING to do with EXEC** (CF already
   lowered; uniform-scalar and divergent-vector are identical here). The `LI.overlaps()`
   decline gate in spillPhiWeb is CORRECT and load-bearing: CFG-edge-exclusivity is
   NECESSARY BUT NOT SUFFICIENT (two operands from exclusive edges can still overlap
   BEFORE the fork if defined upstream & live across it). `!LI.overlaps()` is the real
   non-interference proof — KEEP IT AS-IS. (Retracted two wrong turns: it is neither
   unsound nor replaceable by edge-exclusivity.)
4. **Reload sites are known up front** = the uses of the (deletable) PHI result /
   web members' external uses. Because def dominates all uses (SSA), the exact RP
   RELIEF of spilling a value == its Width — trivially computable in place, sound on
   pre-spill MIR (no need to "measure post-spill MIR", which was the layer-4 trap).
   PHI-web cumulative relief APPROXIMATED as Width(PHIResult) (treat web as one def-use);
   refine later if data shows it matters.
5. **Feasibility = unified `reloadRPBeforeUse`** (already exists; its comment: post-spill
   RP at the use via -W+W cancel). Do NOT speculatively add/remove terms (e.g. the
   uncolored-spanner term or the RPb-only variant) — UNIFY on reloadRPBeforeUse and let
   the CORPUS + analyst decide the open question below. 
   - OPEN (for analyst, post-corpus): should feasibility count UNCOLORED SPANNERS as
     consumers of the reload-site room? Current webReloadFeasible does (added to protect
     %886 from round-over-round inflation). Counter-view: uncolored peers will THEMSELVES
     be recovered (worklist), so counting them as fixed supply over-rejects (same
     pessimism as measuring pre-spill MIR). Keep the term for now; let data settle it.

### Layering (folds into cleanup task) 
6. **webReloadFeasible is OVERLOADED** — it does BOTH (a) PHI-web detection/closure
   (root resolve + bidirectional member walk + external-use collection, lines ~2013-2066)
   AND (b) reload feasibility (the RP loop, ~2067-2092). In the new design, (a) BELONGS
   IN THE WINDOW DRIVER — it re-derives the web the driver already computed (webPhi seed +
   closure). Split: window driver owns web detection/closure and outputs the closed member
   set + external uses (extend RecoveryWindow); the feasibility check keeps ONLY the RP
   loop (b), consuming the driver's output. Delete the duplicated detection.
7. **All recovery strategies move to the Emitter** (spillCrossLiver [renamed from
   trySplitColorViaBlocker — it SPILLS a cross-liver, not "splits color"], self-split,
   memory-spill floor join spillPhiWeb). RA classify() only DISPATCHES. RP access unified
   as a passed-in FUNCTOR `function_ref<unsigned(MachineInstr* useSite)>` (= reloadRPBeforeUse).

### Refactor ORDER (agreed)
A. Move handlers -> Emitter + unify RP getter as functor + rename (cleanup task #25).
B. Move web detection/closure -> window driver; slim webReloadFeasible to the RP loop (#6).
C. Wire RA classify() dispatch against the unified Emitter layer (#26), feasibility via
   the functor.
Then corpus + analyst on the result (settles the open uncolored-spanner question).

## ARCHITECTURE PRINCIPLE (2026-08-03) — Emitter = mechanics, RA = policy

Verified by dependency scan (retracting the earlier "move all handlers to Emitter"
premise, which was BACKWARDS — it would drag ColorMap/colorOneInPlace/commitColor
into the Emitter):

- **Emitter = pure spill/reload/SSA-repair MECHANICS.** Emits stores, reloads,
  repairs SSA. No coloring, no pressure/feasibility reasoning, no policy.
- **RA = ALL policy + coloring:** candidate finding (occupancy), physreg decisions
  (commitColor/colorOneInPlace), recolor-after-spill, RP/feasibility reasoning,
  reload-placement policy.

Evidence: trySplitColorViaBlocker/trySelfSplitColor touch ColorMap(×5)/commitColor/
colorOneInPlace/MaxVGPRIdx — they COLOR, so they correctly live in RA. spillPhiWeb
touches ZERO RA color state (only the ColorFreshVReg callback) — it correctly lives
in the Emitter for the EMISSION half, but its web-closure + overlaps-gate +
feasibility are POLICY that must move OUT to RA/window-driver (task #27).

RP queries in the Emitter split by caller:
- reloadRPBeforeUse, reloadRPAtBlockEnd — RA-called feasibility POLICY -> move to RA NOW.
- getMaxRPForBlock, maxRPBetween, getMaxRPInBlockDownTo — Emitter-INTERNAL, drive
  reload-PLACEMENT inside emitReloadsAndRepairSSA -> moving them needs extracting
  placement policy = the DEFERRED deep inversion (task #28).

Staging: NOW = rename spillCrossLiver + move reloadRPBeforeUse/reloadRPAtBlockEnd to
RA + RP functor (task #25). LATER = reload-placement inversion (task #28).
