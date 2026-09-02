# Shared Context — SSA RA Project

Cross-worktree knowledge base. Updated after significant sessions.
Last updated: 2026-09-02

## 2026-09-02 (evening) — READ THIS FIRST: current design docs moved to `04-Design/StandaloneRA/`

**Design truth now lives in `SSARA/04-Design/StandaloneRA/` — nine documents. Anything left at the
top level of `04-Design/` is STALE, including `Architecture.md` and `SSA_RA_Coloring.md`.** The move is
deliberate: staleness is now in the PATH of every search hit, because a status block inside a file does
not stop a topic grep from answering out of July material. Committed and pushed.

Current set: `Lane_Accurate_Interference.md`, `RegisterTree_Driver_FSM.md`, `Recursive_Recovery_Fix.md`
(authoritative over FSM §7), `SGPR_Spill_Lowering_In_SSARA.md`, `ssa_region_regalloc_design.md`,
`Width_Tiered_Coloring.md`, `Spiller_GCNRPTarget_Redesign.md`, `Permutation_Scratch_Reserve.md`,
`ACL_Pass_and_CallSite_Capacity.md`, plus the new
`Demand_Oracle_And_Cumulative_Spill_Planning.md`.

**Commit date is NOT an authority signal.** `SSA_RA_Coloring.md` and `ACL_Pass_and_CallSite_Capacity.md`
were committed 2026-08-28 with content last edited 07-23. Read the file's own Status block.

### New design decision — one demand oracle, cumulative spill planning

Full text: `04-Design/StandaloneRA/Demand_Oracle_And_Cumulative_Spill_Planning.md`; session detail in
NOTES §2026-09-02 (evening). User's two points:

1. **No scalar RP metrics anywhere.** ONE register-demand oracle backed by the register tree: at a slot,
   per (pool, width) tier in DESCENDING width order, Demand = values live needing that tier,
   Capacity = starts from `RegClassInfo::getOrder(RC)` passing `isSpanFree`, Deficiency = shortfall in
   RUNS. A dword count cannot express run structure or alignment, which are what decide colorability.
2. **Cumulative (set) planning.** Relief is NOT additive — whether two evictions yield a usable run
   depends on adjacency — so candidate selection must be over SETS with effect MEASURED by re-querying
   the oracle, never credited per candidate. This is FSM §11 **O4** (atomic-spill insufficiency).

`isSpanFree(first, w, [S,E))` is designed (`Lane_Accurate_Interference` §5) and exists in **NO code** —
neither `SSARegisterTree` nor `SSARegisterTreeV2`. Prerequisite: the leaf axis must be **hardware
register index**, not `getOrder` ordinal.

**Odd widths are CLOSED (2026-08-29), by canonical decomposition into maximal aligned nodes.** Over
leaves 0..3 a 3-wide run is `isFree(node 0..1) AND isFree(leaf 2)`, or
`isFree(leaf 1) AND isFree(node 2..3)`. FSM §11 **O5 is STALE** — it still calls this open and needing
composite nodes; that staleness caused the decision to be re-derived from scratch on 2026-09-02.

### Corrections that change pending work

- **Loop-carried liveness.** A value defined ANYWHERE in a loop, including the latch, is live across the
  WHOLE loop, because the back edge carries it. Any forward-hull-over-slots model is wrong. The
  `case3` removal in `costOfSpilling` is therefore **WITHDRAWN** until the demand model represents
  back-edge liveness. The `test2-peruse` removal STANDS (it measured pre-existing pressure, not
  pressure change, so it vetoed every candidate in exactly the regions needing one).
- **Do not quote the relief-error figures** (pre-spill 34% of events, median 84 / max 144 dwords;
  region-rp 20% / median 8). They compared summed `ExcessDrop` against a measured PEAK — different
  quantities. `SpillPlan::NewPeak` vs measured peak is now printed at both stages; no data yet.
- Gate order for spill/planner changes: the **83-command planner sweep** first
  (`scripts/corpus/planner83/`, `scripts/ssara_trace.py`), then `cf512` as the under-spilling canary,
  then corpus by bucket TRANSITION at `--timeout 300`. Never the lit suites.

### Still open from the docs rescue

`.gitignore` for the ~40 junk untracked entries that hid six design docs for a month; `AGENTS.md` still
points at `Architecture.md` / `SSA_RA_Coloring.md` instead of `StandaloneRA/`, so the new folder does
not yet reach a fresh session; the ACL doc's status line claims a default-off flag that was made
default-on and then deleted by `05dc22aa5401`; FSM O5 needs marking closed.

## 2026-09-01 (late) — THE PLAN for the next stages (user-set), plus three fixes applied

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, HEAD `0af845a0ed5a`. Detail:
`SSARA/08-Worklog/NOTES.md` §2026-09-01 sections G/H/I/J and §K (the plan).

### The four stages, in order

1. **Corpus CRASH to 0.** "Make the LIT suite green" means the CORPUS HARNESS, not the SSARA lit files —
   those were retired 2026-08-29 and are stale (see the standing entry below). The harness IS the AMDGPU
   lit suite for SSARA purposes. Current baseline `runs/corpus-0901-refreeze` = **CRASH 9** of 8246
   records over 3080 files. RISK: triage the 9 for design-impossibility FIRST, because a structurally
   impossible one cannot be closed and would block every stage behind it.
2. **Assembly correctness on every test**, delegated to a background agent. The harness classifies
   CRASHES and compares `NumVgprs/TotalNumSgprs/ScratchSize/Occupancy`; it does NOT check that the
   emitted code is right. Two levers already exist: the in-tree `-amdgpu-ssa-verify-value-flow`
   (+`-fatal`), kept expressly because it checks the resulting assembly, and the harness's per-run
   `asm/` directory, which makes a differential comparison against Greedy possible.
3. **Classify all `REGRESSION_OCC_OR_SPILL`** (90 records in the baseline). Goal: prove nothing is
   impossible BY DESIGN. Known structural candidates: no coalescing before allocation (PHI copies);
   whole-tuple occupancy, so a dead lane is capacity Greedy keeps and SSARA does not (`reportLaneWaste`
   measures exactly this); cross-call coloring, where a value live across a call may only take a
   preserved register and one-shot greedy cannot pack them; spiller reload placement.
4. **Cleanup, refactor, optimize — DIAGRAM FIRST.** Build the state diagram / workflow / call graph of
   the whole allocation before touching anything; then cleanup driven by that; then switch to
   `SSARegisterTree`. **The existing design docs are FAR OUTDATED** (user, 2026-09-01) — `Architecture.md`
   and the `04-Design/` call graphs describe a pipeline the code no longer has, so the diagram must be
   derived FROM THE CODE, and the docs are candidates for rewrite or deletion, never for citation.
   The **dead-code cleanup of Stage 4 is ALREADY DONE** (last week) — see the correction entry below.
   What remains queued for Stage 4: the Step 2 dedup of the two victim-selection loops, and
   `reduceRegionPressure`'s private CFG-blind pressure model.

### Applied this session — ALL COMMITTED AND PUSHED (verified by git, not memory)

`git status` clean of source changes; HEAD `cafaab029cbe` == `origin/weekend/prespill-widthaware`
(confirmed via `git ls-remote`). Only untracked scratch `.md` files remain in the tree. The two commits
are `850168403fa4` (Reserve-WWM re-freeze) and `cafaab029cbe` (the allocator trio).
DO NOT ASSUME UNCOMMITTED WORK — check `git status` and `git ls-remote` first.

| # | change | why |
|---|---|---|
| 1 | `AMDGPUReserveWWMRegs`: `freezeReservedRegs()` after `clearNonWWMRegAllocMask()` | stale frozen reserved set; fixed 2 crashes + 5 occupancy regressions |
| 2 | `relieveTightRegion` routed through `planSpill`, relief MEASURED not credited | tonga spilled ~400 values with the excess never moving (PHI-operand reload lands at the peak slot). TEMPORARY HALF-FIX — Step 2 dedup pending |
| 3 | `wholeBlockDemand` + `allocStride` as the pre-spill gate metric | `pressureOf` is lane-accurate but `markOccupied` claims the whole tuple: tahiti read 50 of 96 where the colorer needed 98 |
| 4 | live-through spill-blocker queues its evicted pieces | it erased the color + spilled (both committed) then returned NoOp, leaking an uncolored vreg to rewrite |

All 8 reproducer configs compile with `-verify-machineinstrs`; canaries match or beat Greedy. Gate:
`runs/corpus-0901-wholeblock` (pin sha `b7ab7ca7361d`) vs `runs/corpus-0901-refreeze`. Change 3 strictly
raises region peaks, so it strictly increases spilling — watch `REGRESSION_OCC_OR_SPILL` transitions as
closely as `CRASH`.

**AI commits stay prohibited** (potentially-public workspace, ruling of 2026-08-25). The user runs them.

### CORRECTION — the 2026-08-25 flag/dead-code inventory is OBSOLETE. Do not quote it.

Every removal it proposed LANDED LAST WEEK. Verified today by grepping the tree, after the user had to
correct an agent that recited the audit as if it were pending work:

- `75b0ea42c988` removed the width-tier virgin allocation order (`buildVirginTierOrder`, `analyzeTierRank`,
  `findNonInterferingGap`, the tier statistics).
- `05dc22aa5401` dropped the five flags that were on by default (`acl-coloring`, `pre-spill-wa`,
  `agpr-rescue`, `region-rp`, `phi-web-spill`).
- `400183d0ab0d` dropped `agpr-first` and kept its behavior.
- `pre-spill`/`preSpillToLimit` and `slot-delta`/`dumpSpanWidthDelta` are gone. NOTE the surviving
  `preSpillToLimitWidthAware` is a DIFFERENT, LIVE function — do not confuse the names.

`AMDGPUSSARegisterAllocator.cpp` now has exactly **6** `cl::opt`, NOT 13, and every one is
`cl::init(false)` diagnostics: `experiment-bail`, `verify-value-flow`, `verify-value-flow-fatal`,
`shadow-tree`, `lane-waste-dump`, `block-demand-dump` (the last is TEMPORARY measurement scaffolding for
the whole-block metric and is the one thing still slated for deletion). Remaining matches for the old
names are debug strings and `[Design: region-rp-reduction]` tags, not flags.

**META-LESSON, the user's actual complaint:** the documentation mess is a direct consequence of reciting
memory instead of reading the tree. `AGENTS.md` / `SHARED_CONTEXT.md` / `NOTES.md` entries older than a
few days describe code that has since been deleted. Treat every inventory, flag list, line number, and
"uncommitted state" claim in them as a LEAD ONLY; re-derive from `git log` + the source before stating it.

## 2026-09-01 — corpus 0831 is a REGRESSION; all 7 new failures are ONE bug: a stale frozen reserved-register set

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, HEAD `0af845a0ed5a` (unchanged —
nothing committed this session). Full detail: `SSARA/08-Worklog/NOTES.md` §2026-09-01. Design:
`SSARA/04-Design/SGPR_Spill_Lowering_In_SSARA.md`.

### Corpus `corpus-0831-phisimp-reserve` vs `archive-intervalfix-0829`

`HARNESS_EXIT=0`, 2906 s, 8246 records / 3080 files. **NET crashes 11 -> 11, which nets 2 real fixes
against 2 NEW crashes** — not a pass (`regression-baseline-is-truth`). Plus 5 new
`REGRESSION_OCC_OR_SPILL` records and 8 improvements.

| | test [config] | detail |
| --- | --- | --- |
| FIXED | `amdgcn.bitcast.1024bit.ll` [gfx1100], [gfx900] | compile now, but land in `REGRESSION_OCC_OR_SPILL` (below greedy) |
| NEW CRASH | `preserve-wwm-copy-dst-reg.ll` [gfx908] | PEI `failed to find free scratch register` |
| NEW CRASH | `schedule-amdgpu-tracker-physreg.ll` [tahiti] | `RegisterScavenging.h:81` in branch relaxation |
| REGRESSED | `si-sgpr-spill.ll` [tonga] | `main` **+216 VGPRs / occupancy -5**; `main1` +200 / -3 |
| REGRESSED | `schedule-amdgpu-trackers.ll` [gfx1100], [tonga] | +141 / -8 and +18 / -1 (trackers=1 configs) |
| REGRESSED | `attr-amdgpu-num-sgpr.ll` [fiji], `insert_vector_dynelt.ll` [fiji] | +56 / -6 and +57 / -4 |

### ROOT CAUSE — one bug, and it is pipeline state, NOT allocation quality

SSARA's output is unchanged. `MachineRegisterInfo` holds reserved registers as a FROZEN snapshot.
`SIRegisterInfo::getReservedRegs` :724 reserves every VGPR in `MFI->NonWWMRegMask`, which is the
COMPLEMENT of a small top-of-file WWM window — so while set it reserves nearly the whole per-thread
range. `AMDGPUReserveWWMRegs` :108 clears the mask but is `setPreservesAll()` and never re-freezes;
the only later refresh was `createVGPRAllocPass(true)` via `RegAllocBase::init` :66, which
`2296b3084604` skips under SSARA. So the WWM-era snapshot reaches PEI, `shiftWwmVGPRsToLowestRange`
finds nothing `isAllocatable` and `break`s on iteration 1, the SGPR-spill lane holders stay parked at
`v254/v255`, and `NumVgprs` (= highest index used) blows up. The scavenger reads the same snapshot,
which is the two crashes. The parking is BY DESIGN — `determineRegsForWWMAllocation` says *"Try to use
the highest available registers for now. Later after vgpr-regalloc, they can be shifted to the lowest
range."* We removed the "after vgpr-regalloc" point.

Proof without rebuilding: pre-PEI MIR **and** MachineFunctionInfo are identical between the two pins,
yet `-run-pass=prologepilog` on that same MIR makes BOTH pins shift to `v38/v39`, and
`-start-before=prologepilog` clears both crashes — because the MIR parser re-freezes
(`MIRParser.cpp` :663). **Reusable:** identical serialized MIR + different output => the difference is
non-serialized in-memory state; `-run-pass`/`-start-before` isolates it in one step, no bisect.

### Upstream order (confirmed) and the architectural consequence

`addRegAssignAndRewriteOptimized` :1714-1776 = SGPR RA -> ... -> `SILowerSGPRSpills` ->
`SIPreAllocateWWMRegs` -> WWM RA -> `AMDGPUReserveWWMRegs` -> **VGPR RA last** (same shape in the fast
path). That last position is load-bearing three times: only remaining re-freeze; the documented
"after vgpr-regalloc" point for the holder shift-down; and it allocates per-thread VGPRs AROUND the
reserved WWM window. SSARA sits in the SGPR slot but colours VGPRs there too, i.e. before holders or
the WWM window exist — which is what `VGPRReserve` compensates for by PREDICTING holder demand.
`availableOrder` withholds the reserve from the numeric-HIGH tail while the shift-back wants a LOW
register just above the coloured range: coupled by count only, never identity, so the prediction is
unverifiable.

### Decisions

1. Interim workaround now (re-freeze in `AMDGPUReserveWWMRegs`), **not** the pipeline fix — the RA code
   is still being cleaned up (`reduceRegionPressure` rewrite is step 1) and a re-plumb would land in
   moving code.
2. Full design parked in `04-Design/SGPR_Spill_Lowering_In_SSARA.md`, BACKLOG row marked GATED ON THE
   RA CODE CLEANUP: SSARA picks the holder physregs itself and `SILowerSGPRSpills` uses the PHYSICAL
   lane path for all spills (the path callee-saved spills already use for CFI reasons), deleting the
   window, the mask, WWM allocation for holders, and the shift-back.
3. `bitcast.1024bit` signatures moved: **tahiti** -> `GENUINE POINT-OVER-PRESSURE at 13056r` (the
   width shortage from 08-31, gate still pending); **tonga** -> `FEASIBLE YET UNRECOVERED at 4288r`,
   i.e. a RECOVERY bug and a different class. That resolves the 08-31 "tonga untriaged" question.
4. User presentation preference: **no option lists / multiple-choice** in replies, ever. Prose only.

## 2026-08-31 (night) — 3 fixes committed; tahiti `bitcast.1024bit` is a WIDTH shortage; width-aware gate PROPOSED

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, HEAD `0af845a0ed5a`.
Full detail: `SSARA/08-Worklog/NOTES.md` §2026-08-31.

### Committed and pushed

| commit | what |
| --- | --- |
| `2296b3084604` | `createVGPRAllocPass(true)` guarded by `!EnableSSARegAlloc`. On the SSARA path it enqueued ZERO values and made ZERO assignments (measured) — SSARA colors both files. WWM allocation stays greedy on both paths. |
| `26de7e397c6e` | VGPR reserve now also counts callee-saved SGPR spill lanes. `SILowerSGPRSpills` takes those holders with `findUnusedRegister` BEFORE the whole-wave reservation is computed, straight out of the reserve. Fixed 5 functions failing `cannot find enough VGPRs for wwm-regalloc` on `bitcast.1024bit [gfx900]`. |
| `0af845a0ed5a` | PHI simplifier: single-real fold compares the (register, sub-register) PAIR; `IMPLICIT_DEF` with only undef-flagged reads is erased; undef-flagging sub-flag removed. 32 folds + 96 erasures on the reproducer. |

`bitcast.1024bit`: both `gfx1100` configs and `gfx900` now compile. `tahiti` and `tonga` still fail.

### Status of `amdgcn.bitcast.1024bit.ll` per config

| gfx900 | tonga | gfx1100 x2 | tahiti |
| --- | --- | --- | --- |
| ok | CRASH (own signature, untriaged) | ok | CRASH (root-caused, fix proposed) |

### `tahiti` root cause — ALIGNED-PAIR saturation, not dword over-pressure

**Correction to a stale model:** the colorer has been LANE-ACCURATE since `0e7bbc24fdcc`
(`pickFreePhysReg`'s `claimsUnit` tests per-unit subranges). Proof it works: 23 ODD SGPRs are accepted
for 32-bit values in the failing function. Do NOT say "the colorer charges whole tuples".

`SReg_64_XEXEC`'s order has exactly 48 entries (47 even-aligned pairs + `VCC`; SGPR 64-bit is stride-2).
48 simultaneously live crossers — each a `%N:sreg_64 = S_LSHR_B64 ..., 24` whose ONLY use is
`PHI %N.sub0`, so `sub1` is dead at its own def — each hold the LOW half of a distinct pair. All 48
candidates are rejected `occupied-unit` while 48 odd registers sit free and are structurally unusable
for a 64-bit value. Lane-accuracy cannot help a value of the SAME width as the hole.

`findTightRegions` cannot see it: its gate is lane-accurate dwords (`GCNRegPressure::inc` charges
`getNumCoveredRegs`), reading 50 of 96, so ZERO regions are opened and `reduceRegionPressure` returns
before its own debug line — even though 48 zero-weight live-through candidates had been enumerated.
`-amdgpu-ssa-lane-waste-dump`: `tahiti pool=96 peakWhole=98 laneAtPeak=50 maxWaste=48` versus
`tonga pool=88 peakWhole=146 laneAtPeak=130` — the same function COMPILES on tonga because its
lane-accurate peak is already over the smaller pool. `tahiti` fails exactly where `lane <= limit < whole`.

`reportPointOverPressure` MISLABELS this class: it sums whole class widths, so it claims
`GENUINE POINT-OVER-PRESSURE: 98 > 96 ... no coloring-time recovery can fit them` when the lane-accurate
demand is 50 of 96 and spilling one crosser would fix it. Diagnostic-only fix, own commit.

### Width-aware tight-region gate — PROPOSED, awaiting approval

The predicate ALREADY EXISTS: `relieveTightRegion`'s `overSubscribed(W)` = `live(W) > floor(Limit/W)`
(RA `:1833-1837`) fires here at 49 > 48, but is only a victim-ORDERING key; the region-entry gate and the
stop condition are both total-dword, so it is never even computed. Proposal: compute it per slot in
`findTightRegions` and OR it into the gate; seed `relieveTightRegion`'s excess from it.

**Soundness (decides the design):** one width at a time is SOUND. The whole-width dword SUM is NOT —
48 dead-high pairs plus 48 32-bit values sum to 144 dwords and still fit, and this function does exactly
that. So keep the dword total lane-accurate and ADD the width test beside it. Group by WIDTH not by
register class (coarser but strictly stronger: all width-2 SGPR classes draw pairs from one file).
`floor(Limit/W)` overstates capacity when stride > W, which errs toward MISSING, never a false trigger.

**RISK:** strictly ADDS regions, so it spills MORE. `cf512` broke on UNDER-spilling, so the exposure is
the opposite direction — watch `REGRESSION_OCC_OR_SPILL` as closely as `CRASH`.

### Corpus run in flight at session end

`screen -S corpus0831`, out `scripts/corpus/runs/corpus-0831-phisimp-reserve` (persistent, not `/tmp`),
pinned `/tmp/ssara-pin-0831/llc` sha `78224533ce6b`, `--configs all --jobs 32 --timeout 300`. Baseline
`scripts/corpus/archive-intervalfix-0829`.

**HARNESS DEFECT:** `run.json`'s `git_head` records the head of `git_src` = **the DOCS repo**, not the
compiler tree, so no archive carries a compiler commit and archive identity is `llc_sha256` alone.
**PROCESS:** always `ninja -C build/user-debug llc` immediately before pinning a corpus binary — the
build was stale at this session's end.

## 2026-08-29 (evening) — migrated-def interval fix + identity-copy elimination; corpus gates A only; `bitcast.1024bit` STILL REGRESSED (OPEN)

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, session baseline HEAD
`0e7bbc24fdcc`; all of the below was UNCOMMITTED during the session. **Committed AFTERWARDS by the
user as `bc355db5e45a`** (`[AMDGPU] SSA RA: region pressure, migrated-def intervals, identity copies`,
alex-t, 21:58 UTC) — verified against `git log`, not assumed. `git diff 0e7bbc24fdcc HEAD` = +448/−305
over `MachineLaneSSAUpdater.{h,cpp}`, `AMDGPURebuildSSA.cpp`, `SSASpillEmitter.cpp`,
`AMDGPUSSARegisterAllocator.{h,cpp}`. That commit ALSO carries region-pressure work not described here,
so do NOT read it as containing only A and B.

### A. Live-interval malformation in SSA repair — the orphaned zero-length segment

Root cause of the `amdgcn.bitcast.512bit.ll` coloring failure. When `repairSSAForNewDef` retargets a def
operand to a fresh vreg, `shrinkToUses` trims segments but KEEPS THE DEAD DEF, leaving an ORPHANED
ZERO-LENGTH SEGMENT `[SlotN, SlotNd)` in the original vreg's main range and subranges. Six reload redefs
(`%1039`-`%1054`) each kept one, and each orphan still claimed `VGPR0_VGPR1` in the interference test —
**76 phantom live dwords**, which is what blocked the reload.

Fix, two parts: (1) `performSSARepair` gained a `SlotIndex MigratedDef` parameter and removes that value
from each affected subrange via `S.removeValNo(VNI)` BEFORE `shrinkToUses`; (2) new public
`rebuildMainRangeFromSubranges(OrigVReg)` clears the main range and calls
`LIS.constructMainRangeFromSubranges`, invoked ONCE PER VREG by the drivers — `AMDGPURebuildSSA` after
`finalizeCoupledUses`, `SSASpillEmitter` after the reload-repair loop.

**CAVEAT (unresolved).** The comment this fix replaced explicitly warned that
`constructMainRangeFromSubranges` aborts with `Use not jointly dominated by defs` when lanes are split
across vregs. The fix moves that call to DRIVER level (after all renames) on the ASSUMPTION that it is
then safe. That assumption is NOT yet fully validated — see the OPEN REGRESSION below.

### B. Identity copies were ENDEMIC, and erasing them fixed real crashes

Applied under `APPROVED: erase identity copies in the allocator`. New `eliminateIdentityCopies(MF)`
called from `rewriteStage` after `eliminateRegSequences`, plus `STATISTIC NumIdentityCopiesErased`. It
erases a `COPY` whose source and destination resolve to the same physical register, via the established
idiom (`RemoveMachineInstrFromMaps` guarded by `Indexes->hasIndex`, then `eraseFromParent`). Guards:
skip a `COPY` with >2 operands, skip virtual operands (another stage's file), assert physical operands
carry no subreg index, skip an UNDEF SOURCE (that copy is what makes the register appear defined).

**Scale: 167 identity copies across 33 of the 34 SSARA pipeline `.ll` tests**, including
`pipeline-linear.ll`, which spills nothing. Dominant source = kernel-argument live-in copies, an input
`%0 = COPY $sgpr4_sgpr5` colored straight back onto `$sgpr4_sgpr5` — the classic missing-coalescer
artifact; SSARA has no coalescer and Greedy never shows it because `RegisterCoalescer` runs first. Never
EMITTING one was already the convention in three places (`lowerPHIs` `SrcPhys == DstPhys`;
`eliminateRegSequences` `Src != Expected` / `S != D`; `resolvePermutation` `S != D` per dword); the gap
was only copies PREDATING the pass. After: 167 -> 0.

**KEY INSIGHT — NOT cosmetic.** `$vgpr0 = COPY $vgpr0` is both a def AND a USE, and the phantom use
fails the post-RA check `Use of $vgpr0 does not have a corresponding definition on every path`, aborting
with `LLVM ERROR: Use not jointly dominated by defs`. Erasing it FIXED two crashing configs of
`amdgcn.bitcast.1024bit.ll` (`gfx900`, `tonga`).

Verification: ZERO test transitions across all 121 tests in SSARA + SSASpiller + MachineLaneSSAUpdater
(102 pass / 19 fail, identical set on both binaries); the five live-allocator `.mir` failures produce
BYTE-IDENTICAL MIR either way; `amdgcn.bitcast.512bit.ll` passes all 5 configs on both binaries;
`-amdgpu-ssa-verify-value-flow` reports 0 violations across the SSARA `.ll` tests; no new clang-tidy
lints.

### C. Corpus run gates change A ONLY — CRASH 13 records/12 files -> 12 records/7 files

`harness_rescue.py` run against the FROZEN PRE-IDENTITY-COPY binary `/tmp/ssara-pin-0829/llc`, so it
gates A and NOT B. 3080 files, 8246 records, `--configs all --jobs 32 --timeout 300`, 2825s wall, in a
detached `screen` session `corpus0829`. **ARCHIVED** out of `/tmp` to
`scripts/corpus/archive-intervalfix-0829/` (19 MB: `results.jsonl`, `run.json`, `report.md`,
`failed.txt`, `harness.log`) — that is the baseline the NEXT corpus run must be diffed against. Note
`scripts/` is itself a git repo, so the archive is only durable once committed there. The pin
`/tmp/ssara-pin-0829/llc` was NOT archived (1.8 GB, rebuildable).

Versus `archive-rescuebound-0828`: CRASH **13 records over 12 files -> 12 records over 7 files**; off
the crash axis 22 keys better, 3 worse (`GlobalISel/llvm.amdgcn.wmma_64.ll` [gfx1100+gisel]
`DIFF_COALESCING -> REGRESSION_OCC_OR_SPILL`; `bf16.ll` on two configs `MIXED ->
REGRESSION_OCC_OR_SPILL`). Confirmed crash fixes: **3 only** — `identical-subrange-spill-infloop.ll`
[gfx900] (`CRASH -> MIXED`, the null-`KillMI` segfault), `indirect-addressing-si-gfx9.ll` [gfx900],
`rewrite-vgpr-mfma-to-agpr.ll` [gfx942]. This supersedes the "8 remaining crashes (INFERRED)" note in
the section below.

**METHOD WARNINGS.** Two apparent EXTRA fixes are not fixes — `nullptr-long-address-spaces.ll` and
`write-register-vgpr-into-sgpr.ll` [bonaire], plus four `vgpr-spill-emergency-stack-slot-compute.ll`
configs, bucket `SKIP_EXPECTED_FAIL` in the new run and are therefore NOT COMPARED AT ALL. And keying a
bucket diff by `(test, config)` **COLLIDES** when one file has two configs sharing an mcpu name —
`amdgcn.bitcast.1024bit.ll` has two `gfx1100` RUN lines differing only by `-mattr` real-true16 — which
silently undercounts. Compare per-key bucket LISTS, never a single value per key. (This is the same
multiset trap recorded for the 0828 run, now confirmed on a second axis.)

**HARNESS: `SSA_EXTRA_FLAGS` is EMPTY.** The six `-amdgpu-ssa-*` extra flags were removed from the
allocator and their behavior is unconditional, so passing them makes `llc` fail with `Unknown command
line argument`. The harness injects ONLY `-amdgpu-ssa-regalloc` and `-verify-machineinstrs`.

### OPEN REGRESSION — `amdgcn.bitcast.1024bit.ll`, NOT at baseline

| state | gfx900 | tonga | gfx1100 x2 | tahiti |
| --- | --- | --- | --- | --- |
| baseline `archive-rescuebound-0828` | REGRESSION_OCC_OR_SPILL | REGRESSION_OCC_OR_SPILL | REGRESSION_OCC_OR_SPILL | CRASH (joint domination) |
| change A alone | CRASH | CRASH | CRASH | CRASH |
| A + B | ok | ok | **CRASH** | CRASH (signature MOVED) |

Both `gfx1100` configs abort with `SSARA recursive-recovery [worklist-drained]: cannot place %2555 or
%2556 (SGPR file). FEASIBLE YET UNRECOVERED (allocator bug): peak 105 live dwords at 4480r <= 105
registers, so a placement exists but recovery did not find it` — **two configs remain REGRESSED vs
baseline.** `tahiti` still crashes with a MOVED signature, from joint domination to `GENUINE
POINT-OVER-PRESSURE: 98 dwords live at 1510`: not a new regression (it crashed before) but not fixed.
Per `regression-baseline-is-truth` this work is **NOT at baseline and stays OPEN.**

**NEXT STEP — ATTRIBUTION, proposed but NOT approved and NOT run.** Temporarily revert the four
change-A files (their diff contains ONLY change A, verified), rebuild, re-run the `gfx1100` config, and
establish whether change A owns the recovery abort.

**READ FIRST — prior art.** This `bitcast.1024bit` failure was already triaged and queued in an earlier
session (NOTES near lines 3551 / 3637 / 3687), which attributes the `wwm-regalloc` + `Use not jointly
dominated by defs` abort to **the WWM Greedy allocator**, not to SSA reconstruction. That matches change
B clearing `gfx900` and `tonga`: the phantom use inside a self-copy is what failed the
every-path-definition check. So the joint-domination half is most likely a PRE-EXISTING WWM sensitivity
the identity copies were feeding. The surviving `gfx1100` abort has a DIFFERENT signature (SSARA
recursive recovery reporting a feasible placement it did not find) — treat it as a separate question.

### Reusable facts

**The abandoned spiller pass is PROVABLY out of the pipeline.**
`createAMDGPUSSARegisterSpillerPass` is defined at `AMDGPUSSARegisterSpiller.cpp:1416` and declared at
`AMDGPU.h:103` but has NO CALL SITE anywhere in `llvm`. The live pipeline at
`AMDGPUTargetMachine.cpp:1720-1736` is `RebuildSSA`, `PHISimplifier`, `SSARegisterAllocator`,
`VerifyPhysRegLiveness`. So `narrowSpilledRemnants` and its only callee `narrowRemnantToNewReg`
(`SSASpillEmitter`) are reachable ONLY via `-run-pass=amdgpu-ssa-register-spiller` and cannot affect
shipped output. By contrast `splitLiveRangeAt` IS live — `AMDGPUSSARegisterAllocator.cpp:2569` and
`:2815`. (This corrects the "RebuildSSA -> SSA Spiller -> SSA RA" description in *Pipeline Integration*
below, which has been updated.)

**Anatomy of the 19 baseline lit failures** in SSARA + SSASpiller + MachineLaneSSAUpdater — useful for
triage even though these suites are NOT a gate: 10 exercise the abandoned
`amdgpu-ssa-register-spiller` pass (7 via `-run-pass`, 3 via `-stop-after`; includes the 1 legitimate
XFAIL) and DISAPPEAR when that pass is deleted; 4 are the known unregistered
`test-machine-lane-ssa-updater` harness pass; 5 are genuine live-allocator `.mir` failures PRE-DATING
this session (`destruct-chain`, `destruct-sgpr64-swap`, `destruct-sgpr96-swap`, `destruct-wide-swap`,
`lowerphi-critical-edge-split`).

**Baseline-comparison technique.** `lit` resolves tools from the BUILD DIRECTORY, so comparing a frozen
binary against a fresh build requires replaying each test's RUN lines directly with the tool paths
substituted. Throwaway runner at `/tmp/runtest.py` (joins backslash-continued RUN lines, substitutes
`%s` and `%t`, rewrites the `llc` and `FileCheck` tokens, runs under `bash` with `pipefail`). VALIDATE
any such runner by confirming it reports PASS for tests that pass under `lit` — cf. the 2026-08-28/29
process lesson, where an unvalidated replay script produced a fake regression panic.

## 2026-08-28/29 — SSARA lit suites RETIRED as a gate; lane-accurate interference probe; 16-bit swap fallback

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, on top of `400183d0ab0d`.
UNCOMMITTED: +149/−22 across `AMDGPUSSARegisterAllocator.{h,cpp}`.

### THE SSARA + SSASpiller LIT SUITES ARE NOT A GATE. IGNORE THEM ENTIRELY.

User ruling (2026-08-29): **forget about the SSA RA lit tests completely.** They were authored for the
now-ABANDONED design — NUA + EarlySpiller + the old RA — so their CHECK lines encode the expectations
of machinery that no longer exists. A failure in
`llvm/test/CodeGen/AMDGPU/SSARA` or `.../SSASpiller` carries NO information about the current
allocator. Do not baseline against them, do not quote their pass counts as evidence, do not bisect
their diffs. This SUPERSEDES every earlier entry that treated them as a signal, including
"lit: 120 passed / 1 XFAIL / 17 failed" above, the older "86 pass + 1 legit XFAIL" figure, and the
2026-08-25 proposal to gate a default-flag flip on "the 74 SSARA-invoking lit files".

The corpus harness `ssa-spiller-docs/SSARA/tools/harness_rescue.py` is the ONLY regression gate,
compared by per-test bucket TRANSITION against a named baseline.

Knock-on effect: the empirical DEAD-ness argument for the `virgin-order` flag rested on
`forensic-colorfail-scope.mir` and `forensic-failure-shape.mir` still passing FileCheck with the flag
removed. Those are SSARA lit tests, so that evidence is void — the flag's fate must be argued from the
corpus instead.

### 16-bit swap fix — APPLIED and VERIFIED (`emitSwap`, `RegWidth == 16`)

`V_SWAP_B16` is VOP1-encoded, so both operands must lie in `VGPR_16_Lo128` (lo16/hi16 of v0-v127);
`emitSwap` emitted it unconditionally under `hasTrue16BitInsts()`. Latent until the lane-accurate
interference probe first placed a 16-bit permutation cycle above v127. Fix: require
`VGPR_16_Lo128RegClass.contains()` on BOTH operands, else emit a `V_XOR_B16_t16_e64` triplet (VOP3,
reaches all of `VGPR_16`). That opcode carries source modifiers and op_sel, so its operand list is
`dst, src0_mods, src0, src1_mods, src1, op_sel` and it cannot reuse the existing `EmitXorTriplet`.

Verified on `amdgcn.bitcast.1024bit.ll [gfx1100 -mattr=+real-true16]`: exit 0, was
`Illegal instruction detected: Operand has incorrect register class`. Fallback fired 85 times (255
`v_xor_b16`, every triplet touching a register >= v128); no surviving `v_swap_b16` has an operand
outside v0-v127. The `tahiti` crash on that file is pre-existing, byte-identical signature in baseline.

### Corpus accounting settled: 3 real fixes; the 2 phantoms are upstream `XFAIL: *`

Re-confirmed against the fresh binary: `identical-subrange-spill-infloop [gfx900]`,
`spill-agpr [gfx908]`, `spill-agpr [gfx90a]` all exit 0. The two apparent fixes are
reclassifications, proven twice over: `nullptr-long-address-spaces.ll` and
`write-register-vgpr-into-sgpr.ll` each carry an unconditional `; XFAIL: *` plus
`; REQUIRES: asserts` on lines 1-2, pass NO RA flag in their RUN lines, and fail identically with
`-amdgpu-ssa-regalloc` removed (`Size <= 8 && "Invalid size"` in `MCAsmStreamer::emitValueImpl`;
`illegal copy from vector register to SGPR`). The newer harness buckets them `SKIP_EXPECTED_FAIL`; the
archived 0828 baseline predates that detection. TRAP when diffing against any older archive.

### GUARDING SCHEME FOR THE REGISTER TREE — SETTLED

Recorded in [[Lane_Accurate_Interference]] §7/§10. Reference oracle = `recomputeOccupancy(V)`, which is
the per-unit probe ALREADY in `pickFreePhysReg`, lifted into a named function; contract is DERIVES
EVERYTHING, CACHES NOTHING, so it is correct by construction and has no staleness surface. Compare the
BITVECTOR OF UNAVAILABLE UNITS over V's range (the legality predicate), never the chosen register
(choice = AGPR preference + phi-affinity hints, orthogonal). Directional severity: tree-free while
reference-occupied is a MISCOMPILE and must be zero; tree-occupied while reference-free is lost capacity
only, a harness-bucketed warning. The reference SURVIVES the flip under `EXPENSIVE_CHECKS`. Tree
augmentation (per-unit `(Start,End)` arrays, arbitrary-start and non-power-of-two span queries) comes
BEFORE guarding.

`LiveIntervalUnion` REJECTED: throwaway complexity, staleness is an unenforced convention with no
assert and no `MachineVerifier` coverage, snapshots hold `const LiveInterval *` that
`removeInterval` + `createAndComputeVirtRegInterval` can dangle, and `LiveRegMatrix` is built around
eviction, which this allocator never does.

"Zero diff vs existing" is the WRONG criterion: the current shadow is FED BY `OccupiedRegUnits`
(`shadowResetToOccupied` re-derives it), so it is a photocopy that catches only copying bugs; its
comparator asks "did the allocator pick the LOWEST free leaf" while the real order is AGPR-preference
then affinity hints then first-fit, so it can never read zero; it is gated on `Reporter->active()` and
scoped to VGPR_32 width-1 with wide tuples mirrored as independent width-1 leaves; and the incumbent
whole-tuple model IS the defect, so faithfully reproducing it reproduces over-claiming.

Structural blocker: `SSARegisterTree` models ALIGNED POWER-OF-TWO blocks with POINT queries.
`FeatureRequiresAlignedVGPRs` has only 3 use sites in `AMDGPU.td`, so most targets allow a `VReg_64` at
an odd VGPR, and `VReg_96` is width 3. Keep candidate enumeration in `RegClassInfo::getOrder(RC)` and
use the tree purely as the `isFree` oracle.

### Design SETTLED (2026-08-29): guarding scheme + candidate order

**Guard.** Reference = `recomputeOccupancy(V)`, i.e. the per-unit probe ALREADY in `pickFreePhysReg`,
lifted into a named function. Contract: DERIVES EVERYTHING, CACHES NOTHING — correct by construction, no
staleness surface, too slow to ship, definitionally the right answer. Compare the BITVECTOR OF
UNAVAILABLE UNITS over V's range (the legality predicate), NOT the chosen register (choice = AGPR
preference + phi-affinity hints, orthogonal). Directional severity: tree-free/reference-occupied =
MISCOMPILE, hard error, must be zero; tree-occupied/reference-free = lost capacity, harness-bucketed
warning. The reference SURVIVES the flip under `EXPENSIVE_CHECKS`, because shadowing only observes states
the incumbent's decision sequence reaches. `LiveIntervalUnion` REJECTED (throwaway complexity; staleness
discipline is an unenforced convention with no assert and no `MachineVerifier` coverage; snapshots hold
`const LiveInterval *` so interval recompute can dangle them; `LiveRegMatrix` is shaped around eviction,
which this allocator never does). "Zero diff vs the existing code" is the WRONG criterion: the current
shadow is FED BY `OccupiedRegUnits` so it is a photocopy that only catches copying bugs, its comparator
tests "did the allocator pick the LOWEST free leaf" which affinity hints falsify by design, it is gated
on `Reporter->active()` so normal corpus runs never exercise it, and above all the incumbent whole-tuple
model IS the defect — a diff against it is WANTED.

**Candidate order.** Enumerate from `RegClassInfo::getOrder(RC)`; the tree answers ONLY
`isSpanFree(first, w, [S,E))`. Unaligned starts and non-power-of-two widths are handled by the CANONICAL
SEGMENT-TREE RANGE DECOMPOSITION (at most two maximal aligned nodes per level, ANDed): the width-3 run
`[1,4)` is `isFree(leaf 1) AND isFree(node 2..3)`. No phase arrays, no sparse table, no extra storage. So
`pickFreeAligned` never needs generalising. A LEVEL SCAN cannot serve as `getNextFree` — not for speed
(the heap layout does make a level contiguous, and the `MaxFreeAligned` descent is already $O(\log N)$ vs
$O(N/2^k)$) but for COMPLETENESS: with leaf 0 occupied, 1-2 free, 3 occupied, a level-1 scan reports no
width-2 block though `v[1:2]` is free and legal; level $k$ holds only $2^k$-aligned blocks and odd widths
have no level. Failure mode is pessimism → needless spills/colorfails. It does earn a place as a cheap
ADMISSION FILTER (`FreeLeaves >= 3` before verifying 3 leaves for a stride-4 width-3 SGPR). TRAPS:
`isSpanFree` must read free-extent aggregates only, never `NodeAllocated`; and THE LEAF AXIS MUST BE
HARDWARE REGISTER INDEX, not `getOrder` ordinal, since allocation order is not HW order on targets that
reserve registers.

### NEXT SESSION STARTS HERE (user decision, 2026-08-29 01:15) — `reduceRegionPressure` hull model

Function boundaries matter; an agent MISATTRIBUTED them mid-session, crediting the good machinery to the
wrong function. Actual layout: `peakSlotForValueInRegion` :1680, `relieveTightRegion` :1711,
`preSpillToLimitWidthAware` :1813, `reduceRegionPressure` :1896.

- `preSpillToLimitWidthAware` (PRE-color) is CORRECT and is the template: regions from
  `findTightRegions` (:1865, :1880), hole-accurate admission `LIS->getInterval(V).liveAt(R.PeakSlot)`
  (:1733), relief via `relieveTightRegion` (:1885), spill kill-at-def + reload-at-use (:1804-1805).
- `reduceRegionPressure` (POST-color recovery, LIVE, called :5382 in the round loop) is UNTOUCHED and
  still has the private `Iv{S,E,W,VReg,Colored}` with the HULL at :1932
  (`{LI.beginIndex(), LI.endIndex()}`, so liveness holes cease to exist), its own event-list sweep
  :1947-1983 on ONE GLOBAL SLOT AXIS with no CFG awareness (sums mutually exclusive divergent paths; a
  "region" can span blocks), and its own private `Region` struct :1954. Call-site comment :5374 admits
  it: "Kept as-is only to unblock corpus measurement of the AGPR/dead-def work."
- Mostly DELETION + REWIRING, not new machinery. `peakSlotForValueInRegion` has ZERO call sites (its job
  is done by the inline `liveAt(R.PeakSlot)`) — wire it in or delete it. Relief is CREDITED not measured
  (`Excess -= C.W`, :1795/:1807); defensible under kill-at-def plus the reload-placement filter (:2047),
  but an assumption.

**RISK FLAG (unverified, measure before touching the accounting).** Whole-width accounting is deliberate
and :1942-1946 states its premise: "the colorer reserves whole aligned tuples and does NOT reclaim dead
high-lanes ... Lane-accurate pressure here under-spilled and broke cf512." Today's lane-accurate
interference change makes the colorer RECLAIM dead lanes — we invalidated exactly that premise. So
whole-width pressure here may now OVER-estimate against the new colorer and OVER-spill, the opposite of
the original cf512 failure. Re-check `cf512` under the new colorer FIRST; it is the canary both ways.

### Prerequisites either way, and the remaining crash set

1. `getCachedRegUnit` -> `getRegUnit` at :727 (correctness; gates the guard, since the reference oracle
   must be right before it can judge the tree).
2. `scanOverlappersForVI` :636-661 still ORs in EVERY unit of a colored tuple regardless of live lanes
   (:658-659) — same over-claiming defect in the other consumer (gap pick + splitter).
3. No corpus run since the 16-bit swap fix, so "8 remaining crashes" is INFERRED, not measured.

Remaining classes (from `/tmp/corpus-laneexact2/report.md` minus the fixed gfx1100 bitcast): 2x
`UNREACHABLE` in the allocator (`indirect-addressing-si-gfx9` [gfx900], `schedule-xdl-resource` [gfx908]);
2x incorrect register class (`rewrite-vgpr-mfma-to-agpr` [gfx942],
`unspill-vgpr-after-rewrite-vgpr-mfma` [gfx90a], probably ONE root cause); `non-undef virtual register not
colored` (`debug-value`); `Use not jointly dominated by defs` (`amdgcn.bitcast.1024bit` [tahiti],
pre-existing); `cannot find enough VGPRs for wwm-regalloc` (`scc-clobbered-sgpr-to-vmem-spill` [gfx900]);
self-diagnosed GENUINE SGPR point-over-pressure (`spill-scavenge-offset` [verde]). NONE is an
occupancy-pessimism colorfail — the interference work already extracted its crash value, which is why the
RegisterTree is now REFACTORING, not correctness.

### Still open

The physreg leg of the interference test uses `getCachedRegUnit`, which materializes ranges only for
ABI live-ins, so mid-function physregs (`$vcc`, `$exec`) are not consulted — silent interference
misses, wrong assignment rather than a crash. Fix is `getRegUnit`, not yet applied. The docs repo is
messy and its design documents are NOT to be reworked until the design is finally settled.

### Process lesson

A throwaway python replay script substituted only `/tmp/llc.laneexact` in harness command lines, so the
five rows carrying `/tmp/llc.rescuebound-0827` silently re-ran the OLD baseline binary and produced a
fake "the fixes regressed" panic. For a handful of cases, run the commands MANUALLY.

## 2026-08-27/28 — AGPR-home-rescue bound APPLIED, revert-proven on the reproducer; lit clean; corpus gate at 300s

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`, on top of `400183d0ab0d`.
UNCOMMITTED (+20/−1 across `AMDGPUSSARegisterAllocator.{h,cpp}`), backup `/tmp/rescue-bound.patch`.

**BOTH DIRECTIONS PROVEN on the real reproducer**, same flags, binaries differing only by the
patch (the pre-fix binary was rebuilt from a `git stash` of the two files, then restored and
re-verified byte-identical against the backup patch):

| binary | exit | elapsed | result |
| --- | --- | --- | --- |
| pre-fix | 124 | 120s, killed | still churning, no output |
| with fix | 134 | **3s** | `[worklist-drained] cannot place %213 (VGPR file). GENUINE POINT-OVER-PRESSURE: 65 dwords live at 140r but only 64 registers` |

The abort names an ORIGINAL value (`%213`), not a rescue copy, and comes from the terminal sweep
in `@test_rewrite_mfma_direct_copy_from_agpr_class`. The overshoot is ONE register (65 vs 64) —
a margin a working pre-spiller should close, so this is an acceptance case for the pressure-model
redesign, not a coloring bug.

**PROCESS LESSON — reproduce with the test's OWN RUN line, never a hand-built command.** A first
attempt dropped `-amdgpu-mfma-vgpr-form` from `; RUN: llc -mcpu=gfx942 -amdgpu-mfma-vgpr-form`,
and the run exited 0 in 4.5s, which looks exactly like "the bug is gone". That flag is what drives
values into the AGPR path at all. Read the RUN line, or take the command from the harness.

**Lit: 120 passed / 1 XFAIL / 17 failed** over SSARA + SSASpiller + MachineLaneSSAUpdater +
NextUseAnalysis (138 tests) — the same 17 pre-existing failures. Note the pass count is 120 rather
than the previously recorded 103 ONLY because `NextUseAnalysis` (17 passing) was included in the
set; nothing changed.

**Corpus gate PASSED — 0 regressions, 0 fixes, exactly the 2 predicted unmaskings.** 8250 records
over 3080 files in 2819s; pinned `/tmp/llc.rescuebound-0827` (sha `4eb769dd5fc1`, head
`400183d0ab0d+dirty`), `--configs all --jobs 32 --timeout 300 --ssa-extra ''`, corpus path from the
`ssara` tree. Archived (with the patch) to `scripts/corpus/archive-rescuebound-0828` (19 MB).
`diff` vs `archive-400183d0-0826`: `FIXED 0`, `REGRESSED 0`, `TIMEOUT->CRASH 2` —
`rewrite-vgpr-mfma-to-agpr.ll [gfx942]` (our hang, now an honest report) and
`amdgcn.bitcast.1024bit.ll [tahiti]` (the crash that used to land at 153s). The budget-mismatch
warning fired as designed (120 vs 300).

**At a 300s budget the TIMEOUT bucket VANISHES ENTIRELY (19 -> 0)**, so CRASH 13 is now the whole
failure population and nothing is hidden — the predicted 13 confirmed by measurement. The 13, by
class: 2x `UNREACHABLE` in the allocator (`indirect-addressing-si-gfx9 [gfx900]`,
`schedule-xdl-resource [gfx908]`); 4x point-over-pressure (`spill-agpr [gfx908]` + `[gfx90a]` at
1108r, `spill-scavenge-offset [verde]` SGPR `no-reload-fits` at 1208r,
`rewrite-vgpr-mfma-to-agpr [gfx942]` at 140r); 1x `MO.isUndef() && "non-undef virtual register not
colored"` (`debug-value.ll`); 1x unclassified abort (`identical-subrange-spill-infloop [gfx900]`);
1x `Use not jointly dominated by defs` (`amdgcn.bitcast.1024bit [tahiti]`); 1x `Size <= N &&
"Invalid size"` (`nullptr-long-address-spaces`); 1x `cannot find enough VGPRs for wwm-regalloc`
(`scc-clobbered-sgpr-to-vmem-spill [gfx900]`); 1x `Operand has incorrect register class`
(`unspill-vgpr-after-rewrite-vgpr-mfma [gfx90a]`); 1x `illegal copy from vector register to SGPR`
(`write-register-vgpr-into-sgpr [bonaire]`). **Run the gate at `--timeout 300` from now on** —
2819s wall, same as the 120s run, because the artifacts finish instead of burning the full cutoff.

**Exactly 19 records changed bucket and NOTHING else in the 8250 moved** (verified as a multiset per
`(test,config)`): 2 -> `CRASH`; 6 -> `OK_EQUAL` (`shufflevector.v2{bf16,f16,i16}.v8*` x gfx90a,
gfx942); 6 -> `DIFF_COALESCING` (`v2{f32,i32,p3}` x 2); 4 -> `REGRESSION_OCC_OR_SPILL`; 1 ->
`PREEXISTING_FAIL` (`memintrinsic-unroll [gfx1030]` — Greedy needs 425s so it now exceeds the 300s
budget itself). `MIXED`, `OK_BETTER`, `NO_METRICS` and all nine skip buckets are identical to the
record.

**NEW WORK ITEM the raised budget exposed (not caused by the patch): 4 real occupancy/spill
regressions vs Greedy** that were previously invisible because those configs only ever timed out —
`amdgcn.bitcast.1024bit [gfx900]` and `[tonga]`, `shufflevector.v2i64.v8i64 [gfx90a]` and
`[gfx942]`.

**THE FAILURE COUNT IS 11, NOT 13 — and the harness was MISSING lit `XFAIL`** (2026-08-28). Two
CRASH records fail IDENTICALLY under Greedy because upstream marks them `; XFAIL: *`:
`write-register-vgpr-into-sgpr.ll [bonaire]` (`illegal copy from vector register to SGPR`, with the
in-test comment saying there is little that can be done about it) and
`nullptr-long-address-spaces.ll [?]` (`MCAsmStreamer.cpp:1338 Assertion Size <= 8`, an ASM-PRINTER
bug, no register allocation involved). Root cause of the misclassification: `SKIP_EXPECTED_FAIL`
fired ONLY when a RUN line started with `not llc`; the harness never read lit's `XFAIL:` directive,
and an XFAIL file's RUN line is a plain `llc`. Compounded by the harness's own design note — "on the
CRASH path Greedy does NOT normally run" — so a CRASH record is never checked against Greedy.
FIXED: new `has_xfail()` + `XFAIL_RE`, checked per file in `process()` before any RUN line is
considered; verified all 6 XFAIL files in the corpus now bucket `SKIP_EXPECTED_FAIL` and non-XFAIL
files are unaffected. Effect on the 0828 run: CRASH 13 -> **11**, and
`REGRESSION_OCC_OR_SPILL` 117 -> **112** (5 more records were the XFAIL
`vgpr-spill-emergency-stack-slot-compute.ll` across 5 configs). A diff against any older archive
will therefore show those records as `FIXED` — that is the reclassification, not a code change.

**ROOT-CAUSE CLASSIFICATION of the 11 real failures** (from the per-crash stderr in
`/tmp/corpus-rescuebound-0827/stderr`, not from signatures):

| family | n | evidence | status |
| --- | --- | --- | --- |
| A. Stage-3 `reduceRegionPressure` under-relieves | 4 | all abort in `reportPointOverPressure` (RA:2907); margins are **1-3 dwords**: `spill-agpr [gfx908]` 33 vs 31, `[gfx90a]` 34 vs 32 (both `@max_32regs_mfma32`), `spill-scavenge-offset [verde]` SGPR 42 vs 41 via `Floor` 3163, `rewrite-vgpr-mfma-to-agpr [gfx942]` 65 vs 64 | CONFIRMED |
| A'. same stage, null `KillMI` segfault | 1 | `identical-subrange-spill-infloop [gfx900] @main`: SIGSEGV at `SSASpillEmitter.cpp:597` `DT->dominates(KillMI,&UseMI)` <- `:144` <- the victim spill at RA~2097 that passes `LIS->getInterval(BestB).beginIndex()` as the kill index | CONFIRMED — matches the 2026-08-25 paper analysis exactly |
| B. tied-operand coloring invariant | 2 | `llvm_unreachable("Tied use must be colored already or undef")` RA:3737 <- 3740 <- 5256; `indirect-addressing-si-gfx9 [gfx900] @insertelement_with_call`, `schedule-xdl-resource [gfx908]` | HYPOTHESIS: the tied use's def was queued uncolorable/spilled, so no `ColorMap` entry existed when the tied def was processed |
| C. VGPR budget does not reserve for the downstream WWM allocator | 2 | both start with `error: cannot find enough VGPRs for wwm-regalloc`: `scc-clobbered-sgpr-to-vmem-spill [gfx900]` (clean error), `amdgcn.bitcast.1024bit [tahiti]` (then `Use not jointly dominated by defs` from `LiveIntervalCalc.cpp:192` inside **Greedy**) | first symptom CONFIRMED shared; the cascade is a HYPOTHESIS |
| D. post-rewrite MIR invalid | 1 | `unspill-vgpr-after-rewrite-vgpr-mfma [gfx90a]`: verifier `Operand has incorrect register class` + `Illegal physical register for instruction` (2 errors) | HYPOTHESIS: arch-VGPR vs AGPR class confusion on gfx90a's split file |
| E. value reaches rewrite uncolored | 1 | `debug-value.ll @wobble`: `assert(MO.isUndef() && "non-undef virtual register not colored")` RA:4615 | HYPOTHESIS: a path leaves a value uncolored WITHOUT queueing it to `UncolorableVRegs` (the queueing the rescue relies on) |

**5 of the 11 (families A + A') are the pending pressure-model redesign**, and the margins say these
are NOT structural infeasibility — three of the four are over capacity by 1-2 registers.

**TOOLING CAVEAT — 970 keys carry MORE THAN ONE record**, because several tests have multiple RUN
lines that map to the same config tag. Keying a dict on `(test,config)` silently drops one record
per duplicate: it made 19 timeout transitions look like 18 and made the `PREEXISTING_FAIL` entry
disappear entirely. Always diff results as a MULTISET. `cmd_diff` reached the right crash answer
here, but whether it collapses duplicates the same way is UNAUDITED.

**Host fact:** 10 orphaned `AllClangUnitTests` processes owned by `paakan`, reparented to init,
had been spinning at 99.8% CPU each since 2026-03-04 (176 days, ~10 of 128 cores). Killed by the
user via `sudo pkill -u paakan -f AllClangUnitTests`. Worth re-checking `ps -eo user,pcpu` before
trusting any timing-sensitive corpus measurement.

## 2026-08-26 — flag cleanup A/B/C committed (7 flags gone); corpus gate 0 transitions; TIMEOUT triage added; true failure count is 13; AGPR-rescue non-termination root-caused

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`. All commits created BY
THE USER — the 2026-08-25 process conflict is **RESOLVED**: AI commits are prohibited because
this workspace is potentially public. The agent prepares and stages only.

**Three cleanup commits landed** (on top of `f3869a20da99`):

| commit | removes | net |
| --- | --- | --- |
| `75b0ea42c988` | dead code: width-tier virgin order + everything it gated, naive pre-spiller (`preSpillToLimit`), slot-delta probe (`dumpSpanWidthDelta`) | −546 |
| `05dc22aa5401` | five default-ON flags, code made unconditional: `acl-coloring`, `pre-spill-wa`, `agpr-rescue`, `region-rp`, `phi-web-spill` | −103 |
| `400183d0ab0d` | `-amdgpu-ssa-agpr-first`, hardcoded ON at all eight sites + emitter plumbing | −7 |

Commit B also rewrote the width-aware pre-spiller's doc comment to stand ABSOLUTELY — it had
described itself by contrast with the naive twin A deleted, leaving five dangling references.

**The `agpr-first` in-tree comment was INVERTED at HEAD.** It claimed the arch-VGPR metric caused
"undefined physical register" crashes on `buffer-fat-pointer-*`. Measured on the A+B binary: the
three `buffer-fat-pointer-atomicrmw-{fadd,fmax,fmin}.ll` pass either way, and
`buffer-fat-pointers-memcpy.ll` **aborts with the flag OFF** on gfx90a AND gfx942
(`classified-infeasible: cannot place %163 (VGPR file). FEASIBLE YET UNRECOVERED (allocator
bug)`) while completing with it ON. So the SHIPPING DEFAULT was the failing path and hardcoding
ON is a fix. Every corpus run of record passed the flag ON — **read `run.json` to learn a run's
flags, never the harness's built-in list** (that list never contained `agpr-first`; it arrived via
`--ssa-extra`). Semantics for reference: `getArchVGPRNum()` = `VGPR+AVGPR`; `getVGPRNum(false)` =
`max(VGPR+AVGPR, AGPR)`; three of the eight sites were NOT subtarget-guarded, so the flag also
changed the reload-RP metric on gfx908-class targets.

**Corpus gate: 8250 records, ZERO bucket transitions.** `/tmp/corpus-abc-0826` → archived
`scripts/corpus/archive-400183d0-0826` (19 MB). `--ssa-extra '' --configs all --jobs 32 --timeout
120`, 3080 files, 2797s. CRASH 11 / TIMEOUT 19 with identical test SETS vs
`archive-f3869a2-0825`, nine crash-signature classes byte-identical, `(test,bucket)` multiset
equal in both directions. Lit unchanged: 103 passed / 1 XFAIL / 17 pre-existing failures.
`--ssa-extra ''` still passes `-amdgpu-ssa-regalloc` (it only controls flags appended after it),
independently confirmed by the bucket mix (146 `DIFF_COALESCING`, 111 `OK_BETTER`).

**The true failure count is 13, not 11 and not 30.** Measured both legs of all 19 TIMEOUT records
at a 600s budget:

| n | test / configs | SSARA vs Greedy | verdict |
| --- | --- | --- | --- |
| 14 | `shufflevector.v2*.v8*.ll` gfx90a+gfx942 | 126-133s vs 124-129s | artifact — Greedy also >120s |
| 1 | `memintrinsic-unroll.ll` | 135s vs **425s** | artifact — SSARA 3x FASTER |
| 2 | `amdgcn.bitcast.1024bit.ll` tonga/gfx900 | 146-176s vs 66-68s | `slow_ok`, ~2.5x slower |
| 1 | `amdgcn.bitcast.1024bit.ll` **tahiti** | aborts at 153s | **crash masked by the cutoff** |
| 1 | `rewrite-vgpr-mfma-to-agpr.ll` **gfx942** | >600s vs 17s | **genuine hang** |

Input size explains the family: median corpus file is 7 KB; these are 90 KB-12.6 MB (578
functions / 238k lines). The masked crash is `cannot find enough VGPRs for wwm-regalloc` then
`LLVM ERROR: Use not jointly dominated by defs` in **Greedy** on `@bitcast_v64bf16_to_v128i8_scalar`
— the joint-domination property of `5fde0ed1dd8d` failing DOWNSTREAM of SSARA. Queued.

**Harness (`SSARA/tools/harness_rescue.py`, UNCOMMITTED on branch `work`; working copy
`scripts/corpus/harness_rescue.py` re-synced).** User waived review.
- CRITICAL: `SSA_EXTRA_FLAGS` is now `[]` — it still listed three flags deleted by A/B, so any
  default invocation would fail all 3080 tests with "Unknown command line argument".
- TIMEOUT triage: on an SSARA timeout, run Greedy at the SAME budget; if Greedy finished, re-run
  SSARA at `--timeout-extend` × budget (default 3). Verdicts `both` / `slow_ok` / `late_crash`
  (captures signature + paste-runnable repro) / `hang`, in the record and a `## TIMEOUT triage`
  report section. **The bucket stays `TIMEOUT`** so per-test transition diffs against archived
  runs stay valid. `cmd_diff` now warns on a `--timeout` mismatch between runs and lists
  `late_crash` records as HIDDEN FAILURES. Default timeout left at 120 (help recommends 300).
- All four verdicts validated on real inputs, incl. `slow_ok` = `amdgcn.bitcast.1024bit.ll
  [gfx1100]` (Greedy 54-58s under a 60s budget, SSARA 92-99s of 180s).
- `/tmp/timeout-probe/probe.py` deliberately NOT kept — every capability moved into the harness;
  keeping it would duplicate logic that must not drift.

**AGPR-home-rescue non-termination — ROOT-CAUSED; fix APPLIED 2026-08-27 and verified in BOTH
directions (see the 2026-08-28 entry below).** `rewrite-vgpr-mfma-to-agpr.ll [gfx942]` makes real
but unbounded progress: `tryAGPRHomeRescue` mints one `%tmp:VGPR = COPY R` per VGPR-only use, and
a copy that fails to color is appended to `UncolorableVRegs` (~2830, under a comment claiming it
cannot happen). TWO loops then walk into those copies, because both re-evaluate their bound over
values queued while they run: the drain loop (`PassEnd = UncolorableVRegs.size()` at ~5374) and the
terminal sweep (`I < UncolorableVRegs.size()` at ~5379). And the rescue has FOUR call sites, not
one — 3135 `AGPRRelief`, 3148 `Floor`, 3173 `Infeasible` inside `recoverUncolorable`, plus 5383 —
which is exactly why the guard belongs in the CALLEE. WHICH loop spun was never determined (hit
counts were collected, not backtraces) and the fix does not depend on it. EVIDENCE: gdb breakpoint
on the push-back hit **9,706 times in 7 minutes, still climbing**; consecutive vregs
`%6909`…`%6915`, each `-> AGPR, 1 a->v copies`. Both `agpr-first` settings fail this test, so
Commit C added no failure. Fix (4 minimal edits): `SmallDenseSet<Register,8> RescueCopies` in the
`.h`, cleared PER FUNCTION only (a copy stays a copy across the full recolor that clears
`UncolorableVRegs` a second time); early `return false` when `RescueCopies.count(R)` (a rescue copy
exists precisely to occupy a VGPR at one instruction, so AGPR-homing it cannot satisfy that use);
`insert(Tmp)` at creation; replace the false comment (the `push_back` itself MUST stay — it is the
only thing that keeps an uncolored live value from reaching `rewriteStage`, where
`assert(MO.isUndef() && "non-undef virtual register not colored")` fires, or in a release build a
live value silently gets an arbitrary physreg). No defensive loop snapshot — with the guard the
vector grows at most once per rescue. UNVERIFIED: that nothing succeeding today depends on a
NESTED rescue; the corpus run settles it.

**Next session:** (1) apply the rescue bound on approval → repro must abort in seconds with
`GENUINE POINT-OVER-PRESSURE`, lit stays 103/1/17, corpus at `--timeout 300` vs
`archive-400183d0-0826` expecting ONLY mfma `TIMEOUT`→`CRASH` (reported as already-failing, not a
regression). (2) Multi-block pressure-model redesign steps (a)-(d) from 2026-08-25, canary
`cf512`; acceptance cases are concrete now — 5 of the 13 real failures are pressure not relieved
before coloring (2 VGPR `[worklist-drained]`, 1 SGPR `[no-reload-fits]`, mfma, +1). (3) Queued:
the `wwm-regalloc` joint-domination failure; 2x `UNREACHABLE executed at
AMDGPUSSARegisterAllocator.cpp`.

**Failure population at `400183d0ab0d` (13):** 2x allocator `UNREACHABLE`, 2x VGPR
`[worklist-drained]` point-over-pressure, 1x SGPR `[no-reload-fits]`, 1x `MO.isUndef() &&
"non-undef virtual register not colored"`, 1x `Size <= N && "Invalid size"`, 1x `wwm-regalloc`
VGPR exhaustion, 1x `Operand has incorrect register class`, 1x `illegal copy from vector register
to SGPR`, 1x unclassified `identical-subrange-spill-infloop` abort, 1x mfma hang, 1x masked tahiti
crash.

**Reusable technique — to run lit as if a flag were hardcoded, shim the BIN, not the PATH.** lit
resolves `llc` by absolute path, so PATH interposition does nothing; copy
`build/user-debug/bin/llc` aside and place a 3-line `exec` wrapper at that exact path, then
restore. This is how Commit C was measured against the 74 SSARA-invoking lit tests.

**`AGENTS.md` delta still PENDING manual apply** — the edit-guard blocks the
`/work/atimofee/sandbox/github/ssara` path prefix, which `ssara-wt-widthaware` shares, so the
documented memory-update exemption stays unreachable. Exact text in
`SSARA/08-Worklog/NOTES.md`, section 2026-08-26, last subsection.

## 2026-08-25 — joint-domination undef flagging + dead-def store skip committed (corpus CRASH 15 -> 11); Stage-3 multi-block pressure model redesigned on paper; flag audit

Worktree `ssara-wt-widthaware`, branch `weekend/prespill-widthaware`.

**Two commits landed** (both verified in `git log`, on top of `76ecaa1369d1`):
- `5fde0ed1dd8d` — **undef flagging must test JOINT DOMINATION, not liveness.** The
  flagging added in `76ecaa1369d1` used `SR.getVNInfoAt(useSlot)` and marked a read
  undef when no lane was live there. Live segments are half-open, so a KILLING use
  sits exactly at its own segment's END and `getVNInfoAt` returns null for a
  perfectly live lane: nearly every last use got flagged undef, `updateDeadFlags`
  then saw the only reader gone, the def went dead, and half of a split lane pair
  was never written -> verifier "Using an undefined physical register". Swapping to
  `getVNInfoBefore` is necessary but NOT sufficient — liveness AT the use cannot
  decide this at all, because a lane can be live along one edge and undefined along
  another. The property the next whole-value LiveIntervals computation demands is
  joint domination (a def of the read lanes on EVERY path to the use). Implemented
  per read lane in `MachineLaneSSAUpdater.cpp` (~lines 312-373): no reaching value
  => undef; a block-boundary value (live-range phi, NOT a PHI instruction) => undef
  unless every predecessor carries the lane out; otherwise => undef iff the
  reaching def does not dominate the use (one dominance query, valid because the
  updater maintains SSA). PHI-defined values are exempt (per-edge by construction).
- `f3869a20da99` — **do not store a dead def at its definition.**
  `SSASpillEmitter::spillAtDefinition()` (~line 486) emitted the save right after a
  DEAD def, leaving `dead %v = ...` followed by a read of `%v`, which the verifier
  rejects once colored. The function already guarded the twin IMPLICIT_DEF case for
  exactly this reason. Skipping is COMPLETE, not partial: with no readers
  `buildDomGroupsForSpill` emits no reload. Instance: `dead %202:sreg_64`, the
  unused sdst of a V_DIV_SCALE, stored into `%stack.12` as `$sgpr52_sgpr53`. A
  latent hole exposed only because region-rp's victim selection changed.

**Corpus gate: CRASH 15 -> 11, 4 REAL fixes, 0 regressions.** Run `/tmp/corpus-f3869a2`
(dies at reboot); metadata archived to
`/work/atimofee/sandbox/github/scripts/corpus/archive-f3869a2-0825` (20 MB:
`results.jsonl`, `run.json`, `report.md`, `failed.txt`). Binary `/tmp/llc.f3869a2-0825`
(`sha256` 9c401ea68f28…), `head=f3869a20da99`, all six SSA flags, `--configs all
--jobs 32 --timeout 120`, 3080 files -> **8250** (test x config) records, ~47 min.
Baseline `/tmp/corpus-newfixes-0825` (same 8250/3080). Fixed, all four formerly
"Using an undefined physical register": `flat_atomics_i64_system.ll [gfx900]`,
`insert_vector_elt.v2bf16.ll [tahiti]`, `si-sgpr-spill.ll [tahiti]`,
`si-sgpr-spill.ll [tonga]`.

**UNRESOLVED (not progress).** `unspill-vgpr-after-rewrite-vgpr-mfma.ll [gfx90a]`
changed SIGNATURE, "Using an undefined physical register" -> "Operand has incorrect
register class", and still fails. Per `regression-baseline-is-truth` a failure that
merely changes shape is an open regression; needs triage. The other 10 remaining
failures carry paste-ready `llc` command lines in `archive-f3869a2-0825/failed.txt`:
`indirect-addressing-si-gfx9 [gfx900]`, `write-register-vgpr-into-sgpr [bonaire]`,
`identical-subrange-spill-infloop [gfx900]`, `schedule-xdl-resource [gfx908]`,
`spill-agpr [gfx908]`, `spill-agpr [gfx90a]`, `spill-scavenge-offset [verde]`,
`nullptr-long-address-spaces`, `scc-clobbered-sgpr-to-vmem-spill [gfx900]`,
`debug-value`.

**Stage 3's private pressure model is invalid across blocks — redesign DRAFTED, NOT
implemented.** `reduceRegionPressure` (`AMDGPUSSARegisterAllocator.cpp` ~2324) carries
its own model: its `Iv` struct collapses each value to the hull
`[beginIndex, endIndex)` (line 2360) so liveness HOLES stop existing; it sorts events
on one global slot axis with no CFG awareness, so a "region" spans blocks (observed
`[304e,1616r)` over bb.0-bb.6) and sums pressure from mutually exclusive divergent
paths; it then fabricates a `TightRegion` from such a region
(`TR.MBB = LIS->getMBBFromIndex(R.S)`, line 2482), violating that struct's own
documented invariant `SlotIndex Start, End; // half-open, within MBB` (.h line 309),
and hands the malformed view to `costOfSpilling`; coverage is hull intersection,
which is how `%18` was picked as victim with `cover=8` for a region sitting inside
its liveness HOLE; relief is CREDITED (`R.Peak -= BestW`, line 2618) rather than
measured; and the kill index is `LIS->getInterval(BestB).beginIndex()` (line 2605),
contradicting the stage's own documented contract ("kill at R.Start") and able to be
a block-boundary slot — the null-`KillMI` segfault in
`identical-subrange-spill-infloop`.

**KEY DISCOVERY: the CFG-correct machinery already exists in-tree and Stage 3 simply
does not use it.** `findTightRegions` (line 1601) is per-MBB, seeds
`GCNUpwardRPTracker` at block end and recedes, and is PHI-aware (skips PHI slots
because PHI operands resolve at predecessor edges and would manufacture phantom
regions); it is already called by two other stages (2065, 2293/2308).
`peakSlotForValueInRegion` (line 2107) is the hole-accurate victim test — it asks
`VI.liveAt(SI)` per in-region slot and returns RP 0 when the value is live nowhere in
the region, and its own comment describes exactly the failure debugged here — and it
currently has **ZERO CALLERS** (only its .h declaration at 356).
`relieveTightRegion` (2139) is an excess-driven victim selector already keyed on a
well-formed `TightRegion` and may let Stage 3 drop its own selection loop
(compatibility of the eligibility rules is NOT yet verified). So today the two stages
disagree with each other; unifying them introduces no new model.

Four independently measurable steps: (a) admit a candidate only if
`peakSlotForValueInRegion(R,V).second != 0` — smallest change, eliminates the `%18`
class; (b) take regions from `findTightRegions` instead of the private sweep;
(c) `KillIdx = R.Start` — the segfault CANNOT recur, because `R.Start` is assigned
from `LIS->getInstructionIndex(MI).getRegSlot()` (line ~1627) and therefore always
maps to a real instruction, so NO defensive block-slot guard is needed; (d) measure
relief by RECOMPUTING the region peak instead of subtracting the victim width.
Tie-break on summed live-segment intersection with `[R.Start, R.End)`, not hull
overlap. Risk: accurate pressure is LOWER than hull pressure => fewer/smaller tight
regions and less spilling; **`cf512` is the standing canary** (an earlier
more-accurate model under-spilled and broke it). The whole-width vs lane-accurate
question is ORTHOGONAL — do not touch it in the same change. The user explicitly
REJECTED a temporary `KillIdx` guard: "I don't want a temporary fix which in its
order likely introduce a regression."

**Flag audit (analysis only, NOTHING applied).** `AMDGPUSSARegisterAllocator.cpp` has
exactly 13 `cl::opt` flags, all bool, all within the first 137 lines.
- Default-TRUE **and** passed redundantly by the corpus config, so those CLI flags
  are no-ops: `amdgpu-ssa-acl-coloring`, `amdgpu-ssa-pre-spill-wa`,
  `amdgpu-ssa-agpr-rescue`, `amdgpu-ssa-region-rp`, `amdgpu-ssa-phi-web-spill`.
  Stale comments reading "Default off"/"Default OFF" sit directly above
  `cl::init(true)` at lines 30-35, 108-110 and 117-120.
- `amdgpu-ssa-agpr-first` is default FALSE but the corpus ALWAYS passes it, so the
  shipping DEFAULT path is the one nothing covers.
- VERIFIED DEAD: `amdgpu-ssa-pre-spill` + `preSpillToLimit` (2034-2138; sole caller is
  the `else if` arm at 5785, unreachable unless `-amdgpu-ssa-pre-spill-wa=false`; no
  corpus, no lit) and `amdgpu-ssa-slot-delta` + `dumpSpanWidthDelta` (952-1049, one
  call site at 1058, 0 tests).
- `amdgpu-ssa-virgin-order` is DEAD, proven EMPIRICALLY not assumed: default off,
  never passed by the corpus, only users are `forensic-colorfail-scope.mir` and
  `forensic-failure-shape.mir`, and running both with the flag REMOVED still passes
  FileCheck (the JSON bytes differ — cause string `"virgin-order"` becomes
  `"first-fit-order"` — but every CHECK still matches). Confirms Hack-compliancy was
  abandoned. It gates ~260 lines: `buildVirginTierOrder` (723-777), `analyzeTierRank`
  (778-857), the pick path (1174-1201), `findNonInterferingGap` (886-951, sole caller
  is that block), tier tallies (4032/4041/4256/4363/4421/4506), .h members 71-92, and
  statistics `NumVirginPicks`/`NumGapPicks`/`NumTiersFeasible`/`NumTiersInfeasible`
  (160-176).
- `amdgpu-ssa-experiment-bail` MUST BE KEPT despite being default-false and test-only:
  it is load-bearing for those same two forensic tests. Without it `llc` aborts with
  `LLVM ERROR: SSARA recursive-recovery [classified-infeasible]: cannot place %102
  (SGPR file). GENUINE POINT-OVER-PRESSURE: 110 dwords live at 1760r` before the
  forensic JSON is flushed.
- KEEP per user decision: `amdgpu-ssa-shadow-tree` (+ `SSARegisterTree.cpp/.h`, 401
  lines) because `SSARegisterTree` is intended to REPLACE `ColorMap` and more, and the
  shadow keeps it exercised and up to date; `amdgpu-ssa-verify-value-flow` (+`-fatal`)
  because it checks the resulting assembly.
- Removal traps: `scanOverlappersForVI` LOOKS virgin-order-adjacent but has three live
  callers (2781, 2844, 3116) and must stay; `NumTierSpills` is also incremented on the
  live path at 5904 and must stay.

**Coverage fact — SSARA is entirely opt-in, so `check-llvm` measures NOTHING here.**
`createAMDGPUSSARegisterAllocatorPass()` is added only inside the `-amdgpu-ssa-regalloc`
branch, and that flag is `cl::init(false)` at `AMDGPUTargetMachine.cpp:241`. A default
`check-llvm` run therefore exercises ZERO SSARA code, and "run check-llvm to measure an
SSARA flag" measures nothing. **The corpus harness IS the AMDGPU lit suite** for SSARA
purposes (same ~3080 inputs, every RUN line, each test's own triple/mcpu, plus the SSA
flags). The only lit tests that invoke SSARA are the 71 files in
`llvm/test/CodeGen/AMDGPU/SSARA/` plus 3 in `MachineLaneSSAUpdater/` (74 total; 37 of
those RUN lines pass `-amdgpu-ssa-regalloc`, the other 41 use
`-run-pass=amdgpu-ssa-register-allocator`), and they are the ONLY place SSARA OUTPUT is
checked by FileCheck — the corpus classifies crashes, not output correctness. So the
correct gate for removing `amdgpu-ssa-agpr-first` (which would hardcode ON a path those
74 currently run OFF) is to run those 74 with the flag injected, e.g. via a PATH shim —
NOT a full `check-llvm`. Also confirmed: nothing outside AMDGPU references
`MachineLaneSSAUpdater` (only its own .cpp/.h and the CodeGen CMakeLists entry), so
despite living in `llvm/lib/CodeGen` it cannot affect other targets.

**Caution on `agpr-first`.** The in-tree comment (~1555-1572) records that the two-file
arch-VGPR metric this flag enables previously caused "undefined physical register"
crashes on AGPR-using code, that the default path deliberately keeps the unified count
"exactly as before", and that making the two-file model uniformly correct is a pending
follow-up. Hardcoding it ON adopts a metric the code itself documents as not yet
uniformly correct, and removes the escape hatch.

**Planned next session.** Commit A: remove verified-dead code (naive pre-spiller,
virgin-order + everything it gates, slot-delta; drop `-amdgpu-ssa-virgin-order` from the
two forensic RUN lines while KEEPING `-amdgpu-ssa-experiment-bail`). Commit B: remove
the five default-ON flags together with their `if`s, preserving behavior, and fix the
three stale "Default off" comments. Commit C: `amdgpu-ssa-agpr-first`, separately, gated
on the 74-test SSARA lit run. Then the multi-block redesign in steps (a)-(d). Also
triage the `unspill-vgpr-after-rewrite-vgpr-mfma [gfx90a]` signature change.

**PROCESS CONFLICT — needs an explicit user ruling, do not assume.** This session the
user instructed "commit fixes proved useful and run corpuse in screen", and the agent
created `5fde0ed1dd8d` and `f3869a20da99` WITH `Co-Authored-By: Claude
<noreply@anthropic.com>` trailers — matching the de-facto branch convention (9 of the
last 12 commits on `weekend/prespill-widthaware` carry that trailer). This contradicts
the standing preference recorded below and in `AGENTS.md` ("User commits manually — AI
must never run `git commit` or add AI trailers"). Unresolved: which wins, and whether
the trailers on those two commits should be stripped. See User Preferences.

**INFRA FACT + open item: `ssara/AGENTS.md` is NOT writable from a guarded session, despite
its own documented exemption.** `AGENTS.md` records that it is approval-EXEMPT for memory/fact
updates so a background `agents-memory-updater` never deadlocks — but the edit-guard
HARD-BLOCKS any write into the live `ssara` tree, that path included ("this sandbox is
reports-only for that tree"). The exemption is therefore unreachable in practice: AGENTS.md
fact updates must be applied by the USER, or the guard needs a carve-out for that single file.
The full intended AGENTS.md delta from this session — one in-place correction (the stale
"CURRENT-STATE crash figure = 59/3072") plus six additive fact bullets — is written out
ready-to-paste at the end of the 2026-08-25 section of `SSARA/08-Worklog/NOTES.md`.

## 2026-08-21 — reserved-register hint gate + lane-group split committed; Greedy tail measured empty; crash cluster re-triaged

Full detail: `SSARA/08-Worklog/HANDOFF-2026-08-21.md` (evening session, §6-§13).

**Working tree agreement.** All work and testing happens in `ssara-wt-widthaware`
(branch `weekend/prespill-widthaware`); fixes are carried to other worktrees as a
BULK PROMOTION once the corpus is all green. **Do not test in `ssara-claude`** —
its build is from 2026-08-07 and rejects `-amdgpu-ssa-pre-spill-wa` and
`-amdgpu-ssa-agpr-first`, so it cannot reproduce current behavior.

**Two commits pushed** (on top of ACL pre-pass `bd3465961b1e`):
- `7f68676d9535` — the physreg-copy affinity hint accepted a candidate on
  register-class containment alone. `SReg_64` contains `EXEC`, so a value defined
  by a copy of the exec mask got colored to the exec mask and its spill hit the
  "exec should never spill" assertion. Every other pick scans `availableOrder()`,
  which excludes reserved registers; the hint path was the only bypass. Gated on
  `isReserved`; the two hint composers factored into one helper. Corpus 8250
  records: CRASH 22 -> 19, zero healthy-to-broken.
- `48ed02ef1617` — `buildRSForSuperUse` asserted every updated-lane group has a
  single subregister index; a partial-def chain can leave one with none (sub1..15
  of a 512-bit register when sub0 has its own def). Split into covering
  subregisters in that case. **Do not rebase lane masks onto the new register's
  coverage** — that attempt regressed SDWA on `si-sgpr-spill` and produced an
  invalid global physreg on `tuple-allocation-failure`.

**Greedy is measurably not needed.** With `-amdgpu-prealloc-sgpr-spill-vgprs`,
7363 of the 7364 compiling corpus records have ZERO vregs surviving past
`si-pre-allocate-wwm-regs`. Sole exception `sgpr-regalloc-flags.ll`
(`control_flow`, `%0`), which does not force another allocator.

**Reusable techniques / pitfalls from this session**
- **Cluster crashes by ABORTING PASS, never by message text.** Doing so split the
  four "Use not jointly dominated by defs" records into two unrelated bugs and
  revealed one failure living in the Greedy tail rather than in SSARA.
- **Re-verify "pre-existing" per record** by rerunning the exact recorded command
  with the SSA flags stripped, rather than trusting an earlier classification.
- **`-amdgpu-ssa-forensic-trace=FILE` beats `-debug-only`** for allocator
  triage: 1.75 MB in 7 s, and it emits only functions that had a color failure
  (`-amdgpu-ssa-forensic-colorfail-only` defaults on). Note that values colored
  via `colorOneInPlace` emit NO forensic events, so an absent value in the trace
  does not mean it was not processed — cross-check the debug log.
- **When counting vregs in a `-print-after` dump, scope to that dump's section.**
  Corpus tests that carry their own `-debug` / `-debug-only` / `-print-after`
  flags dump pre-RA MIR to the same stream; ignoring the section boundaries
  produced 7 false positives out of 7 hits.
- **`pkill -f PATTERN` kills the shell running the command** when the pattern
  appears in its own argv. Kill by PID instead.

**Upstream defect found (not ours to fix in the allocator).** The register
coalescer flattens a REG_SEQUENCE into partial defs with `undef` correctly on the
first in program order; the machine scheduler then swaps the two copies and
leaves the flag on the now-second one. A subregister def without `undef` reads the
other lanes, so a from-scratch live-interval recomputation sees a use with no
reaching def and aborts in `LiveRangeCalc::findReachingDefs`. The machine verifier
accepts the MIR and Greedy never recomputes that interval, which is why only
SSARA's `performSSARepair` trips on it.

**Negative result worth remembering.** In the SSARA worklist fixpoint, making a
memory spill count as progress (`Progress |= recoverUncolorable(Failed)`) is NOT
a sufficient fix for the tonga colorer failure: it turns a 7-second abort into an
unbounded spill cascade (4257 spills, vregs `%1248 -> %14001`), because spilling a
long-range width-1 SGPR yields a redef with the same long range under a new name.
The underlying defect is that the memory-spill floor does not shorten the live
range of a value live-out across many blocks, while `floorViable` accepts it
anyway. Reverted; see HANDOFF §10.

## 2026-07-14 — ssara synced to ff16 baseline (affinity + fold), PHI pass renamed, 3 commits pushed

**Spiller allocatable-budget cap COMMITTED fc16 (`fc1614731504`).** `AMDGPUSSARegisterSpiller`:
`VGPRLimit/SGPRLimit = min(getMaxNum*, TRI->getAllocatableSet(&VGPR_32/&SGPR_32RegClass).count())`
BEFORE the 10% margin. `getMaxNumVGPRs` = occupancy target over the whole vector budget (gfx90a =
VGPR+AGPR = 128) but the allocator colors into VGPR_32 only (64); the spiller over-budgeted ~2x,
under-spilled, `color()` aborted "Failed to find free physreg". Corpus CRASH -10, 0 new. (Reconciles
the long-open "spiller vs RA budget differ" item.)

**PHI pass renamed `AMDGPUPHICoalescer` → `AMDGPUSimplifyUndefPHI`** (file/class/symbols;
DEBUG_TYPE `amdgpu-simplify-undef-phi`; flags `-amdgpu-simplify-undef-phi[-flag|-fold]`; stats
`NumUndefFlagged`, `NumPHIsFolded`). Two rewrites: (a) flag fully-undef PHI operands undef; (b) fold a
single-real undef-PHI onto its operand when its def dominates the PHI (whole-reg only; MDT test;
declines loop-carried back-edge). **Kept STANDALONE (load-bearing):** it mutates undef flags →
invalidates LiveIntervals + AMDGPUNextUseAnalysis, which the pass manager recomputes for the spiller
(pass only preserves CFG/MDT). Folding it into the spiller would strand a STALE NUA (spiller acquires
`AMDGPUNextUseAnalysisWrapper` up front) — that is the concrete reason a pre-spiller pass boundary is
required, not overkill.

**ssara vs ssara-claude (both fc16) — the baseline gap.** `corpus-ff16` (47 crashes, /tmp/corpus-ff16)
was run on **ssara-claude**, which has three behavioral features ssara lacked: (1) spiller
reload-lane-narrowing — **POST-baseline, OUT OF SCOPE**; (2) φ-affinity coloring (promote patch 02);
(3) PHI fold (b). ssara alone = 50 crashes; +3 vs ff16 = `urem.ll`, `wave32.ll` ("Segment is not
entirely in range!"), `amdgcn.bitcast.576bit.ll` ("Failed to find free physreg"). Proven NOT the
rename via A/B: `urem.ll` asserts identically with the PHI pass on AND off (pass-independent). Fix =
port affinity(2) + restore fold(3).

**Result:** after the sync, corpus `uptodate` (jobs=32/timeout=180) = **CRASH 47, IDENTICAL set to
ff16, all buckets match** (the one REGRESSION delta `a-v-flat-atomicrmw` is ff16's flaky TIMEOUT(1)
resolving). Three commits pushed: `da78e671` (metric, stats-only), `3deb087e` (phi-affinity coloring),
`80fc7d8d` (AMDGPUSimplifyUndefPHI pass). Report: `SSARA/08-Worklog/corpuse/corpus-14-07-2026.md`.

### Reusable techniques (this session)
- **Non-interactive hunk-split for separate commits:** classify each `git diff` hunk by content
  marker, emit a subset patch, `git apply --cached` it (commit 1), then a whole-file `git add` stages
  the residual after commit 1 lands (commit 2). Verify with `git diff --cached`.
- **Upstream formatting checks:** local `git-clang-format` can be MORE LENIENT than CI — apply CI's
  proposed diff verbatim. A push rejected with "fetch first" after remote merged main → `git pull
  --rebase` then push (rebases your isolated commit on top).
- **Corpus harness:** jobs=32/timeout=180 avoids the tail-overload timeout→CRASH misclassification
  that jobs=64 produces (some tail tests ballooned to ~700s).

## 2026-07-11 (evening) — guard-test campaign COMPLETE (11 tests) + shell-guard finalized

**11 guard tests committed+pushed** in `llvm/test/CodeGen/AMDGPU/SSARA/`, each REVERT-PROVEN
(crash/incorrect-class when the fix is reverted in the ssara-guard sandbox, clean with it):
rebuildssa-bitcast-oversized-padding (36154bd), rebuildssa-wmma-early-clobber-tied-use (75b82e),
rebuildssa-newdef-among-all-operands (400c67), ra-undef-self-tied-def (030d4d),
rebuildssa-undef-phi-operand (392cc), ra-color-by-operand-flag (4cb21),
ra-dying-use-early-clobber (60727; test_load_mfma_store16), rebuildssa-rmw-subreg-reorder (c8c11;
subreg-coalescer-crash @foo), rebuildssa-loop-carried-phi-self-ref (fad0;
loop-live-out-copy-undef-subrange), spill-phi-def-insertion-point (the previously-UNCOMMITTED
spiller PHI-insert fix — now COMMITTED e138cc9 WITH its test), ra-swap-16bit-permutation (effb6;
v_swap_b16.ll @swap). Commits 50bef5c, 402d82a, 528cbc5, e138cc9, 938f117, 804652.

DEFERRED (precise reasons): #9 partial reload (90a2) is a MISCOMPILE fix, not a crash — reverting
it causes ZERO corpus crashes (partial reload marks un-spilled lanes undef -> wrong code, no
verifier abort); a guard needs a hand-crafted spill+partial-reload correctness CHECK, not an .ll
crash repro. 867d/b293c/c100e do NOT cleanly `git revert` (later commits rewrote the code); covered
by #1/#2/#3 machinery. 316d (CallSites isAllocatable) is perf-only.

### Repro-discovery technique (reusable, reliable)
Revert ONE fix in `ssara-guard` (`git reset --hard HEAD && git revert -n <c> && ninja -C build/guard
llc`), run the harness `--llc /work/atimofee/sandbox/github/ssara-guard/build/guard/bin/llc`, then
diff the CRASH set vs the fixed 103 baseline (`/tmp/corpus-postfix/results.jsonl`) -> the NEW crashes
are that fix's repros; extract the crashing function and verify crash-reverted/clean-fixed. This
found effb6 (v_swap_b16.ll) and c8c11 (subreg-coalescer-crash) where guessing failed. Single-function
extraction sometimes doesn't reproduce (needs the file's pressure) — always confirm.

### Prompt-free tooling (kernel 5.15 = no sandbox; hooks can't auto-approve)
Bare-tool PATH: `export PATH=/tmp/ssara-pin:$PATH` -> bare `llc`/`FileCheck`/`llvm-extract` = fixed
(pinned HEAD) binaries; symlinks `gllc`/`gextract` in /tmp/ssara-pin = the ssara-guard SANDBOX
(reverted) binaries. Cursor Auto-Run Mode = "Use Allowlist" with these first-token chips + BARE tool
invocation (allowlist matches FIRST TOKEN only; `$SG/llc`/`cd &&` never match). External-File
Protection turned OFF (writes to /tmp + ssara-guard are outside the ssara workspace). shell-guard hook
is DENY-ONLY (shlex/quote-aware) — hooks cannot auto-approve, only deny/ask.

## 2026-07-11 — shell approval hardening (stop the once-a-minute "Allow" prompts)

Root cause of the per-command approval pain during autonomous work: on this remote host
Cursor's execution-sandbox never engages (`sandbox:true` = 0 in the hook audit log
`.cursor/hooks/state/shell-guard.log`), so every non-allowlisted command prompts.
Fix (committed to the ssara worktree, `.cursor/hooks/shell-guard.sh`, an APPROVED safety change):
upgraded the audit-only `beforeShellExecution` hook into a DECISION hook that hard-DENYs
destructive carve-outs of otherwise-safe tools and otherwise ABSTAINS (never auto-allows).
Per-segment analysis (split on `| ; &` backtick/newline; peel env/sudo/xargs wrappers; strip
quotes/backslash/path to basename) so a flag on a piped command or a tool name as an argument
never misfires. Blocks: find `-delete/-exec/-fprint*`; every sed `-i` variant + sed `w`/`s///w`
writes; perl `-i`; awk `-i inplace`/`system(`/`print>file`; `tee FILE`; `dd of=`; `truncate FILE`;
`ex`/`ed`. This makes it SAFE to add to Cursor's UI Command Allowlist for auto-run:
`ninja cmake llc FileCheck llvm-extract git cp mkdir find sed perl awk python3` (user adds these
in Settings; hook is the safety net). Test the hook by reading payloads from a FILE — inlining
destructive strings makes the LIVE hook block your own test command.

## 2026-07-10 (evening) — padding fix committed; corpus 195→103; guard-test backlog + infra

**All prior 2026-07-09/10 crash-cluster work is now COMMITTED** (the risky RebuildSSA narrowing #7 was
dropped; safe set + self-tied/V_SWAP_B16/NewDefMI/WMMA-EC fixes landed: git series fad0fc8..75b82eb).

### New fix committed (36154bd): oversized-padding super-use (`MachineLaneSSAUpdater::buildRSForSuperUse`)
A value in an oversized register class (e.g. a 384/448-bit bitcast held in sgpr_512) makes
LiveIntervalCalc fabricate a subrange over never-defined PADDING lanes whose only values are undef (`@x`
== `VNInfo::isUnused()`, confirmed LiveInterval.cpp:1001) joined into a PHI-def. The reaching-VNI query
returned that PHI-def → padding lanes emitted as a live OrigVReg placeholder never patched → dangling
use + illegal subreg index. Fix: (a) restrict the query to lanes with a REAL establishing def
(`!isUnused() && !isPHIDef()`), routing padding to the undef NoSub piece; (b) gate the direct-subreg
fast path on `TRI.getSubClassWithSubReg(RC, Idx)`, else decompose via `getCoveringSubRegsForLaneMask`
(sgpr_512 has no single sub12_..._sub15 / sub14_sub15 index). Repro amdgcn.bitcast.{384,448}bit.ll.

### Corpus: CRASH 195 → 103 (`/tmp/corpus-postfix/`, 3060 tests, no new crash-class regressions)
Top remaining: (30) Failed to find free physreg [cross-call, needs coalescing]; (10) Operand incorrect
register class; (10) Found PHI after non-PHI [amdgcn.bitcast.320/512/640/704/1024bit]; (7) Invalid
Object Idx; (6) Register class not set [GISel]; (6) VOP const bus; (6) Remaining vreg [GWS]; (5)
Multiple vreg defs SSA; (4) v_div_scale; + singletons.

### Guard tests (dev-rule: each fix needs a guarding LIT test). 6 COMMITTED, all revert-PROVEN.
`llvm/test/CodeGen/AMDGPU/SSARA/`: rebuildssa-bitcast-oversized-padding.ll (36154bd),
rebuildssa-wmma-early-clobber-tied-use.ll (75b82e), rebuildssa-newdef-among-all-operands.ll (400c67),
ra-undef-self-tied-def.ll (030d4d), rebuildssa-undef-phi-operand.ll (392cc), ra-color-by-operand-flag.ll
(4cb21). Test commits 50bef5c + 402d82a.
DEFERRED (reasons in NOTES 2026-07-10 evening): V_SWAP_B16 effb63 (needs MIR — 16-bit PHI permutation
cycle), c8c11 RMW ordering (no repro found), fad0 loop-PHI (repro elusive), 90a2 partial reload (noisy
free-physreg signature), 867d/b293c/c100e (don't cleanly revert — code rewritten), 60727 dying-use.
316d CallSites isAllocatable = perf-only, no functional test.

### Reusable guard-test infra (on disk)
Isolated detached worktree `/work/atimofee/sandbox/github/ssara-guard` + minimal `build/guard`
(llc/FileCheck/llvm-extract only; ~10G), built path-independently by reusing the warm ccache via
`CCACHE_BASEDIR=/work/atimofee/sandbox/github CCACHE_NOHASHDIR=true` (this ccache REJECTS
CCACHE_HASHDIR=no/false). Pinned fixed binaries `/tmp/ssara-pin` (HEAD 36154bd). Scratch authoring
`/tmp/ssara-tests`. Revert-proof: in ssara-guard `git reset --hard HEAD && git revert -n <c> && ninja
-C build/guard llc`, run repro (~2min). Bulk repro discovery: revert several, run harness `--llc
ssara-guard/.../llc`, diff crash classes vs 103.

### UNCOMMITTED (user's — commit TOMORROW with a guard test): PHI-after-non-PHI spiller fix
`AMDGPUSSARegisterSpiller::spillAtDefinition` (~1441): when the spilled value's def is a PHI, store was
inserted at `std::next(PHI)` (between PHIs → verifier "Found PHI after non-PHI"). Fix:
`InsertAfter = DefMI->isPHI() ? DefMBB->getFirstNonPHI() : std::next(DefMI->getIterator())`. Diff saved
at `ssa-spiller-docs/SSARA/08-Worklog/UNCOMMITTED_phi-after-nonphi-spiller-fix_2026-07-10.patch`.
Guard-test candidate repro: amdgcn.bitcast.320bit.ll (currently in that class).

## 2026-07-09/10 (late) — crash-cluster fixes; corpus 224→195 (good) then +22 regression from 3 risky changes

**ALL WORK THIS SESSION IS UNCOMMITTED (working tree, `ssara`).** 7 files modified:
`MachineLaneSSAUpdater.cpp`, `AMDGPURebuildSSA.cpp`, `AMDGPUSSARegisterAllocator.{cpp,h}`,
`AMDGPUSSARegisterSpiller.cpp`, `SIInstrInfo.cpp`, test `SSARA/lowerphi-critical-edge-no-split.ll`.

### Corpus trajectory (harness `scripts/ssara_corpus_harness.py`, 3060 tests, gfx-per-test RUN lines)
- Committed baseline (2026-07-08 `b293c794`): CRASH **224**.
- **run1** (this session, GOOD changes only): CRASH **195** (−29). Changes: loop-PHI self-ref fix +
  partial-reload `undef` fix + `CallSites` isAllocatable precision + stale `v_swap` CHECK update.
- **run2** (added 3 RISKY changes): CRASH **217** (+22 vs run1 = NET REGRESSION). Deltas:
  `Invalid subregister index` 17→27 (+10), `even aligned vector regs` 0→3 (+3) [both from RebuildSSA
  narrowing], `SGPR permutation cycle scratch` 0→5, `Using undefined physreg` 1→5 [RA bias/spiller],
  `Failed to find free physreg` 29→**26** (−3, the intended win). `/tmp/ssara-corpus-run` (195) and
  `/tmp/ssara-corpus-run2` (217) hold the JSON.

### CORPUS-SAFE fixes (KEEP — net −29):
1. **Loop-carried PHI self-reference** (`MachineLaneSSAUpdater.cpp` `rewriteDominatedUses`): guard was
   `if (UseMI==DefMI) continue;` — this skipped a loop-header PHI's OWN back-edge operand (the PHI is
   both def of NewSSA and, via the self-edge, a use of OrigVReg), leaving `%X.subN` with no reaching def
   → "reading vreg without a def" at the interval recompute. Fix: `if (UseMI==DefMI && !DefMI->isPHI())`
   — let the PHI's incoming operands flow into `rewriteUseReaching` (reaching-VNI match rewrites the
   self-edge to the PHI result). Repro `loop-live-out-copy-undef-subrange.ll` (gfx906).
2. **Partial reload-as-redef must preserve un-spilled lanes** (`SIInstrInfo::loadRegFromStackSlot` +
   `AMDGPUSSARegisterSpiller::getOrCreateReloadInBlock`): the `SubRegIdx!=0` reload overload stamped
   `RegState::Undef` on the partial def (correct for a FRESH-vreg reload, WRONG for Option-3
   reload-as-redef of a live OrigVReg — it made LiveIntervals treat the reload as a fresh whole-reg def,
   killing the un-spilled lanes → reconstruction sourced them `undef` in the REG_SEQUENCE, dropping live
   data). Fix: drop the unconditional `Undef` in `loadRegFromStackSlot` (`SubRegIdx!=0`, spiller-only
   path — the only non-default caller); spiller re-applies `undef` ONLY when the complement is dead
   across the reload (`S.liveAt(RIdx.getRegSlot())`). Fixed 3 SSASpiller tests (multi-path-independent,
   use-before-spill, sgpr-wide).
3. **`CallSites` over-capture** (`AMDGPUSSARegisterAllocator.cpp`): the implicit-physdef clobber-site
   predicate used `!MRI->isReserved(reg)`, catching every `implicit-def $scc/$vcc` ALU op (S_CMP etc.).
   Not a correctness bug (`modifiesRegister` is exact so no false rejects) but bloats CallSites + slows
   pickFreePhysReg. Fix: `MRI->isAllocatable(reg)` (only regs a value could be colored onto matter).
4. Stale `v_swap_b32` CHECK in `lowerphi-critical-edge-no-split.ll` regenerated (coloring aligned the
   per-lane accumulator PHI results with the atomic result → no swap needed; verified correct vs greedy).

### RISKY fixes (REVERT or rework — run2 net +22):
5. **Spiller call-clobber pressure charge** (`AMDGPUSSARegisterSpiller.cpp` `processFunction` +
   `findRegMask`): at a call, charge `Shortfall = max(0, RPLimit − #callee-saved-allocatable)` against
   the live-after set so cross-call values spill to the callee-saved budget. Principle correct (only
   fires when cross-call > callee-saved, i.e. when greedy would also spill), but see regressions.
6. **RA call-clobber color-choice bias** (`AMDGPUSSARegisterAllocator.{cpp,h}` `pickFreePhysReg` +
   `CallerSavedReg` BitVector): non-cross-call values prefer caller-saved regs (leave callee-saved for
   cross-call). Dominance-order preserved (Hack-safe — biases CHOICE not ORDER; do NOT reorder to color
   cross-call first, that violates the PEO completeness proof).
7. **RebuildSSA single-partial-def narrowing** (`AMDGPURebuildSSA.cpp`): don't skip a `getNumValNums==1`
   vreg when its sole def is a PARTIAL (subreg) def — route through the existing Root-narrowing so a
   `undef %x.sub0:vreg_128` (only sub0 live, used whole via COPY) narrows to the defined lanes' class.
   Fixed `undef-handling-crash-in-ra.ll` (spill-free, matches greedy) BUT is the main regressor
   (+10 Invalid subregister index, +3 even-aligned) — narrowing produces illegal subreg indices /
   violates align2. **Likely revert this one first and re-measure.**
   **LEADING HYPOTHESIS for the #7 regression (user, 2026-07-10):** rewriting a single-def partial Root
   loses/mis-uses the pre-repair frozen snapshot. Two candidate mechanisms: (a) single-def vs multi-def
   freeze content differs — multi-def freezes on the FIRST repairSSAForNewDef call (full original
   interval, all lane subranges) and narrows Root LAST using it; the new single-def path freezes an
   interval with ONLY sub0 defined (upper lanes have no subrange), so `buildRSForSuperUse`/
   `collectReachingVNIs` rebases the upper lanes onto an illegal subreg index / non-align2 slice; OR
   (b) narrowing `%137` mutates `%128 = COPY %137` into a REG_SEQUENCE, making already-frozen/processed
   `%128/%159` snapshots stale → the align2/subreg errors land on the copy chain. TEST: revert #7 →
   corpus ~195; re-apply #7 alone; on an `Invalid subregister index` repro break in `buildRSForSuperUse`
   and compare FrozenOrigLI upper-lane subranges for a single-def Root vs a multi-def Root.

### KEY FINDINGS for tomorrow (recorded in `08-Worklog/BACKLOG.md` HIGH PRIORITY):
- **"Failed to find free physreg" class is a CROSS-CALL COLORING problem, NOT under-spilling** — greedy
  compiles these with `ScratchSize:0` (no spill). A value live across a call may only take callee-saved
  regs; the SSA one-shot coloring can't pack them (esp. wide *aligned* `vreg_128_align2`) where greedy
  succeeds via EVICTION. `undef-handling-crash-in-ra.ll`: `%137:vreg_128_align2` has only sub0 live
  (ISel wide-undef) + uncoalesced `COPY %137→%128/%159` chains → inflated demand on the 4 aligned
  callee-saved tuples. Real lever = **coalescing** (already "Pending: PHI coalescer") + the narrowing.
- **Spiller vs RA size RPLimit differently (HIGH PRIORITY, unresolved):** spiller uses
  `getMaxNumVGPRs(MF)` (gfx90a=128, −10%→116, INCLUDES the AGPR half); RA uses the allocatable count of
  the exact class (`RegClassInfo.getNumAllocatableRegs(VGPR_32)`=64). Spiller over-budgets ~2×. Which is
  correct + can they be reconciled? Likely spiller should query `getNumAllocatableRegs`. NOT changed yet
  (recorded only).

### NEXT SESSION plan:
1. Revert change #7 (RebuildSSA narrowing) → re-run corpus → confirm back to ~195/198. Then decide if #5/#6 net-help or also revert.
2. Commit the corpus-SAFE set (#1–#4) — they're net −29 and regression-free.
3. Attack "free physreg" via coalescing (the real fix) + revisit narrowing safely (legal-subreg/align2-aware).

---

## 2026-07-08 (eve) — 3 fixes committed+pushed; CRASH 275→224; free-physreg reclassified; spiller design docs

- **COMMITTED + PUSHED (ssara), 3 fixes this session:**
  - `c100e9a8` [AMDGPU] SSA RA: reject clobbered registers for values live across calls and inline asm —
    the CallSites clobber-interference mechanism (`.cpp` + `.h`): pickFreePhysReg rejects any candidate a
    live value crosses that a call regmask OR an instruction implicit physreg-def clobbers; PLUS fold each
    call regmask into MRI via `addPhysRegsUsedFromRegMask` so PEI's `findUnusedRegister` stops picking a
    call-clobbered SGPR as the whole-function FP-save reg. (Predicate = implicit non-reserved physdef;
    explicit defs excluded to avoid ~71-test coalescing churn + a bf16 occ/spill regression.)
  - `b293c794` [CodeGen][MachineLaneSSAUpdater] Source reconstructed old lanes by reaching VNInfo — fixes
    `Reading virtual register without a def` on RMW partial-def chains. Root cause (found via gdb, NOT the
    earlier iteration/ordering guesses): `buildRSForSuperUse` decided old-lane undef-vs-defined by the
    GLOBAL "does OrigVReg own a subrange" test; a lane that owns a subrange but is DEAD at the use (poison
    buffer-descriptor base read whole by a later store) was sourced as a live def-less read. Fix: decide
    per lane group from the reaching VNInfo at the use (`collectReachingVNIs`/`getVNInfoBefore`): null →
    undef; renamed-this-session → renamed vreg (build-time, order-independent); live non-renamed →
    OrigVReg placeholder. Surviving partial defs untouched.
  - (Also earlier in the day: the two clobber fixes were validated then squashed into `c100e9a8`.)
- **Corpus trajectory (harness `scripts/ssara_corpus_harness.py`, 3060 tests):** postfix12 CRASH 255 →
  postfix14 (clobber fix) 250 → **postfix15 (reaching-VNI) CRASH 224**. Every step 0 OK→CRASH; the few new
  REGRESSION_OCC_OR_SPILL all came FROM crash (net improvement). Undefined-physreg 9→1; reading-vreg 43→28.
- **[CORRECTED CLASSIFICATION] `Failed to find free physreg` (27) is NOT one cause** (user challenged the
  blanket "defer to spiller redesign"; only 2/27 have the inline-asm fragmentation signature). Clusters:
  AV/AGPR pinned-wide (7: a-v-*-atomicrmw, ds_*_a_v, rewrite/unspill-vgpr-mfma), GlobalISel div/rem i64
  (6), whole-wave/WWM (3), fragmentation-deferred (2: spill-scavenge-offset, spill-alloc-sgpr-init-bug),
  misc (9). gdb triage of `global_atomic_xchg_i32_ret_av_av_no_agprs` (gfx90a): two live `vreg_1024_align2`
  pin v0-v63, no slot for a `vreg_64` REG_SEQUENCE; greedy compiles at NumVgprs=64 + Scratch=132 (greedy
  SPILLS) → our spiller UNDER-spills. So AV cluster = genuine high-pressure spiller-planning, NOT trivial
  bugs (an earlier "greedy uses 11 VGPRs" read was the WRONG function in the file).
- **[NEW SKILL] `gdb-debugging`** (`~/.cursor/skills/gdb-debugging/SKILL.md`, drives persistent gdb via
  `scripts/gdbctl.sh`) — validated this session; pinpointed the AV failing MI + pinned-1024 pressure in a
  few commands. (Cursor fact: a newly added skill is only visible in NEW chats, not the creating one.)
- **[MEETING DIRECTION → design docs created]** Implement the fragmentation-aware spiller by augmenting
  `GCNUpwardRPTracker` with a precolored-unit BitVector + per-register-class `getClassCapacity(RC)` API
  (naive `⌊(N-|O|)/K⌋` first, run-based `Σ⌊Li/K⌋` later), replacing the ad-hoc scalar `LivePhysRP` (+ its
  dead-clobber over-count). Two new Design docs (mermaid + KaTeX):
  `SSARA/04-Design/GCNUpwardRPTracker_PerClassRP.md` and `SSARA/04-Design/Spiller_Redesign.md`.
  OPEN Q for tomorrow: `NumAvail/K` arithmetic — VReg_64 is 2 RU (so `/2`), meeting note said `/4`
  (=VReg_128); confirm per-class-K vs fixed-4-RU-slot granularity.
- **Next-session agenda:** (1) build the per-class RP tracker (milestone 1-2 in Spiller_Redesign.md),
  target the AV cluster; (2) continue crash triage — largest fixable = `Found PHI with NoPHIs` (43,
  SSA-destruct leftover PHIs, bitcast/Flow-block subreg-source PHIs) and remaining `Reading vreg` (28,
  wmma family); (3) port `b293c794` reaching-VNI fix to the `mssa-updater` worktree copy + gtests.

## 2026-07-08 — Two clobber fixes committed-ready + FULL spiller-redesign design recorded

- **Two APPROVED fixes in working tree (`AMDGPUSSARegisterAllocator.cpp`), corpus-validated (postfix14 vs
  baseline postfix12, 3060 tests):** (1) fold call regmask clobbers into `MRI` via
  `addPhysRegsUsedFromRegMask` in the clobber-site pre-scan → fixes PEI picking a call-clobbered SGPR as the
  whole-function FP save (`getVGPRSpillLaneOrTempRegister`→`findUnusedRegister` gated on
  `MRI.isPhysRegUsed`, which the RA framework normally populates and we bypassed). (2) generalize
  `CallSites` collection to also record instructions with an IMPLICIT non-reserved physical def (inline-asm
  `implicit-def dead early-clobber $vgprN`), so values live across inline-asm clobbers aren't colored onto
  clobbered regs. Predicate narrowed to `isImplicit()` after the broad version caused ~71-test
  OK→MIXED/DIFF_COALESCING churn + a `bf16.ll` occ/spill regression. **Result: `Using an undefined physical
  register` 9→1, CRASH 255→250, 0 OK→CRASH, churn eliminated, bf16 regression gone.** Remaining undefined-1
  = `indirect-addressing-si-gfx9` (distinct: real call/wide-tuple).
- **[DESIGN RECORDED — see NOTES.md 2026-07-08 "[DESIGN] Fragmentation-aware spiller + greedy fallback"]**
  Full multi-turn design for the `Failed to find free physreg` bucket, to consult WHEN the spiller redesign
  starts. Key conclusions: (a) root cause is the spiller's SCALAR 32-bit-slot pressure metric being blind
  to tuple ALIGNMENT/FRAGMENTATION from scattered pre-colored inline-asm clobbers (NOT occupancy, NOT
  "spiller ignores clobbers"); greedy survives only via spill-on-placement-failure. (b) This is the
  aliasing + pre-coloring NP-hard fringe — `MAXLIVE<=k` in slots is necessary-not-sufficient; the SSA
  colorability theorem's preconditions (uniform regs, no pre-color) are violated. (c) HARD INVARIANT:
  coloring MUST NEVER insert instructions — spill/reload need `EXEC(spill)==EXEC(reload)` or WWM, tractable
  only in the dedicated early spiller; this is THE reason SSA RA exists, so greedy-style spill-at-color is
  FORBIDDEN → coloring must be guaranteed to succeed before it starts (no in-flight recovery). (d) Plan:
  fragmentation-aware early spiller (per-width capacity `F(defRC, demand_W from LIS, preColored(P)
  arrangement, widerFootprint_W)`; pre-color state = LIS reg-unit ranges + regmask index; width-descending
  charge) + a CONSERVATIVE early (pre-RebuildSSA) whole-function greedy-fallback gate for the residual
  fringe. Per-function routing = flag + guarded dual pass-chains (in-allocator split RULED OUT).

## 2026-07-07 (PM) — Corpus crash reduction: 10 fixes total; CRASH 852 -> 275

- **Continuation of the corpus-driven triage (harness `scripts/ssara_corpus_harness.py`).** Regression
  gate = per-test bucket TRANSITION vs baseline run `scripts/out/ssara-corpus/full-run2` (852 CRASH).
  **Net: CRASH 852 -> 275 (-577, -68%), 577 files fixed, 0 compiled->crash and 0 compiled->worse-alloc
  regressions; SSARA+SSASpiller lit 87 pass + 1 XFAIL throughout.**
- **Commits (manual):** `9b30c8ab` (the 6 morning fixes; amended from mangled-subject `656baf05` then
  force-pushed `--force-with-lease` — content identical), `4cb211e6` (#7), `867d2e17` (#8), `60727a8a`
  (#9). **#10 UNCOMMITTED** — held until the call-site `undefined physical register` class is fully
  resolved (working tree: `AMDGPUSSARegisterAllocator.{cpp,h}`).
- **#7 color defs/uses by operand FLAG not position** (`color()`): `MI.defs()/uses()` key off operand
  position (`getNumExplicitDefs()==0` for INLINEASM), so inline-asm-defined vregs went uncolored.
  Iterate `MI.operands()` by `isDef`/`isUse`; EXCLUDE implicit defs (`|| MO.isImplicit()`) since they are
  call/instr clobbers `MI.defs()` also skipped (marking them occupied exhausts the file). INLINEASM
  constraint defs are explicit; only clobbers implicit. `Virtual register not colored` 286 -> 1.
- **#8 source undef lanes as undef** (`buildRSForSuperUse`): whole-reg use of a partially-undef wide
  value (poison buffer-descriptor base ptr) decomposed to a REG_SEQUENCE read the undef lanes plainly ->
  `Reading vreg without a def`. Split `LanesFromOld` into defined (union of OldVR subrange lanemasks; NO
  `liveAt` - too strict) vs undef (no subrange), source undef with `RegState::Undef`. 85 -> 43.
- **#9 no dying-use reuse for early-clobber defs** (`color()`): kills-before-defs freed a dying source
  that an early-clobber def then reused (`early-clobber $sgpr0_sgpr1 = S_LOAD_ec $sgpr0_sgpr1`) -> read a
  clobbered value. When the MI has an early-clobber def, defer freeing dying uses until after the def
  loop (DeferredUnits for physreg per-unit resets vs DeferredFree for colored-vreg markFree - different
  granularity: physreg units are independently live, colored vregs die atomically).
- **#10 (UNCOMMITTED, INCOMPLETE) call-clobber-aware coloring** (`color()`+`pickFreePhysReg`, member
  `CallSites`): a vreg live across a call was colored to a reg the call destroys (csr_amdgpu regmask OR
  explicit call def like return-addr `$sgpr30_sgpr31`) -> `undefined physical register`. Reject a
  candidate if the vreg is `liveAt(callSlot)` and `CallMI->modifiesRegister(PR)` or a regmask clobbers
  it. 64 -> 30. REMAINING 30 = a DIFFERENT sub-cause: CSR save/restore in the frame prologue/epilogue
  (`$sgpr33 = frame-destroy COPY $sgpr6`) - finish that before committing #10.
- **NEXT:** finish the call-site class (CSR save/restore undefined-physreg) then commit #10; then by
  impact `Reading vreg without a def` (43), `Invalid subregister index` (26), `Operand has incorrect
  register class` (25), `DefOp NewDefMI should have a def operand` (18). `Found PHI with NoPHIs` (43) is
  mostly fatal-path MF.verify collateral and should shrink as real errors are fixed.

## 2026-07-07 — Corpus-driven SSA-RA crash reduction: 6 fixes (COMMITTED+PUSHED 656baf05)

- **[TOOL] `scripts/ssara_corpus_harness.py`** (in `github/scripts/`, NOT llvm-project). Runs the whole
  `llvm/test/CodeGen/AMDGPU` corpus through the SSA stack: reuses each test's own RUN line, strips
  `|FileCheck`/`-o`, injects `-amdgpu-ssa-regalloc` (+`-verify-machineinstrs`), and on success diffs
  per-function VGPR/AGPR/scratch/occupancy vs Greedy (same cmd minus the flag). Buckets: CRASH(by
  normalized signature), OK_EQUAL/OK_BETTER, DIFF_COALESCING, MIXED, REGRESSION_OCC_OR_SPILL,
  PREEXISTING_FAIL, TIMEOUT, NO_METRICS, SKIP_*. `run`/`report` subcommands; parallel `--jobs`
  (default ncpu/2); resumable `results.jsonl`. **The regression gate is the per-test bucket TRANSITION
  vs a baseline run dir (compiled-at-baseline -> crash-now), NOT net class counts.** Baseline run
  `out/ssara-corpus/full-run2`, final `postfix6`. Metric caveat: `.set *.num_vgpr` omits AGPRs;
  occupancy can drop with VGPR unchanged on MFMA — check `.num_agpr` too.
- **[RESULT] Clean Pareto improvement: CRASH 852 -> 490 (-362), 362 files fixed, 0 compiled->crash AND
  0 compiled->worse-alloc regressions; SSARA+SSASpiller lit 87 pass + 1 XFAIL.**
- **[6 FIXES] one commit 656baf05** (`AMDGPURebuildSSA.cpp`, `MachineLaneSSAUpdater.cpp`,
  `AMDGPUSSARegisterAllocator.{cpp,h}`):
  1. RebuildSSA **single-block RMW partial-def chains**: a non-`undef` subreg def read-modify-writes the
     super-reg, so a wide value built from a chain where only the first def has `undef` must keep the
     establishing (earliest-slot) def as Root and rename re-defs in REVERSE dominance order (Root
     narrowed last). Gated `SingleBlock && HasRMWRedef`. Killed `Use not jointly dominated by defs`
     117->0 + its verifier twin `Reading vreg without a def`.
  2. MachineLaneSSAUpdater `rewriteUseReaching`: derive REG_SEQUENCE result class from the base-0
     **rebased** lane mask (`rebaseLaneMask(OpMask,OpMask)`), since unaligned super-reg subregs
     (sub1_sub2_sub3 of sgpr_128) have no `getSubRegisterClass`.
  3. `eliminateRegSequences`: an unaligned dest subreg slice (`getSubReg(Dst,Sub)==NoRegister`, because
     SGPR tuples >=64b exist only at aligned bases — SGPR_64 stride 2, SGPR_96/128 stride 4) is lowered
     as per-dword 32-bit copies via `getChannelFromSubReg`+`getSubRegFromChannel`.
  4. `rewriteOperands`: assign `RegClassInfo.getOrder(RC).front()` to undef-only operands (no value to
     color; undef flag preserved). Fixed `Virtual register not colored` 286->111.
  5. `resolvePermutation`: AGPR is a THIRD file (no swap/xor) — break AGPR cycles with an AGPR scratch,
     not the SGPR path (which emitted illegal `$sgpr=COPY $agpr`). New `MaxAGPRIdx`, high-water tracked
     by the CHOSEN physreg file (also fixes latent av_*->VGPR undercount).
  6. RebuildSSA `flattenRegSequences`: collapse nested REG_SEQUENCE towers (areg_64->96->...->384) the
     lane-by-lane rebuild produced; absent a coalescer they inflate pressure (bf16 MFMA 43 AGPR/occ5 ->
     32/occ8 == greedy). Inline single-use whole-read child RS, composing lanes via
     `composeSubRegIndexLaneMask` (NOT `composeSubRegIndices`, which silently mis-handles compositions
     missing a defined subreg index).
- **[LEARNINGS]** (a) a test that ABORTS has NOT passed — never accept "the crash moved to another pass";
  (b) grep the component for existing helpers (`rebaseLaneMask`, `getSubRegIndexForLaneMask`,
  `composeSubRegIndexLaneMask`, `getCoveringSubRegsForLaneMask`) BEFORE theorizing from stack traces;
  (c) `composeSubRegIndices(a,b)` = b within a AND silently returns garbage for illegal compositions ->
  use lane-mask composition; (d) `SmallPtrSet<Register>` does not compile -> `DenseSet<Register>`.
- **[NEXT]** top remaining crash buckets (postfix6): `Virtual register not colored` 111 (non-undef
  sub-cause), `Using an undefined physical register` ~87, `Reading vreg without a def` ~98, `PHI with
  NoPHIs` ~47 (largely fatal-path MF.verify collateral). Attack `not colored` 111 + `undefined physical
  register` 87 next by impact. Still open from prior agenda: deeper spiller redesign (#1b), design-doc
  refresh (SSA_RA_Coloring), SSARA kickoff deck (needs 3 workstream areas).

## 2026-07-08 (housekeeping) — workspace-layout rule, AGENTS drift fix, gdb debugging tooling

Meta/workflow session (no SSARA compiler code changed).

- **[RULE] `.cursor/rules/workspace-layout.mdc`** (always-apply): canonical worktree layout under `github/` (ssara [primary/integration], next-use-analysis [NUA], early-ssa-spiller [SSA Spiller], mssa-updater [+gtest harness], llvm-project [clean upstream], scripts [permanent tools], ssa-spiller-docs [the "docs" repo: design docs + NOTES + SHARED_CONTEXT]) + script placement: permanent/multi-session → `scripts/`, throwaway/one-off → `/tmp`.
- **[AGENTS DRIFT — root cause + fix]** The corpus harness (built 07-06, used through 07-07) had NO reference in AGENTS.md although richly recorded in SHARED_CONTEXT/NOTES. Root cause: AGENTS is fed ONLY by `agents-memory-updater`, whose transcript index was stale/divergent — two files, `ssara/.cursor/hooks/state/continual-learning-index.json` (@2026-07-04, key `last_updated`) vs `~/.cursor/projects/…/…` (@2026-07-06T18:01, key `updated_at`) — and it never processed the 07-07 sessions. "Save context" reliably updates NOTES/SHARED_CONTEXT, but the AGENTS promotion step didn't run. Fixed: recorded the harness as a durable AGENTS fact, marked agenda item (2) DONE, corrected the stale worktree bullet. LESSON: on "save context", promote durable tools/facts DIRECTLY into AGENTS — do not rely solely on the updater. (Open: reconcile the two divergent index files / run agents-memory-updater to catch up 07-07.)
- **[TOOL] `scripts/gdbctl.sh`** — persistent, agent-driven gdb across separate tool calls (background gdb reads a FIFO; sentinel-synced; `start`/`send`/`log`/`status`/`stop`; state persists). Verified controlling the 1.8 GB debug `llc` (first symbol-resolving break ~1-2 min, then fast; `GDBCTL_TIMEOUT`, `GDBCTL_DIR`).
- **[SKILL] `~/.cursor/skills/gdb-debugging/SKILL.md`** (personal) — wraps gdbctl + a 6-step "debug the test crash" algorithm chaining the triage/evidence/regression/approval rules; auto-invokes on "debug the test crash". CURSOR FACT: skills are discovered at startup/chat-start → available only in NEW chats (not already-open ones); rules differ (re-scanned per message, reach open chats next turn).

## 2026-07-07 — Workflow/interface housekeeping (rules + Cursor auto-run allowlist + audit hook)

Meta session (no SSARA compiler code changed). Tuned the human↔AI interface and Cursor guardrails.

- **[RULES] Two new always-apply `.cursor/rules/`** (join `investigate-dont-rationalize` as the epistemics/regression cluster):
  - `evidence-over-memory.mdc` — no claims about root cause/behavior/fix from memory or theory; ground every claim in real-execution evidence (dumps, logs, a reproducing run, verifier). Memory/NOTES/SHARED_CONTEXT are leads, not verdicts. Prefix unverified statements with **HYPOTHESIS:**.
  - `regression-baseline-is-truth.mdc` — the known-good baseline is the sole arbiter of a behavior change; a failure that merely MOVES/changes shape (different pass, different error, different test) is still an unresolved regression, never "progress"; only baseline-or-better = done.
- **[CURSOR AUTO-RUN — verified empirically, Cursor 3.2.16, Windows client + Linux remote]** Auto-Run Mode = "Use Allowlist". The authoritative gate is the **Settings-UI Command Allowlist**, stored CLIENT-SIDE (Windows `AppData\Roaming\Cursor`), NOT editable from the Linux box → user adds entries via UI. Matching is command-string **PREFIX**-based; it **governs background subagents too** (non-allowlisted subagent command → View/Allow prompt in parent UI, blocks the subagent until clicked). `ninja -C build/user-debug` as an entry scopes builds to the correct folder. Prefix matching can't carve exceptions → bare `sed`/`find` also allow `sed -i`/`find -delete`; scoped `sed`→`sed -n`, left `find` OFF (OPEN ITEM: find is agent-critical — revisit via subagent hook-DENY test or Cursor 3.6+ Auto-review).
- **[HOOK]** `beforeShellExecution` hook fires for subagents but its `allow` is NOT honored there (they fall back to the UI allowlist); a logging-only hook (read stdin, write nothing, exit 0) safely ABSTAINS (verified — does not default to allow). Installed audit hook: `.cursor/hooks.json` → `.cursor/hooks/shell-guard.sh` → log at `.cursor/hooks/state/shell-guard.log`. Subagent discriminator in hook input: `transcript_path == null`.
- **[OPEN ITEM]** `find` read-only auto-run without permitting `-delete`/`-exec`: (a) empirically test whether hook-DENY is honored inside subagents (then allowlist `find` + deny mutating forms), or (b) upgrade to Cursor 3.6+ Auto-review. User: "get back to this soon."

## 2026-07-06 (PM) — AMDGPU corpus harness + single-block RMW fix (applied, uncommitted, DECISION PENDING)

- **[TOOL] `scripts/ssara_corpus_harness.py`** (in `github/scripts/`, NOT llvm-project). Runs the whole
  `llvm/test/CodeGen/AMDGPU` corpus through the SSARA stack: reuses each test's OWN RUN line, strips
  `| FileCheck`/`-o`, injects `-amdgpu-ssa-regalloc` (+`-verify-machineinstrs` correctness gate), runs
  our stack; on success re-runs the same cmd minus the flag (Greedy) and diffs per-function
  `; TotalNumSgprs/NumVgprs/ScratchSize/Occupancy` + `.set *.num_vgpr/.numbered_sgpr/.private_seg_size`.
  Buckets: CRASH (normalized sig), OK_EQUAL/OK_BETTER, DIFF_COALESCING, MIXED, REGRESSION_OCC_OR_SPILL,
  PREEXISTING_FAIL, TIMEOUT, NO_METRICS, SKIP_*. Parallel `--jobs` (default ncpu/2), resumable
  `results.jsonl`, `run`/`report` subcommands. Parser handles bash `<` metachar, `2>&1`, lone `-`
  (stdin), `%t.bc` generated inputs. Runs: `scripts/out/ssara-corpus/{full-run2 (baseline), postfix}`.
- **[TRIAGE baseline `full-run2`]** 3060 .ll; 850 skipped; 2210 attempted -> 852 CRASH (38.6%), 1357
  compiled. Allocation quality ~= Greedy (only 9 REGRESSION_OCC_OR_SPILL; rest equal/better/coalescing).
  **Headline: crashes are the problem, not allocation quality.** 852 crashes = 26 classes; top6 = 87%.
  By owner: SSA-RECON 257 (117 `Use not jointly dominated`, 85 `Reading vreg without a def`, 47 `PHI
  with NoPHIs`=collateral of the fatal-path MF.verify), RA-COLORING 319 (286 `Virtual register not
  colored`, 17 tied-use, 11 failed-physreg), OP-REWRITE 259 (119 `use operand subreg has no register
  class`, 85 `undefined physical register`, ...). Full report + prioritized plan:
  `scripts/out/ssara-corpus/full-run2/TRIAGE_PLAN.md`.
- **[ROOT CAUSE #1 — RMW partial-def chains]** `add.ll -mcpu=verde` (@s_add_v8i32, single straight-line
  block). Wide vreg built by a chain of partial subreg defs where only the FIRST has `undef`; later
  subreg defs without `undef` READ-MODIFY-WRITE (implicitly read unwritten lanes). Old RebuildSSA split
  them as independent re-defs; renaming the establishing (undef) def stripped lanes later RMW defs read
  -> `createAndComputeVirtRegInterval` aborts `Use not jointly dominated`. Same root as the 85 `Reading
  vreg without a def` (verified: same `RebuildSSA -> repairSSAForNewDef -> performSSARepair ->
  createAndComputeVirtRegInterval -> LiveRangeCalc::findReachingDefs` path; the two strings are the same
  failure via report_fatal_error vs the forced MF.verify dump). ~202 crashes, one root.
- **[FIX APPLIED, UNCOMMITTED — `AMDGPURebuildSSA.cpp`]** For a vreg whose defs are ALL in one block and
  include a non-`undef` subreg def (`SingleBlock && HasRMWRedef`): Root = establishing (earliest-slot)
  def via `(DomPreorder, slot)` tie-break; re-defs renamed in REVERSE order (latest first) so each
  still-present def reads only dominating, not-yet-renamed lanes; Root processed last and narrowed
  normally (pressure-neutral, no wide leftover). Multi-block/loop vregs keep byte-identical old behavior
  (reverse-order is only dominance-safe intra-block; loop back-edge reads are not from dominators).
- **[RESULT — NOT A CLEAN WIN; user must decide next session]** SSARA+SSASpiller lit = 87 pass + 1 XFAIL
  (0 CURATED regressions). Harness `postfix` vs `full-run2`: `Use not jointly dominated` 117->0
  (eliminated), Two-address 13->1, net CRASH 852->785 (-67). BUT per-test transitions: **192 fixed
  (CRASH->compile), 125 REGRESSED (compiled-before -> CRASH-now)**; 123/125 = `UseRC && "use operand
  subreg has no register class"`, overwhelmingly WIDE-DESCRIPTOR intrinsics (image/buffer, dwordx3=96b).
  Root of regression: reverse-order reconstruction changes which def owns which lanes at a use, pushing
  wide uses out of `rewriteUseReaching`'s whole-operand early-return (MachineLaneSSAUpdater.cpp:448)
  into the partial-REG_SEQUENCE path (line 465-468), where `TRI.getSubRegisterClass(OpRC, subreg)`
  returns NULL for those widths -> assert. LATENT reconstruction weakness the reorder exposes.
- **[DECISION PENDING — resume here tomorrow]** Options (asked user, unanswered): (a) REVERT to clean
  baseline (loses 192 fixes, reintroduces 117); (b) KEEP + add COUPLED fix = handle null `UseRC` in
  `rewriteUseReaching` (derive REG_SEQUENCE result class for the lanemask when `getSubRegisterClass` is
  null; read `buildRSForSuperUse` + class-derivation APIs first), then re-run harness to confirm 0
  compile->crash regressions. RECOMMENDATION: (b) if UseRC-null handling is small, else revert +
  scoped follow-up. Repro: `llc -mtriple=amdgcn -mcpu=tonga -amdgpu-ssa-regalloc
  llvm.amdgcn.buffer.store.dwordx3.ll` (@raw_buffer_store_format_immoffs_x3). Working tree has the
  uncommitted `AMDGPURebuildSSA.cpp` edit (user commits manually — DO NOT commit).
- **[Remaining agenda unchanged]** #1b deeper spiller redesign; #3 design-doc refresh (SSA_RA_Coloring +
  reaching-VNI/Option-3); #4 SSARA kickoff deck (needs 3 workstream areas from user). Next crash target
  after RMW: `Virtual register not colored` (286, coloring) and `use operand subreg has no register
  class` (base 119, now the #1 blocker on wide builds).

## 2026-07-06 — Legacy dominance/IDF SSA-repair path removed (ssara, committed+pushed)

- **[CLEANUP]** Single commit (-967/+54). Design is now unified on reload-as-redef + inline
  reaching-VNI repair, so the old dominance/dom-group/IDF path was deleted:
  - **Spiller** (`AMDGPUSSARegisterSpiller.{cpp,h}`): removed orphaned legacy reload cluster
    (`emitReload`, `emitReloadToReg`, `reloadBefore`, `reloadAtEnd`, `repairSSAForReload`,
    `processPIdfBlock`, `processKillDominatedGroups(WithList)`, `fixPathologicalPHIs`) + unused
    `getRegNameForDebug`. Live path: `emitReloadsAndRepairSSA` →
    `getOrCreateReloadInBlock`/`insertReloadForUse` + `optimizeReloadPlacing` + `canHoistReloadTo`.
  - **MachineLaneSSAUpdater** (`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp` + header): removed the
    `UseReachingOracle` flag (only ever set false in the now-callerless `repairSSAForReload`, so it was
    always true); collapsed both guarded branches to the reaching path. Deleted `repairSSAForReload`,
    `createPHIInBlock`, `findRenamedReachingDef`, `insertPHIAtBlock`, `getPrunedIDF`, `incomingOnEdge`,
    and the write-only `RenamedLaneDefs` map (superseded by `DefInstrToRenamed`, MachineInstr*-keyed).
    `insertLaneAwarePHI(Register OrigVReg, LaneBitmask DefMask)` now places PHIs solely from OrigVReg's
    frozen isPHIDef VNInfos; `rewriteDominatedUses` always calls `rewriteUseReaching`.
  - NOTE: this was done ONLY in the ssara worktree. No port to `mssa-updater`/`early-ssa-spiller` has
    been done or planned in this session.
- **[DESIGN] IDF fully removed (2026-07-06, COMMITTED+PUSHED as 839660b).** No IDF anywhere in
  MachineLaneSSAUpdater/spiller. PHI placement (reconstruction) reads the isPHIDef VNInfos
  LiveIntervalCalc materializes in OrigVReg's frozen interval when it is recomputed after reload
  re-defs (reload-as-redef keeps the value live through merges via the still-attached original uses).
  The spiller's `isUseReachableFromDef` only asked whether a use is downstream of the kill — for SSA
  that is exactly plain CFG reachability (the pruned-IDF slow path was set-equivalent). Now it is a
  successor-closure BFS from the kill block to the use target block (PHI use → predecessor block),
  same-block by slot order + `MDT.dominates` fast path; DefMask param dropped. DELETED: `computePrunedIDF`,
  `IDFCache`/`IDFCacheKey`(+DenseMapInfo), `clearIDFCache`, `defDominatesUse`, `defReachesUse`, the
  MachineOperand overload of `isUseReachableFromDef`, and the GenericIteratedDominanceFrontier.h include.
  Kept DenseMapInfo<LaneBitmask> (used by LanePHIs). Behavior-preserving (test counts == baseline); the
  only DF work left is inside core LiveIntervalCalc. Deferred follow-up (1b): reload only kill-dominated
  uses + let reconstruction absorb parallel-path merges → would remove `isUseReachableFromDef` entirely.
- **[TEST STATE]** SSASpiller+SSARA lit: 86 pass + 1 legit XFAIL (`spill-loop-skip-def-inside.mir` —
  unimplemented loop-aware spill-candidate fallback; keep). MachineLaneSSAUpdater dir: 3 real-pipeline
  `.ll` pass; 4 `.mir` harness tests fail because `-run-pass=test-machine-lane-ssa-updater` is not
  registered in the ssara build (pre-existing infra, not correctness).
- **[BUILD/TEST]** `ninja -C build/user-debug LLVMCodeGen LLVMAMDGPUCodeGen` (libs); `ninja -C
  build/user-debug llc FileCheck` (tools; no llvm-lit ninja target). Lit: `python3
  build/user-debug/bin/llvm-lit -sv <dirs>`.
- **[NEXT SESSION]** (1) DONE — IDF eliminated + machinery deleted (staged); optional 1b = deeper
  spiller-planning redesign to drop `isUseReachableFromDef`. (2) `scripts/` AMDGPU e2e harness → bucket
  failures → triage/fix plan; (3) update `SSARA/04-Design/SSA_RA_Coloring.md`; (4) SSARA team kickoff
  deck (3 engineers, split TBD).

## Worktree Layout

| Worktree | Branch | Purpose |
|----------|--------|---------|
| `ssara-wt-widthaware` | weekend/prespill-widthaware | **CURRENT working tree — all work and testing happens here** (2026-08) |
| `ssara` | ssara | SSA Register Allocator (integration target; bulk-promoted to once the corpus is green) |
| `ssara-claude` | claude-sandbox | STALE build (2026-08-07) — do NOT test here, it rejects current flags |
| `early-ssa-spiller` | early-ssa-spiller | SSA Spiller (synced with ssara) |
| `next-use-analysis` | next-use-analysis | Next Use Analysis pass |
| `mssa-updater` | mssa-updater | MachineLaneSSAUpdater (gtest harness lives here) |
| `ssa-rebuilder` | ssa-rebuilder | AMDGPURebuildSSA refactoring |
| `scripts` | — | permanent tooling (corpus harness, gdbctl, corpus archives) |
| `ssa-spiller-docs` | — | design docs + NOTES + SHARED_CONTEXT |

## SSA Register Allocator — Current State

### Implemented
- Pass skeleton: `AMDGPUSSARegisterAllocator.{h,cpp}` (~485 LOC)
- Width classification: `std::set<unsigned, std::greater<unsigned>> ColoringOrder`
- PEO coloring: width-descending MDT pre-order walk, greedy smallest-free
- Tied operand handling via `MI.isRegTiedToUseOperand()`
- Physical live-in tracking
- PHI kill-tracking fix: `if (MI.isPHI()) continue;` — PHI source operands
  are live only to predecessor block boundaries (LiveIntervalCalc.cpp:175),
  not inside the PHI block. Kill tracking would double-free physregs shared
  with PHI results.
- SSA Destruction + Operand Rewrite (combined pass):
  - `lowerPHIs()`: worklist-based chain/cycle permutation decomposition
  - Three-tier cycle breaking: (1) scratch reg matching cycle width if
    occupancy preserved, (2) V_SWAP_B32 per subreg on GFX9+, (3) XOR triplet
  - Critical edge splitting on demand via `SplitCriticalEdge`
  - `rewriteOperands()`: vreg→physreg replacement with subreg composition
  - Precondition: SI control-flow pseudos must be lowered first
  - MaxHWLimit respects `amdgpu-num-vgpr` via `ST->getMaxNumVGPRs(MF)`
- Kill-before-def ordering in colorByWidth: uses freed before defs colored,
  allowing def to reuse dying source's physreg. PHI kills still skipped.
- Physical register tracking in coloring: physreg defs call markOccupied,
  physreg uses check liveAt per reg unit and free dead units.
- Spiller physreg pressure: LivePhysRP counter seeded from MBB->liveins(),
  per-instruction kills-before-defs. Pressure in 32-bit slots; wide physregs
  via getRegSplitParts. Reserved regs (EXEC etc.) filtered via isReserved.
  Key: VGPR_32 has 2 reg units but 1 pressure unit — use sizeInBits/32.
- `countSGPRSpillVGPRs()` (2026-06-11): pure frame-size accounting; `ceil(Σ
  objectSize(FI)/4 / WaveSize)` over distinct SGPRSpill FIs. Replaces old
  `lowerSGPRSpills()` which crashed by calling `getPhysRegBaseClass(virtual_reg)`
  pre-coloring. `VGPRLimit -= N` between Pass 1 and Pass 2. No physreg side
  effects in the spiller.
- MIR test pattern (2026-06-11): physical liveins in spiller tests replaced with
  `IMPLICIT_DEF` + `COPY` to avoid physreg-in-vreg assertion. Hand-maintained
  CHECK lines for `SI_VIRTUAL_SPILL_MARKER` placement. XFAIL for tests exercising
  unimplemented fallbacks (loop-filter not implemented).
- Partial subreg spill fix (2026-06-11): `getVMPsToSpill` "too-large" branch now uses
  `getRegSplitParts(SubRC, 4)` to take only the needed 32-bit parts. `SIInstrInfo::
  storeRegToStackSlot` SGPR path now passes `SubRegIdx` to `addReg` and guards
  `constrainRegClass` with `SubRegIdx == 0`. Wide vregs (e.g. `sreg_64`, `vreg_128`)
  now spill only the needed sub-slot; SSA repair inserts `REG_SEQUENCE` at restore.
  Tests added: `spill-sgpr-linear-basic.mir` (32-bit SGPR), `spill-sgpr-wide.mir`
  (64-bit SGPR, one writelane lane). Autogenerated tests regenerated.
- 61 PASS + 3 XFAIL across RA+Spiller suites (spill-loop-skip-def-inside.mir
  and spill-loop-reload-inside-fallback.mir XFAIL; one balanced-use-before XFAIL)
  — HISTORICAL. These suites are NOT a gate (user ruling 2026-08-29). Current state for
  triage only, measured 2026-08-29: 121 tests over SSARA + SSASpiller + MachineLaneSSAUpdater,
  102 pass / 19 fail, of which 10 exercise the abandoned standalone spiller pass, 4 are the
  unregistered `test-machine-lane-ssa-updater` harness pass, and 5 are genuine live-allocator
  `.mir` failures pre-dating 2026-08-29.
- End-to-end RA pipeline fully functional (coloring → SSA destruction → operand rewrite)
- RebuildSSA pass ported and registered (9 fixes applied)

### Pipeline Integration (COMPLETE, 2026-06-11)
- AMDGPURebuildSSA ported from PR #156049 into ssara worktree (9 bug fixes applied)
- `-amdgpu-ssa-regalloc` flag wired in `addRegAssignAndRewriteOptimized()`;
  replaces entire greedy SGPR/WWM/VGPR chain. **The pipeline as originally wired was
  RebuildSSA → SSA Spiller → SSA RA; that is STALE.** Verified 2026-08-29 against the source:
  the live pipeline at `AMDGPUTargetMachine.cpp:1720-1736` is RebuildSSA → PHISimplifier →
  SSARegisterAllocator → VerifyPhysRegLiveness. `createAMDGPUSSARegisterSpillerPass` is still
  defined (`AMDGPUSSARegisterSpiller.cpp:1416`) and declared (`AMDGPU.h:103`) but has NO CALL SITE
  anywhere in `llvm` — the standalone spiller pass is ABANDONED and reachable only via
  `-run-pass=amdgpu-ssa-register-spiller`. Spilling now happens inside the allocator.
- Pre-RA sequence unchanged (PHIElim + TwoAddress + RegCoalescer + RenameIndependentSubregs)
- RebuildSSA is temporary bridge: converts post-PHIElim non-SSA MIR back to SSA
- Three post-RA property fixes in AMDGPUSSARegisterAllocator (we skip VirtRegRewriter):
  - `finalizeProperties()`: sets NoPHIs + NoVRegs; preserves TracksLiveness
  - `eliminateRegSequences()`: lowers REG_SEQUENCE pseudos to COPYs or deletes trivial ones
- Smoke tests pass: basic-loop.ll, spill-cfg-position.ll, rewrite-vgpr-mfma-to-agpr-phi.ll

### Removed
- LR splitter removed 2026-05-26. Width-descending coloring already reuses freed slots.
- PHI false-interference fix loop removed 2026-06-05. PHI sources are live only
  to predecessor boundaries in LLVM's LiveIntervals — no false interference exists.

### Not Started
- SGPR lowering tests: one-by-one (CFG + liveness → approval → create → run). Priority
  for next session.
- VGPR spill lowering: `SIRegisterInfo::eliminateFrameIndex` handles `SI_SPILL_V*_SAVE/RESTORE`
  via PEI; requires physical regs (SSA RA delivers) + `ScratchRSrcReg` reserved by
  `SIFrameLowering` prologue. Mechanism identified; E2E smoke tests are the proof.
- ~~Full pipeline flag (`-amdgpu-ssa-regalloc`) wire-up and `.ll` smoke tests~~ — STALE, this
  contradicted the "Pipeline Integration (COMPLETE, 2026-06-11)" section above; struck 2026-08-29
- PHI coalescer (paper section 4.3) — still absent, and 2026-08-29 measured its cost directly:
  167 identity copies across 33 of 34 SSARA pipeline `.ll` tests, dominated by kernel-argument
  live-in copies that Greedy never shows because `RegisterCoalescer` runs first
- Spiller tied-operand RP fix

## Key Design Decisions

- **Width-descending coloring** solves mixed-width fragmentation
- **Splitter removed**: coloring already reuses freed slots at def points
- **No per-file separation**: SGPR/VGPR/AGPR reg units don't overlap
- **Tied operands**: inherit use's physreg via MI.isRegTiedToUseOperand()
- **SSA = one segment per vreg**: no LiveInterval segment iteration needed
- **Reg units for interference**: BitVector indexed by MCRegUnit handles all overlap cases
- **PHI sources live to predecessor boundary only**: LiveIntervalCalc extends PHI uses to getMBBEndIdx(PredMBB), not into the PHI block. No false interference — kill tracking skip is sufficient.
- **Scratch reg width-matched**: cycle-breaking scratch tuple matches the cycle's register width, not always 32-bit
- **MaxHWLimit from function attribute**: `ST->getMaxNumVGPRs(MF)` respects `amdgpu-num-vgpr`
- **DynVGPRBlockSize**: all occupancy queries use subtarget's dynamic VGPR block size

See [[SSARA/04-Design/SSA_RA_Coloring|SSA RA Coloring Design]] for coloring documentation.
See [[SSARA/05-Testing/SSA_RA/SSA_RA_TEST_PATTERNS|SSA RA Test Patterns]] for test documentation.

## Key APIs

- `SIRegisterInfo::getHWRegIndex(MCRegister)` = encoding & REG_IDX_MASK
- `AMDGPU::VGPR0 + idx` = contiguous VGPR_32 physreg enum
- `TRI->getMatchingSuperReg(BaseReg, AMDGPU::sub0, RC)` = tuple from base
- `GCNSubtarget::getOccupancyWithNumVGPRs(VGPRs, DynBlockSize)` = occupancy
- `GCNSubtarget::getMaxNumVGPRs(Occ, DynBlockSize)` = max VGPRs for occupancy
- gfx900: 256 VGPRs, granule=4, MaxWaves=10. Thresholds: ≤24→10w, 28→9w, 32→8w

## Build Configuration
- CMakePresets: upstream + shared CMakeUserPresets.json symlink
- Build preset: user-debug, dir: build/user-debug

## Tools & Docs
- md2pdf.py: `ssa-spiller-docs/SSARA/tools/md2pdf.py` (mermaid 9.4.3 + KaTeX + highlight.js;
  auto-discovers cursor-server node/chromium; `~~~` invisible-link syntax unsupported)
- publish_public.sh: INCLUDE_PATHS updated 2026-06-11 (SSA_Spiller → SSARA + SHARED_CONTEXT.md)
- Design doc: `ssa-spiller-docs/SSARA/04-Design/SSA_RA_Coloring.md`
  (Operand Rewrite + SSA Destruction marked ✅ 2026-06-11)
- Architecture.md rewritten 2026-06-11 with full pipeline diagram (SILowerSGPRSpills box)
- Worklog: `08-Worklog/NOTES.md` diary; `08-Worklog/BACKLOG.md` + `08-Worklog/FUTURE_IMPROVEMENTS.md`
  added 2026-06-11

## Future Optimizations

Design considerations identified but not yet implemented. Each entry notes
the component, the idea, and when it might become relevant.

- **[SPILLER] Threshold-guarded SGPR→VGPR lowering**: Instead of lowering all
  SGPR spills to VGPR lanes unconditionally, cap allocation so
  `VGPRLimit - SpillVGPRs >= Threshold`. Excess SGPR spills go to memory.
  Relevant when real programs show SGPR spill VGPRs starving VGPR budget.

- **[SPILLER] Per-program-point SGPR routing**: At each SGPR spill point,
  use local VGPR pressure (known from Pass 1 forward walk) to decide:
  VGPR-lane if slack exists, memory if tight. Hybrid lowering — some
  spills go to lanes, others to memory, per-instruction.

- **[SPILLER] Narrow spill-VGPR liveness**: Spill VGPRs are live only
  in [first_writelane, last_readlane], not the entire function. Integrate
  their liveness into LivePhysRP tracking in Pass 2's forward walk for
  tighter budget accounting (Phase 2 of lowerSGPRSpills).

## RebuildSSA → MachineLaneSSAUpdater refactor

### Phase 1: AMDGPURebuildSSA refactor — COMPLETE AND COMMITTED (2026-06-18)

**Bug fixed (Q1)**: inline RebuildSSA left partial wide defs (`undef %r.sub0:vreg_64`) for the
first subreg def, splitting only re-defs. Result: `%r` is a `vreg_64` carrying ONE live lane;
RA allocates the full tuple → register-pressure inflation → loop-coloring abort / v128 verifier
"undefined physical register".

**Implementation** (AMDGPURebuildSSA.cpp):
- Replaced ~250 lines of inline SSA repair (`buildRealPHI`, `splitNonPhiValue`, `rewriteUses`,
  `buildRSForSuperUse`, `extendAt`, `reachedByThisVNI`, `operandLaneMask`) with
  `MachineLaneSSAUpdater::repairSSAForNewDef`.
- Removed `MachineLoopInfo` dependency; replaced `MachineLoopInfo.h` with `MachineLaneSSAUpdater.h`.
- New `runOnMachineFunction` loop: find Root (earliest non-PHI VNInfo in dom-preorder), build
  WorkList of non-Root non-PHI VNInfos sorted dom-preorder + Root appended last, single loop
  calling `repairSSAForNewDef`. Root handled only if it has a subreg def operand (Q1 fix).
- LI reference scoped before the repair loop with comment: "repairSSAForNewDef replaces
  OrigVReg's interval object, invalidating any reference held across calls".
- `RenumberValues()` removed (updater recomputes via `removeInterval` +
  `createAndComputeVirtRegInterval`; `shrinkToUses` explicitly avoided for PHI-operand
  correctness). `MF.verify()` runs in debug builds.

**Validation**: previously XFAIL `pipeline-spill-loop.ll` and `pipeline-wide-v128.ll` both now
pass. Full SSARA suite 36/36; 78 tests total (36 SSARA + 42 SSASpiller), 0 unexpected failures.

### fixPathologicalPHIs dead-PHI bug — FIXED AND COMMITTED (2026-06-18)

**Context**: `fixPathologicalPHIs` in `AMDGPUSSARegisterSpiller.cpp` finds PHIs still
referencing spilled vregs and replaces them with `SI_SPILL_V32_RESTORE`. KillMI = the
`SI_VIRTUAL_SPILL_MARKER` placed at the end of bb.0 (entry). For a loop-invariant spilled
value, `repairSSAForNewDef` inserts a PHI at loop header (bb.1) but rewrites all dominated
uses directly to the closer reload def. The PHI result becomes unused.

**Bug**: `fixPathologicalPHIs` unconditionally replaced the unused PHI with
`SI_SPILL_V32_RESTORE` at the loop header's first non-PHI position. That restore was also
dead but consumed a VGPR slot, pushing the loop's live count over budget → `color()` abort.

**Fix** (~line 1205 in `AMDGPUSSARegisterSpiller.cpp`): before inserting restore, check
`MRI->use_nodbg_empty(PHIDest)`. If true, delete PHI silently (no restore inserted), continue.

### Loop spill analysis findings

- `getNumCoveredRegs(LaneBitmask)`: AMDGPU-specific, counts 32-bit VGPR slots. sub0
  mask=0x3 → 1 slot (lo16=bit0, hi16=bit1 of one VGPR_32). Full vreg_64 mask=0xF → 2 slots.
- `adjustReloadForLoop`: checks if reload can be hoisted to loop preheader. "Cannot hoist
  reload to preheader: RP exceeds limit on path" → in-loop reload. In-loop reload does NOT
  reduce loop peak pressure (the restore adds back the slot it freed).
- Greedy spills loop-invariant values BEFORE the loop (buffer_store before entry, buffer_load
  inside loop). Our spiller places the virtual kill point (SI_VIRTUAL_SPILL_MARKER) near the
  def in bb.0 but actual reload stays in-loop when preheader hoist fails.
- Loop-filter fallback (`getVMPsToSpill` ~line 623): still open — "pick best invalid candidate
  and use loop exit sinking".

### Phase status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Full E2E test batch | COMMITTED (2026-06-18, 05fcd64) |
| Phase 1 | RebuildSSA → MachineLaneSSAUpdater | COMPLETE AND COMMITTED (2026-06-18) |
| Phase 2 | Function-wide width-descending RA coloring | COMMITTED (2026-06-18, `1a21fd31d109`) — was stale as "NOT STARTED"; corrected 2026-08-25 against `git log` |

**Open work**: PHI coalescer, spiller tied-operand RP fix, loop-filter fallback (`getVMPsToSpill`
~line 623), reg-unit vs pressure-unit mismatch fix.

### Colleague-fix review campaign (2026-07-13, base HEAD b1f8539069e0, corpus CRASH 96)
- **Fix A (tied-def subreg color)**: `AMDGPUSSARegisterAllocator::color()` ~line 391 — a two-address
  def inheriting its tied use's color must inherit `TRI->getSubReg(color, UseSubIdx)` when the tied
  use reads a sub-register lane (V_WRITELANE_B32 / V_MOV_B32_dpp tied to one 32-bit lane of a wider
  value), not the whole super-register. Fixes the "Operand has incorrect register class" (10) cluster
  (7/8; permlane also needs Fix B = undef tied source). Reviewed: minimal + correct. APPLIED+built;
  cluster verify 7/8 pass.
- **Fix B (undef tied-def rewrite)**: `AMDGPUSSARegisterAllocator::rewriteOperands()` undef branch —
  an undef USE tied to a def (DPP/PERMLANE `undef %N.subX(tied-def)` old source) must be rewritten to
  the def's already-assigned physreg (`MO.setSubReg(0); MO.setReg(DefPhys)`), not an arbitrary
  `Order.front()`, else "Tied physical registers must match" / "Two-address operands must be
  identical". Fixes corpus class (1); with Fix A unblocks permlane. Reviewed: minimal + correct.
- **Fix C (spiller isSpill/isReload by TSFlag)**: `AMDGPUSSARegisterSpiller.cpp` `isSpillInstr`/
  `isReloadInstr` replaced hand-maintained S+V opcode lists (omitted AGPR/AV) with
  `SIInstrInfo::isSpill(MI->getDesc()) && mayStore()/mayLoad()`. On gfx90a+ an `SI_SPILL_AV*_RESTORE`
  reload was unrecognized → redef not renamed in SSA repair → vreg multi-defined → `getVRegDef`
  assert. TSFlag covers all files/widths. Fixes corpus class `getVRegDef assumes at most one
  definition`. Reviewed: correct + robustness improvement.
- **CORPUS A+B+C (2026-07-13, /tmp/corpus-abc-run, 3072 tests, ssara real-tree llc):** CRASH 96->86,
  0 PASS->fail regressions. Classes eliminated: incorrect-register-class 10->0 (A), tied-physregs 1->0
  (B), getVRegDef-multi-def 1->0 (C); bonus Multiple-vreg-defs 5->2 (C). Residual advanced into the
  postponed coalescer-lack class "Failed to find free physreg" 32->36. Top remaining crash class = (36)
  Failed to find free physreg = COALESCER-LACK (postpone; e.g. bitcast diamond, see report-D). Plan:
  green all non-coalescer classes, then build coalescer on a green tree.
- **Colleague-fix review campaign (2026-07-13): COMMITTED, CRASH 96 -> 59, 0 PASS->fail regressions.**
  7 fixes committed to `ssara` (each with a revert-proven SSARA guard test; corpus-gated per fix):
    * b312be01daa9 A - SSA RA inherit sub-register of tied use's color (ra-tied-use-subreg-color.ll)
    * 00bd2589097c B - SSA RA rewrite undef tied use to tied def physreg (ra-undef-tied-def-rewrite.ll)
    * 7d93452def3f F - SSA RA rewrite operands inside BUNDLEs (ra-bundle-operand-rewrite.ll)
    * 0521322a38e8 C - spiller classify spill/reload by Spill TSFlag (spill-av-reload-ssa-repair.ll)
    * 5c027bd3b1e4 D - spiller clear per-function stack-slot maps (spill-cross-function-stackslot.ll)
    * 733b6066a85e E - spiller ignore undef uses in physreg RP + getLiveRegs hasInterval-before-
      getRegKind (spill-undef-physreg-pressure.ll + spill-classless-vreg-liveregs.ll)
    * 9fef2ffac407 G - MachineLaneSSAUpdater share super-use REG_SEQUENCE per instruction, keyed
      {UseMI,OpMask}, session-scoped (rebuildssa-superuse-shared-regseq.ll)
  Class-by-class eliminated: incorrect-reg-class 10->0, tied-physregs 1->0, getVRegDef 1->0,
  Invalid-Object-Idx 9->0, Register-class-not-set 6->0, Remaining-virtual-register(GWS) 6->0,
  VOP-constant-bus 6->0, v_div_scale 4->0; Multiple-vreg-defs 5->2 (bonus from C).
  Campaign tally: 96(dead-def) -> 86(A+B+C) -> 81(D) -> 75(E) -> 69(F) -> 59(G). SSARA lit 65/65.
- **UPSTREAM (llvm-project worktree, 2026-07-13):** (1) branch `GCNRPTracker_fix` = the getLiveRegs
  hasInterval-before-getRegKind reorder ported to upstream GCNRegPressure.cpp (same bug exists in
  main); `ninja -C build/Debug check-llvm` = 46096 passed, only the 4 pre-existing MCJIT-EH failures
  (baseline match), 0 new regressions. (2) branch `fix-splitcriticaledge-subrange-vninfo` =
  MachineBasicBlock.cpp SplitCriticalEdge comment simplified per reviewer (perlfu): 4-line comment ->
  "// New segment VNI must be from the subrange.".
- **REMAINING crash classes @ CRASH 59 (postponed/deferred):** (37) Failed to find free physreg =
  COALESCER-LACK (full categorized list in /tmp/ssara-reports/failed-to-find-free-physreg-crashes.md:
  9 wide-bitcast diamonds, 10 AGPR/AV+MFMA, 9 spill-heavy/scavenge, 4 WWM, 5 other; see report-D for
  the diamond root cause). Non-coalescer remainders needing dedicated per-class work: undefined physreg
  (3: $scc-after-spill x2 + call-physreg x1), Multiple-vreg-defs (2: INLINEASM AV_32 subreg outputs -
  RebuildSSA detects 2 VNs, renames def op, but 2 defs persist), MachineCopyPropagation (2),
  containsInterval (2), + singletons. Plan: green all non-coalescer classes, then build coalescer.
  Colleague fix reports live in /tmp/ssara-reports/ (report-A..D + failed-to-find-free-physreg).
- **Fix D (spiller cross-function state leak, Invalid Object Idx)** [applied 2026-07-13]:
  `AMDGPUSSARegisterSpiller::runOnMachineFunction` now clears `Virt2StackSlotMap` and
  `StoredAtDefinition` per function. They are keyed by `VRegMaskPair` (per-function vreg numbers) but
  were never cleared, so a colliding {vreg,mask} in a later function returned a stale frame index
  (out of range for that function's FrameInfo -> getObjectAlign "Invalid Object Idx") and a dangling
  store MI. Fixes corpus class (9). Verified across all 9 repros.

## User Preferences
- No source changes without APPROVED: line
- User commits manually (no AI commits, no trailers)
  - **CONFLICT RESOLVED (user ruling, 2026-08-25/26) — was left marked OPEN here until
    2026-08-29.** AI commits are PROHIBITED because this workspace is potentially public;
    the preference stands from 2026-08-25 onwards and the agent prepares and stages only.
    The pre-existing `Co-Authored-By: Claude` trailers on `weekend/prespill-widthaware`
    (including `5fde0ed1dd8d` and `f3869a20da99`) need no stripping, because the branch will
    be SQUASHED to a single commit before porting to the public tree. Confirmed in practice
    on 2026-08-29: `bc355db5e45a` was created by the user, not the agent.
- Patches shown as unified diffs
- Never update tests to match output — tests define expected behavior
- Always verify user claims independently
- Minimal code, no over-engineering
