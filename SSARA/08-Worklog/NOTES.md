# SSA Register Allocator — Worklog

---

## 2026-05 — Coloring Phase

- Implemented width-descending multi-pass PEO coloring in `AMDGPUSSARegisterAllocator.{h,cpp}`
- Pass skeleton: classifyVRegs, colorByWidth, seedOccupiedAtBBEntry, pickFreePhysReg
- Interference tracked via `BitVector OccupiedRegUnits` indexed by MCRegUnit
- Tied operands handled via `MI.isRegTiedToUseOperand()`
- Physical live-ins tracked in seedOccupiedAtBBEntry
- 5 coloring LIT tests created (color-*.mir)

---

## 2026-05-26 — Splitter Removal + Documentation

- Implemented LR splitter (ShadowMap, planSplit, commitPlan, gap-filling, recoloring)
- Discovered width-descending coloring already reuses freed slots at def points, making splitter redundant
- Removed ~330 lines of splitter infrastructure, no test regressions
- 7 split-*.mir tests kept (verify coloring behavior)
- Renamed docs folder: `SSA_Spiller/` → `SSARA/`
- Created coloring design doc: `04-Design/SSA_RA_Coloring.md`
- Updated concept docs: Chordal_Graphs.md (strengthened SSA chordality claim), PEO.md (added dominance tree PEO subsection)
- Updated README.md, SHARED_CONTEXT.md, pipeline docs

---

## 2026-06-01 — SSA Destruction Design

- Designed combined SSA destruction + operand rewrite pass
- Key decisions: single pass (not separate MachineFunctionPasses), three-tier cycle breaking, precondition guard for SI pseudos
- Code review identified 15 issues in initial patch:
  - SrcRefCount ref-counting (not DenseSet) for fan-out correctness
  - Critical edge: proper check + SplitCriticalEdge, not assert
  - MaxIdx recorded during coloring, not recomputed
  - Scratch saves CycleStart itself, not DstToSrc[CycleStart]
  - Occupancy check == not >=
  - No magic constants (use subtarget APIs)
  - DynVGPRBlockSize from subtarget
  - getRegSplitParts instead of hardcoded subreg array
  - IsVGPR from PHI result RC, not ColorMap scan
  - DenseMap::erase() returns void — worklist pattern
  - Removed setIsRenamable
  - V_SWAP_B32 is GFX9+ (ST->hasSwap())

---

## 2026-06-03 to 2026-06-04 — SSA Destruction Implementation

- Applied SSA destruction + operand rewrite patch (~300 new LOC)
- Added PHI false-interference fix (freeing PHI sources before coloring PHI defs)
- Discovered PHI kill-tracking collision bug: kill tracking frees physregs shared between PHI sources and just-colored PHI results

---

## 2026-06-05 — PHI Liveness Discovery + Bug Fixes + Testing

- **Key finding**: PHI source operands extend to `getMBBEndIdx(PredMBB)` in LLVM's LiveIntervals (LiveIntervalCalc.cpp:175). They are NOT live inside the PHI block at all. This means:
  - seedOccupiedAtBBEntry never marks PHI sources as occupied
  - No false interference exists — the PHI fix loop was unnecessary, removed
  - The only fix needed: `if (MI.isPHI()) continue;` before kill tracking
- Fixed scratch register width bug: scratch must match cycle's register width, use `getMatchingSuperReg` for wide tuples, increment MaxIdx by CycleWidth
- Fixed emitSwap infinite recursion: base case checks `getRegSizeInBits(*RC) <= 32` instead of `Parts.empty()`
- Changed MaxHWLimit to `ST->getMaxNumVGPRs(MF)` to respect `amdgpu-num-vgpr` attribute
- Created 5 SSA destruction tests:
  - destruct-simple-copy: COPY on one edge, identity on other
  - destruct-identity: all identities, no copies
  - destruct-swap: 32-bit cycle via scratch
  - destruct-rewrite: straight-line operand rewrite
  - destruct-wide-swap: 128-bit swap, two RUN lines (gfx900→V_SWAP_B32, fiji→XOR)
- All 17 tests passing
- Created test documentation: `05-Testing/SSA_RA/SSA_RA_TEST_PATTERNS.md`

---

## 2026-06-08 — Kill Ordering Fix + Loop/Chain/Cycle Tests

- **[BUG] Def-before-kill ordering prevents register reuse at last use**
  In `colorByWidth()`, defs were colored BEFORE uses were killed. A def could
  not reuse the physreg of a source dying at the same instruction, even though
  their live ranges don't overlap (without early-clobber). This produced
  spurious COPYs on loop back edges.
  Fix: move kill tracking before def processing. PHI kill tracking still
  skipped (sources live to predecessor boundary only; markFree would clear
  physregs claimed by preceding PHI defs).

- Created 5 new loop/permutation tests:
  - destruct-loop-reuse: kills-before-defs reuse, no copy
  - destruct-loop: %x alive past V_ADD, genuine copy
  - destruct-chain: 3 PHIs, chain of length 3 (worklist tail-to-head)
  - destruct-cycle3: 3 PHIs, cycle of length 3 (scratch Tier 1)
  - destruct-mixed: chain + cycle on same edge (Phase 1 + Phase 2)

- Added ASCII CFG, liveness, and coloring schemes to all destruction tests

- **End-to-end RA pipeline now fully functional**: coloring → SSA destruction
  → operand rewrite. 21 tests passing. Not optimized (PHI coalescer missing).

---

## 2026-06-08 — Pipeline Integration: RebuildSSA Port [FEATURE] [SSARA]

- **Context / goal**
  - Integrate full SSA RA pipeline: RebuildSSA → SSA Spiller → SSA Register Allocator
  - Port AMDGPURebuildSSA pass from PR #156049 (alex-t/ssa-ra-stack-wip) into ssara worktree
  - Plan pipeline hookup via `-amdgpu-ssa-regalloc` flag in `addRegAssignAndRewriteOptimized()`

- **Decisions**
  - Stay in `ssara` worktree (all components already here; separate worktree unnecessary)
  - Pipeline insertion point: `GCNPassConfig::addRegAssignAndRewriteOptimized()` — replaces
    entire SGPR/WWM/VGPR greedy path when flag enabled
  - Pre-RA sequence unchanged (PHIElim + TwoAddress + RegCoalescer + RenameIndependentSubregs
    + MachineScheduler all run first, producing non-SSA MIR)
  - RebuildSSA acceptance: test-as-you-go, no upfront unit tests (pass is temporary).
    Safety nets: MF.verify() in debug builds + end-to-end `.ll` smoke tests

- **RebuildSSA port: 9 fixes applied**
  1. Dropped `AMDGPUSSARAUtils.h` dep — use `TRI->getSubRegIndexForLaneMask()` from base class
  2. Removed unused `#include <algorithm>`, `<stack>`, `LiveVariables.h`
  3. Removed unused `#include "VRegMaskPair.h"`
  4. Removed unused `PassBuilder.h`, `PassPlugin.h`, `GenericIteratedDominanceFrontier.h`,
     `MachineSSAUpdater.h`, `Passes.h`
  5. Removed unused `RegSeqences` member
  6. **Fixed static DomKey map bug**: `static DenseMap<MBB*,unsigned>` inside lambda never
     cleared between vregs/functions. Pre-compute `DomPreorder` once per `runOnMachineFunction`
  7. **Guarded `MF.verify()`** under `LLVM_DEBUG` — was unconditional (release perf hit)
  8. **Removed broken NPM wrapper** — stack-constructed legacy pass, `getAnalysis<>()` crash
  9. **Removed PassPlugin boilerplate** — `llvmGetPassPluginInfo()` not needed in-tree

- **Build result**: zero warnings, llc links (113 targets, 146s)

- **End-to-end test candidates** (`.ll` files through full pipeline):
  - `basic-loop.ll` (18 lines, loop+PHI) — sanity baseline
  - `spill-cfg-position.ll` (78 lines, diamond+PHI) — add `amdgpu-num-vgpr` for spilling
  - `rewrite-vgpr-mfma-to-agpr-phi.ll` (179 lines, diamond+loop, `waves-per-eu`)

- **Next actions**
  - Add `cl::opt -amdgpu-ssa-regalloc` flag
  - Hook up pipeline in `addRegAssignAndRewriteOptimized()`
  - Run end-to-end smoke tests starting with `basic-loop.ll`

---

## 2026-06-09 to 2026-06-10 — Physical Register Pressure Tracking

- **[FEATURE] RA physreg tracking** in `colorByWidth()`:
  - Physreg uses: check `LIS->getRegUnit(Unit).liveAt(NextSI)` per reg unit, free dead units
  - Physreg defs: `markOccupied(Reg)`
  - Same instruction loop as vregs (not separate passes)
  - 2 tests: `physreg-livein-dies`, `physreg-def-midblock`

- **[FEATURE] Spiller physreg pressure** in `processFunction()`:
  - `LivePhysRP` counter seeded from `MBB->liveins()`, updated per-instruction
  - Pressure counted in 32-bit slots; wide physregs decomposed via `getRegSplitParts`
  - Added to `CurRP` before spill decisions
  - 3 tests: `spill-physreg-pressure`, `spill-physreg-dies`, `spill-physreg-def-midblock`

- **[BUG] VGPR_32 has 2 reg units (lo16, hi16) but 1 pressure unit**
  Root cause proven via debug logs. Seed uses `getRegSizeInBits/32 = 1`,
  kill tracking was iterating per reg unit (2 decrements). Fixed: operate
  at operand level with per-32-bit-sub-slot liveness for wide regs.

- **[BUG] Reserved registers (EXEC, M0, FLAT_SCR) have valid SGPR RC but no LiveRange**
  `getPhysRegBaseClass(EXEC_LO)` returns SReg_32, `isSGPRClass` = true.
  But LiveIntervals has no data for reserved units. Fixed: filter with
  `MRI->isReserved(Reg)` before querying liveAt().

- **[DISCOVERY] Special register handling in AMDGPU RA**
  - EXEC/M0/FLAT_SCR: reserved via `getReservedRegs`
  - VCC/SCC: non-allocatable via TableGen
  - Kernel arg SGPRs + work-item VGPRs: protected as live-ins from ISel
  - GCNRegPressure counts only virtual registers
  - All handled by `RegisterClassInfo::getOrder()` which our RA uses

- **25 RA tests + 3 spiller physreg tests passing** (ONLY these were run —
  the full SSASpiller/ suite was NOT verified)

---

## 2026-06-10 — Physreg Pressure Tracking: 24 Test Failures Discovered [BUGFIX] [SPILLER]

- **Context / goal**
  - While implementing `lowerSGPRSpills()`, ran full SSASpiller/ test suite
    for the first time after physreg pressure commit (`00b3709779e8`).
  - Discovered 24 out of 35 SSASpiller tests failing (23 crashes + 1 CHECK mismatch).

- **Bug 1: CRASH in getRegSplitParts on non-standard register classes**
  - `processFunction()` line 327: `TRI->getRegSplitParts(RC, DWordBytes)` called
    on register classes that `getRegBitWidth()` doesn't handle (SReg_1_XEXEC,
    SReg_LO16, or other non-allocatable RC that passes `isSGPRClass` filter).
  - Triggers `UNREACHABLE "Unexpected register class"` at AMDGPUBaseInfo.cpp:2925.
  - Affects any test with physreg operands wider than 32 bits in non-standard RC.
  - Only the 3 hand-crafted physreg tests (VGPR_32, Width=1) avoid the `else` branch.

- **Bug 2: Live-in physreg over-counting causes spurious spills**
  - `spill-linear-dominated.mir`: live-in `$vgpr0_vgpr1_vgpr2_vgpr3` adds 4 to
    `LivePhysRP` at block entry. The COPY that kills this physreg is the first
    instruction. At that instruction, `CurRP = vreg_RP + LivePhysRP` includes BOTH
    the physreg (not yet killed) AND the vreg defined by the COPY.
  - This double-counts: the physreg and its COPY destination are the same value,
    alive at the same time only instantaneously. The kills-before-defs ordering
    should handle this but doesn't for block live-in physregs at the first instruction.
  - Result: false pressure spike → spurious store-at-def of `%0` in bb.0.

- **Root cause of missed detection**
  - Only 3 new physreg tests were run after the commit. The existing 35 SSASpiller
    tests were never re-run. Rule added: always run full component test suite.

- **Fix applied**: Added `!RC->isAllocatable()` to physreg filter (line 314).
  Non-allocatable regs (SCC, VCC, MODE) now correctly excluded.
  Resolved 19 of 24 crashes.

- **Remaining 5 failures after fix**:
  - 3 CHECK mismatches (`spill-linear-dominated`, `spill-dominated-branches`,
    `spill-multi-predecessor-join`): physreg live-ins now correctly counted
    in pressure → spill triggers at earlier program point. Tests need updating.
  - 2 `validateFinalRP` fatals (`spill-loop-reload-inside-fallback`,
    `spill-loop-skip-def-inside`): spiller cannot keep RP within limits when
    physregs are counted. Pre-existing spiller deficiency exposed by tighter budget.
    Known TODO: loop-aware candidate filtering fallback not implemented.

---

## 2026-06-10 — Re-analysis: bisect first-bad `4794a5f9910b` [DESIGN] [SPILLER]

- **Context / goal**
  - Bisect previously flagged `4794a5f9910b` (“partial unused code cleanup”) as first bad for `spill-loop-skip-def-inside.mir` / `validateFinalRP`.
- **What that commit actually removes**
  - Only `splitBlockBeforeReload()` (~170 lines) and `handleReachableUse()` plus matching declarations in `AMDGPUSSARegisterSpiller.h`. No other files.
- **Results / discoveries**
  - At `4794a5f9910b^` (= `3bfb42ab59ef`), the **only** call site is already `// handleReachableUse(KillMI, ReloadMI, SpilledVMP);` (commented out). Same at `4794a5f9910b`. The removed bodies were **dead code** from the compiler’s perspective — no live call graph edge.
  - The MIR test file is **identical** between `3bfb42ab59ef` and `4794a5f9910b`.
  - **Conclusion:** This commit **cannot** explain a pass→fail flip by itself. A bisect that lands here likely reflects **stale `llc` during bisect** (lit run without rebuild after checkout) or **mis-tagged good/bad**, not a semantic regression in the deleted paths.
- **Actual failure mechanism (unchanged)**
  - Loop-aware filtering can leave **no spill candidates**; spiller then cannot lower VGPR pressure → `validateFinalRegisterPressure` fails. Fixing that requires algorithm work (fallback / sinking / cost model), not restoring the deleted split-before-reload stubs unless the team **uncomments** and wires `handleReachableUse()` again.
- **Next actions**
  - After bisect: `git bisect reset`; always **rebuild `bin/llc`** (or the spiller `.o` + link) before each bisect step.
  - Re-run bisect with a script that `ninja bin/llc` then `llvm-lit` single test if seeking a true first-bad for behavior.
- **Empirical check (2026-06-10):** Rebuilt `bin/llc` at `3bfb42ab59ef` (commit that added `spill-loop-skip-def-inside.mir` / `spill-loop-reload-inside-fallback.mir`). Both tests still fail with **`validateFinalRegisterPressure` abort** — same as today. **They never passed** on the branch as soon as they landed; nothing “broke” them afterward in the bisect sense.

## 2026-06-11 — lowerSGPRSpills crashes on virtual SGPRs [BUG] [SPILLER] [BLOCKER]

- **Context / goal**
  - Designing first spill/reload lowering test (single 32-bit SGPR spill → VGPR lane).
  - Built scratch MIR (gfx1200, `amdgpu-num-sgpr=8` → SGPR limit 5), tuned pressure so Pass 1 spills exactly one longest-NUD SGPR. Internal pressure dropped 6→0/1, one spill selected. Good.
- **Blocker (reproduced)**
  - `llc … -run-pass=amdgpu-ssa-register-spiller` **aborts**:
    `Assertion 'Reg < ArrayRef(Mapping).size()' failed` in
    `AMDGPUGenRegisterInfo::getPhysRegBaseClass(MCRegister)`.
  - Call path: `lowerSGPRSpills()` → `TRI->eliminateSGPRToVGPRSpillFrameIndex()` → `SGPRSpillBuilder` ctor (`SIRegisterInfo.cpp:131`) → `getPhysRegBaseClass(SuperReg)`.
  - `SuperReg = MI.getOperand(0).getReg()` of `SI_SPILL_S32_SAVE` is a **VIRTUAL** SGPR in the SSA spiller (pre-coloring). `getPhysRegBaseClass` is **physreg-only** → virtual index out of mapping → assert.
- **Root cause**
  - `lowerSGPRSpills()` is essentially a copy of `SILowerSGPRSpills.cpp` (lines ~443–484). In the **stock** pipeline `SILowerSGPRSpills` lowers **physical** SGPR spills (CSR / post-alloc), so `getPhysRegBaseClass` is valid.
  - In the SSA RA pipeline the order is **RebuildSSA → SSA Spiller → SSA Register Allocator (coloring)**. The spiller runs **before** coloring, so spill pseudos carry **virtual** SGPRs. Reusing `SGPRSpillBuilder` (physreg API) is therefore invalid here.
  - This contradicts the earlier design note ("wire `lowerSGPRSpills()` between Pass 1 (SGPR) and Pass 2 (VGPR)") — that placement collides with the physreg-only lowering API.
- **Impact**
  - **All** SGPR-lane lowering tests (single / wide / packing / budget / IMPLICIT_DEF dominance) hit this same crash. No SGPR-lowering test can pass until resolved. Existing `spill-two-pass-sgpr-vgpr.mir` deliberately avoids SGPR spilling, so this was never exercised.
- **Options (need decision; any fix = source change → approval)**
  1. **Reorder**: run SGPR→VGPR lane materialization **after** SGPR coloring (physregs exist), reuse `SGPRSpillBuilder`. Spiller stays virtual; lowering moves later.
  2. **Virtual-aware lowering**: replace `eliminateSGPRToVGPRSpillFrameIndex` path with a virtual-reg path — derive RC via `MRI->getRegClass(VReg)` (not `getPhysRegBaseClass`), emit `V_WRITELANE_B32`/`V_READLANE_B32` per 32-bit subreg directly on the virtual SGPR.
  3. **Defer**: guard/`XFAIL` SGPR lowering; only test the VGPR spill-pseudo path for now.
- **Status**: investigation done; awaiting direction. No source changed; scratch files removed.

## 2026-06-11 — SGPR spill lowering redesign: accounting split + PEI delegation [DESIGN] [SPILLER] [RA]

### Problem recap
`lowerSGPRSpills()` — copied from `SILowerSGPRSpills.cpp` — called `eliminateSGPRToVGPRSpillFrameIndex()` → `SGPRSpillBuilder::ctor` → `getPhysRegBaseClass(SuperReg)` on a **virtual** SGPR (pre-coloring). Crash: `Assertion 'Reg < ArrayRef(Mapping).size()' failed`.

### Design decisions (session 2026-06-11)

**Decision 1 — Split accounting from materialization**

The spiller's only job is to set the right VGPR budget for Pass 2. Physical lane reservation and `writelane`/`readlane` materialization need physical SGPRs (post-coloring). Therefore:

- **Spiller (pre-coloring):** accounting only — count how many lane VGPRs SGPR spills will consume; `VGPRLimit -= count`. No `eliminate`, no physreg reservation, no `IMPLICIT_DEF`. Pseudos remain.
- **Post-coloring:** materialization delegated to the existing `SILowerSGPRSpills` pass.

**Decision 2 — Pure frame-size math for counting**

`ceil(Σ objectSize(FI)/4 / WaveSize)` over distinct `SGPRSpill` frame indices — derived from `MachineFrameInfo` only. No `SuperReg`, no `getPhysRegBaseClass`, no side effects. (Same formula `allocateSGPRSpillToVGPRLane` uses internally.)

**Decision 3 — Delegate final lowering to `SILowerSGPRSpills` (existing pass), not a new Phase 2**

Pipeline evidence from `addRegAssignAndRewriteOptimized()`:
```
createSGPRAllocPass → VirtRegRewriter → StackSlotColoring
→ SILowerSGPRSpills  ← lowers physical SGPR pseudos → VGPR lanes, grabs top-of-file VGPRs
→ createVGPRAllocPass
```
This is exactly the right shape. After SSA RA coloring+rewrite, `SuperReg` is physical → no crash; `findUnusedRegister(SearchFromTop=true)` naturally finds free VGPRs above `MaxVGPRIdx` — no pre-reservation needed.

**Decision 4 — No pre-reservation in the SSA RA**

Considered and rejected: reserving top-N VGPRs before coloring breaks `MaxVGPRIdx` (reserved reg-units marked occupied but never written to high-water mark → occupancy wrong) and creates a circular dependency (which physregs to reserve depends on coloring result). Instead: SSA RA colors bottom-up; top of file is naturally free for `SILowerSGPRSpills`.

**Decision 5 — `SILowerSGPRSpills` LIS-optional, no recompute needed**

`SILowerSGPRSpillsLegacy::runOnMachineFunction` uses `getAnalysisIfAvailable<LiveIntervalsWrapperPass>()` — LIS is optional. After SSA RA calls `leaveSSA()`/`invalidateLiveness()`, LIS is gone; `SILowerSGPRSpills` operates without it (no crash, no need to recompute).

### Architecture (final)
```
SSA Spiller  →  countSGPRSpillVGPRs()  →  VGPRLimit -= N  →  Pass 2 VGPR
     (SGPR+VGPR spill pseudos remain, all vregs virtual)

SSA RA  (unchanged — unified width-descending coloring, bottom-up)
     destroySSAAndRewrite → leaveSSA → invalidateLiveness
     (SGPRs+VGPRs physical; SGPR spill pseudos: SI_SPILL_S*_SAVE/RESTORE with physical SuperReg)

SILowerSGPRSpills  (existing pass, untouched)
     → SI_SPILL_S32_TO_VGPR / SI_RESTORE_S32_FROM_VGPR
     → IMPLICIT_DEF for lane VGPR, WWM reservation
     (LIS = nullptr, works fine)
```

Pipeline CLI: `-run-pass=amdgpu-ssa-register-spiller,amdgpu-ssa-register-allocator,si-lower-sgpr-spills`

### Verified end-to-end (2026-06-11, gfx1200, `amdgpu-num-sgpr=8`)

**Input** (virtual SGPRs, no spills):
```mir
bb.0: %s_far = S_MOV_B32 200
bb.1: %s0–%s4 = S_MOV_B32 1–5; S_NOP
bb.2: %s_res = S_ADD_I32 %s_far, %s_far; S_ENDPGM
```
**After Spiller + SSA RA** (physregs, spill pseudo with physical `$sgpr0`):
```mir
bb.0: $sgpr0 = S_MOV_B32 200; SI_SPILL_S32_SAVE $sgpr0, %stack.0
bb.1: $sgpr0–$sgpr4 = S_MOV_B32 1–5; S_NOP
bb.2: $sgpr0 = SI_SPILL_S32_RESTORE %stack.0; $sgpr0 = S_ADD_I32; S_ENDPGM
```
**After SILowerSGPRSpills** (writelane/readlane, no crash):
```mir
bb.0: $sgpr0 = S_MOV_B32 200; %8:vgpr_32 = IMPLICIT_DEF; %8 = SI_SPILL_S32_TO_VGPR $sgpr0, 0, %8
bb.1: $sgpr0–$sgpr4 = S_MOV_B32 1–5; S_NOP
bb.2: $sgpr0 = SI_RESTORE_S32_FROM_VGPR %8, 0; $sgpr0 = S_ADD_I32; S_ENDPGM
```

### Source changes applied (`ssara` branch, 2026-06-11)
- **`AMDGPUSSARegisterSpiller.h`**: `lowerSGPRSpills()` → `countSGPRSpillVGPRs()` (declaration + docstring).
- **`AMDGPUSSARegisterSpiller.cpp`**: replaced ~85-line `lowerSGPRSpills` body (allocate + eliminate + IMPLICIT_DEF + removeDeadFrameIndices) with 30-line `countSGPRSpillVGPRs` (frame-size math, no side effects). Call site updated + underflow `assert`. Build: clean. Full suite: 56 pass / 3 XFAIL (no regressions).

### Remaining pipeline wiring (not yet done)
When `-amdgpu-ssa-regalloc` flag lands in `addRegAssignAndRewriteOptimized`, the SSA RA path needs `si-lower-sgpr-spills` inserted immediately after `amdgpu-ssa-register-allocator`, mirroring the stock path. No allocator restructuring needed.

## 2026-06-10 — Worklog index: backlog + future ideas [DESIGN]

- Added `08-Worklog/BACKLOG.md` (failing tests, spiller/RA TODOs from NOTES, `SHARED_CONTEXT`, `AGENTS`, in-code FIXME/TODO scan).
- Added `08-Worklog/FUTURE_IMPROVEMENTS.md` (threshold SGPR lowering, per-site routing, narrow spill-VGPR liveness, bisect script, PHI coalescer, etc.).

## Pending

- **Pipeline wiring** — `-amdgpu-ssa-regalloc` in `addRegAssignAndRewriteOptimized()`:
  chain `SSA Spiller → SSA RA → SILowerSGPRSpills`. Architecture validated with `-run-pass`
  chain on gfx1200; ready to wire.
- **SGPR-lane lowering tests** — now unblocked (pipeline proven). Design one-by-one
  per project rules; start with single 32-bit linear case.
- **PHI coalescer** (paper §4.3) — reduce copies by recoloring PHI operands.
- **Spiller tied-operand RP** fix.
- **Loop-filter fallback** — `getVMPsToSpill` TODO ~632: when filter empties, sink to loop exit or pick invalid candidate.
