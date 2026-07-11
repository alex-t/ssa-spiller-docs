 topic on Discourse# SSA Register Allocator — Worklog

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

## 2026-06-11 — Partial subreg spill fix + SGPR lowering tests #1 & #2 [BUGFIX] [SPILLER]

### Bug: wide vreg over-spill when only 1 pressure slot needed

- **Root cause chain:**
  1. `getVMPsToSpill` enters the "too large" branch (candidate size > remaining slots).
  2. Calls `getSortedSubregUses` — but NUA records only actual use-site lane masks.
     For a `sreg_64` used as a whole (`S_AND_B64`), all records carry mask `0x0F` (full).
     So `getSortedSubregUses` returns `[{%w, 0x0F}]` — the whole register — and size 2 > remaining 1 → falls to `else` and spills the full register.
  3. Even when the correct sub0 VMP `(%w, 0x03)` was selected, `SIInstrInfo::storeRegToStackSlot` ignored `SubRegIdx` in the SGPR path (line 1702 emitted `addReg(SrcReg)` without subreg), so `SI_SPILL_S64_SAVE %w` was emitted regardless.

- **Fix 1 — `AMDGPUSSARegisterSpiller.cpp` `getVMPsToSpill` (else branch):**
  Replace the "spill the whole subreg" fallback with `getRegSplitParts(SubRC, 4)` decomposition.
  Take the first N 32-bit parts to satisfy `RemainingToSpill`.
  For `sreg_64` with remaining=1: emits `{%w, 0x03}` (sub0 only).

- **Fix 2 — `SIInstrInfo.cpp` `storeRegToStackSlot` SGPR path:**
  - Guard `constrainRegClass` with `SubRegIdx == 0` (parent reg is still wide; constraining it to sreg_32 was wrong for partial spills).
  - Change `addReg(SrcReg, kill)` → `addReg(SrcReg, kill, SubRegIdx)` so `SI_SPILL_S32_SAVE %w.sub0` is emitted when SubRegIdx is non-zero.
  - Note: `loadRegFromStackSlot` already honoured SubRegIdx correctly (lines 1901–1905).

- **End result for `%w:sreg_64`, remaining=1 (gfx1200, num-sgpr=10, limit=7):**
  - Spiller emits `SI_SPILL_S32_SAVE %w.sub0` — only sub0 stored, sub1 stays live.
  - SSA repair inserts `REG_SEQUENCE sub0_reload + %w.sub1` at restore site.
  - After RA: `SI_SPILL_S32_SAVE $sgpr0` + restore + `REG_SEQUENCE $sgpr2_$sgpr3 = [$sgpr2:sub0, $sgpr1:sub1]`.
  - After SILowerSGPRSpills: **one** `SI_SPILL_S32_TO_VGPR $sgpr0, lane=0` (not two).

### SGPR lowering tests added

- **`spill-sgpr-linear-basic.mir`** — test #1 (linear CFG, 32-bit SGPR): 3-stage pipeline checks
  (`AFTER-SPILL` / `AFTER-RA` / `AFTER-LOWER`). Passes.
- **`spill-sgpr-wide.mir`** — test #2 (linear CFG, 64-bit SGPR, partial subreg spill):
  asserts `SI_SPILL_S32_SAVE %w.sub0`, single writelane lane 0, `REG_SEQUENCE` on restore. Passes.

### Tests updated by partial subreg fix

- `spill-linear-dominated.mir`, `spill-dominated-branches.mir`, `spill-multi-predecessor-join.mir`:
  marker mask `0x03` (sub0 only), `SI_SPILL_V32_SAVE/RESTORE`, + `REG_SEQUENCE`.
- `spill-multi-path-independent.mir`, `spill-use-before-spill.mir`, `spill-vreg-subregister.mir`:
  autogenerated CHECKs regenerated via `update_mir_test_checks.py`.

### Suite result
**61 tests: 58 PASS, 3 XFAIL** — no regressions.
Binary confirmed newer than both changed source files (`SIInstrInfo.cpp` 17:18, `llc` 17:21).

## 2026-06-10 — Worklog index: backlog + future ideas [DESIGN]

- Added `08-Worklog/BACKLOG.md` (failing tests, spiller/RA TODOs from NOTES, `SHARED_CONTEXT`, `AGENTS`, in-code FIXME/TODO scan).
- Added `08-Worklog/FUTURE_IMPROVEMENTS.md` (threshold SGPR lowering, per-site routing, narrow spill-VGPR liveness, bisect script, PHI coalescer, etc.).

---

## 2026-06-11 — Full Pipeline Integration: -amdgpu-ssa-regalloc [FEATURE] [SSARA]

- **Context / goal**
  - Wire complete SSA RA stack into AMDGPU codegen pipeline behind `-amdgpu-ssa-regalloc` flag
  - Replace greedy SGPR/WWM/VGPR allocator chain with RebuildSSA → Spiller → SSA RA

- **Changes applied**
  - **[FEATURE]** `AMDGPUTargetMachine.cpp`: added `cl::opt<bool> EnableSSARegAlloc
    ("amdgpu-ssa-regalloc")` and branch in `addRegAssignAndRewriteOptimized()`
  - **[BUGFIX]** `destroySSAAndRewrite`: replaced bare `leaveSSA()+invalidateLiveness()`
    with new `finalizeProperties()` helper — sets `NoPHIs`, `NoVRegs`; drops
    `invalidateLiveness()` (clearing `TracksLiveness` breaks `MachineLICM`)
  - **[BUGFIX]** Added `eliminateRegSequences()`: lowers `REG_SEQUENCE` pseudos
    that survive into post-RA MIR (normally handled by `VirtRegRewriter`).
    Trivial cases (src already in correct subreg slot) are deleted; non-trivial
    emit a `COPY` then delete the REG_SEQUENCE.

- **Root causes of the three post-RA failures discovered during smoke testing**
  1. `MachineCopyPropagation` required `NoVRegs` → set it in `finalizeProperties`
  2. `BranchFolder` required `NoPHIs` → set it in `finalizeProperties`
  3. `MachineLICM` called `livein_begin()` asserting `TracksLiveness` → removed
     the `invalidateLiveness()` call (MBB live-ins are physreg-only, remain valid)
  4. Assembly printer crashed on `REG_SEQUENCE` pseudo (opcode has no encoding) →
     `eliminateRegSequences()` lowers them before `finalizeProperties`

- **Smoke test results** (`.ll` → full compilation with `-amdgpu-ssa-regalloc`)
  - `basic-loop.ll` (loop + PHI, gfx900): PASS
  - `spill-cfg-position.ll` (diamond + PHI, gfx900): PASS
  - `rewrite-vgpr-mfma-to-agpr-phi.ll` (diamond + loop, gfx908): PASS

- **Next actions**
  - More ambitious end-to-end testing on larger kernels
  - Spiller integration with budget constraints (`amdgpu-num-vgpr`) — force spilling
  - PHI coalescer (paper §4.3)
  - Spiller tied-operand RP fix

---

## 2026-06-12 — Correctness Fixes + Test Cleanup [BUGFIX] [SSARA]

- **Context / goal**
  - Full pipeline working; smoke test the spill path and fix correctness bugs found
  - Run all SSA RA + spiller + NUA tests and achieve zero unexpected failures

- **Bugs found and fixed in SSA RA** (4 post-RA property / liveness bugs)
  - `clearVirtRegs()` in `finalizeProperties()`: verifier checks `MRI->getNumVirtRegs() == 0`
    when `NoVRegs` is set; stale vreg table entries triggered it even with no vreg operands
  - `addPhysRegLiveIns()`: after rewriting vregs→physregs, MBB live-in sets didn't reflect
    physreg liveness; post-RA passes (`MachineLICM`) asserted `TracksLiveness`
  - PHI result live-ins in `lowerPHIs()`: PHI dest LI starts inside block (at PHI def slot),
    not at BBStart — `addPhysRegLiveIns` missed them; add DstPhys as live-in explicitly
  - `pickFreePhysReg` cross-width interference: wider vreg W defined AFTER narrower vreg V
    in same block, both live ranges overlap — `colorByWidth` per-MBB seed missed it

- **Architecture change: color() loop restructured [REFACTOR]**
  - Previous: outer loop = Width, inner loop = MBB (width-first)
  - New: outer loop = MBB, inner loop = Width (block-first)
  - Per-MBB `WiderDefs` accumulator: tiny list `(physreg, &LI)` of assignments made in
    THIS block by wider passes. `pickFreePhysReg` checks WiderDefs via `LI.overlaps()` — O(k)
    per def (k = wider defs in block, typically 0–5), not O(|ColorMap|)
  - `colorByWidth()` eliminated — logic inlined into `color()`
  - Verified: kernarg segment pointer now correctly gets sgpr4_5 (not overlapping sgpr0_3)

- **Spiller test fixes [TEST]**
  - 6 AFTER-LOWER tests used `%[[LANE:[0-9]+]]` pattern — doesn't match named vregs like
    `%s_far`; fixed to `[0-9a-z_]+`
  - `spill-sgpr-wide` AFTER-RA and AFTER-LOWER had `REG_SEQUENCE` check — our
    `eliminateRegSequences()` correctly lowers these to COPYs before downstream passes;
    replaced check with `S_AND_B64` (verifies reconstructed pair is used)

- **E2E spill test (inline)**: diamond kernel with `amdgpu-num-vgpr="2"` through full pipeline
  - Sees `buffer_store_dword`, `buffer_load_dword`, `NumVgprs: 2`
  - RebuildSSA → Spiller → SSA RA stack works end-to-end under pressure

- **Test status** (end of day):
  - 24/24 SSARA, 17/17 NUA, 79/82 SSASpiller (3 XFAIL) — zero unexpected failures
  - 0 formal e2e LIT tests written yet (all smoke tests done via command line)

- **Next session**
  - T2c `pipeline-spill-loop.ll`: loop + back-edge + spill — highest priority gap
  - Start writing formal LIT tests: T1b `pipeline-diamond.ll` first
  - See plan for full 4-tier test grid

## 2026-06-15 — RebuildSSA mis-attributes post-redef uses [BUGFIX] [REBUILDSSA]

- **Context / goal**
  - Building e2e loop test (T1c): wanted a scalar loop with NO back-edge copy
    (kills-before-defs reuse). Every attempt produced a spurious `s_mov` on the
    back-edge or a redundant latch block.

- **[BUG] `reachedByThisVNI` uses position heuristics, not reaching-def**
  - For a loop induction var, the non-SSA MIR is:
    ```
    bb.1.loop:
      %22 = S_ADD_I32 %22, step      ; redefines %22
      S_CMP_LT_U32 %22, n            ; reads the post-add value
    ```
  - RebuildSSA processes value numbers: PHI value (id=1) first, then the S_ADD
    redef (id=2). When rewriting uses of the PHI value, `reachedByThisVNI` decided
    "does this use read the PHI value?" with:
    - same block: `DefIdx(PHI) < UseIdx` — pure lexical order
    - cross block: `MDT->dominates(DefBB, UseBB)` — pure dominance
  - Both ignore the intervening `S_ADD` redefinition. So the PHI value greedily
    claimed the `S_CMP` use (and the loop-exit `COPY`), which actually read id=2.
  - **Symptom**: RebuildSSA emitted `S_CMP %23` (PHI value) instead of `S_CMP %24`
    (post-add). `%23` then lived past the S_ADD → `%24` could not reuse its
    physreg → spurious back-edge copy.

- **Root cause confirmed via `-debug-only=amdgpu-rebuild-ssa`** (not guessed):
  ```
  [RW] exact -> %23 at S_CMP_LT_U32 %22       ← wrong
  [RW] exact -> %23 at %21 = COPY %22 (exit)  ← wrong
  ```

- **[BUGFIX] Query the live interval instead of position**
  - `AMDGPURebuildSSA.cpp` `reachedByThisVNI`: replaced both heuristics with
    `LI.getVNInfoBefore(getInstructionIndex(UseMI).getRegSlot()) == VNI`.
  - The live interval already encodes the exact reaching value at every slot,
    accounting for redefinitions within a block and across blocks.
  - `DefMI` parameter no longer needed; call site in `rewriteUses` updated.

- **Verified** (before → after RebuildSSA output, `bb.1.loop`):
  - `S_CMP_LT_U32 %23` → `S_CMP_LT_U32 %24` (post-add)
  - exit `COPY %23` → `COPY %24`
  - Final asm: loop is one tight block `s_add_i32 s4, s4, s3 / s_cmp / s_cbranch`,
    **no back-edge copy** (was a separate latch with `s_mov`).
  - No regressions: 79 SSASpiller pass + 3 XFAIL, 24/24 SSARA, 17/17 NUA.

- **Decision / rationale**
  - Applied the minimal LiveIntervals-query fix to the current inline RebuildSSA.
  - The deeper fix (def-first renaming via `MachineLaneSSAUpdater`) is the long-planned
    refactor — added to `FUTURE_IMPROVEMENTS.md`. RebuildSSA is a temporary bridge,
    so the minimal correct fix is appropriate now.

- **Next actions**
  - T1c loop e2e test now has a clean copy-free kernel (variable-stride accumulator).
  - Continue formalizing e2e LIT tests (T1–T4).

## 2026-06-16 — E2E tests + spiller margin fix [WIP — UNCOMMITTED] [SSARA] [SPILLER]

**STATE: uncommitted, NOT green. Do not commit. Recreate from transcript if lost.**

### Done and verified
- **RebuildSSA reaching-def fix** (`AMDGPURebuildSSA.cpp`): committed already? NO — it is
  part of today's uncommitted set. `reachedByThisVNI` now uses
  `LI.getVNInfoBefore(getInstructionIndex(UseMI).getRegSlot()) == VNI`, dropped DefMI param.
  Verified: loop back-edge copy eliminated; 24/24 SSARA, 17/17 NUA still pass.
- **2 new e2e LIT tests** (untracked): `SSARA/pipeline-loop.ll` (copy-free scalar loop,
  guards the RebuildSSA fix) and `SSARA/pipeline-diamond.ll` (WiderDefs kernarg-ptr
  disjointness + divergent PHI→VGPR; verified it FAILS on buggy clobbered-base output).
- **New rule** `.cursor/rules/investigate-dont-rationalize.mdc` (alwaysApply): investigate
  unexpected output, never rationalize/adjust-to-match.

### Spiller margin fix (applied, has fallout)
- `AMDGPUSSARegisterSpiller.cpp:2532` — changed `(N*9)/10` → `N - N/10` (floor 10% margin).
  Rationale: old formula rounded the MARGIN UP, cutting 25-50% from small budgets
  (N=3→limit2). New gives margin 0 for N<10, ~10% for large files. Fixes the
  `num-vgpr=3` abort (target was infeasible 2).
- **Fallout**: the entire SSASpiller suite was calibrated to the OLD threshold via its
  budgets. 35 tests failed + 1 XFAIL→XPASS.
- **Re-derivation done (budget-preserving procedure, approved)**: for 33 single-budget
  tests, decremented the budget by exactly 1 (uniform) to restore the OLD effective
  limit → existing verified CHECKs pass unchanged. Script:
  `scripts/retune_spiller_budgets.sh`. All 33 pass.

### OPEN — blocking commit
- **`spill-sgpr-budget-reduction.mir`** (dual budget sgpr=8/vgpr=4): NOT resolved,
  RESTORED to committed state (clean). Budget-only retune impossible: needs SGPR
  limit 5 (→ sgpr=7) AND VGPR-initial 3 (→ vgpr=3), but at vgpr=3 the
  `si-lower-sgpr-spills` WWM allocation fails ("cannot find enough VGPRs for
  wwm-regalloc") — the WWM lane needs the top VGPR the old margin reserved.
  This is the test that exposes the KEY DESIGN QUESTION below.
- **`spill-vreg-many-lanes.mir`**: still failing, not yet investigated (no budget attr).
- **XPASS `spill-balanced-use-before.mir`**: margin fix may have genuinely fixed it —
  needs individual check before removing XFAIL.

### KEY DESIGN QUESTION (decide first tomorrow)
The old `(N*9)/10` margin was **load-bearing**, not just caution: at num-vgpr=4 it
reserved VGPR3 (limit→3), and `SILowerSGPRSpills` WWM allocation needs exactly that free
top VGPR to place the SGPR spill lane. My margin fix removed that headroom at small
budgets → wwm-regalloc has nowhere to go.
- The spiller does `VGPRLimit -= SpillVGPRsUsed`, but that reduces the spiller's TARGET,
  not the SSA RA's actual usage — the RA can still color into the top VGPRs.
- Design decision needed: (a) revisit the margin fix given this WWM-headroom dependency,
  or (b) make the SSA RA explicitly reserve the SGPR-spill-lane VGPRs (explicit headroom
  instead of relying on the margin). Per NOTES design: "SSA RA colors bottom-up, top free
  for SILowerSGPRSpills" — but nothing ENFORCES the top stays free once margin is gone.

### Full-pipeline sanity (answered today)
`-amdgpu-ssa-regalloc` does NOT run both our + greedy: `addRegAssignAndRewriteOptimized`
(line 1716) adds only RebuildSSA→Spiller→SSARA and returns. (Note: SILowerSGPRSpills is
also bypassed in the full pipeline — separate known gap.)

### Resume checklist tomorrow
1. Decide the margin/WWM-headroom design question above.
2. Resolve `spill-sgpr-budget-reduction.mir` and `spill-vreg-many-lanes.mir`.
3. Investigate XPASS `spill-balanced-use-before.mir`.
4. Full suite green, THEN commit (RebuildSSA fix + margin fix + retunes + 2 e2e tests as
   separate logical commits).

## 2026-06-16 — PHI lowering: per-cycle register file [BUGFIX] [SSARA]

- **Context / goal**
  - While investigating the `illegal VGPR to SGPR copy` in `pipeline_loop_exit`
    (loop-with-break kernel), reviewed `lowerPHIs`/`resolvePermutation` and found the
    `IsVGPR` flag was a block-wide assumption taken from the *first* PHI's dest class.
  - Comment "All PHIs in one block share the same register file" is wrong: in the VGPR
    pass a block can hold both VGPR and SGPR PHIs.

- **Results / discoveries**
  - **[BUGFIX]** `IsVGPR` is only consumed in Phase 2 (cycle breaking) of
    `resolvePermutation`: scratch counter/base (`MaxVGPRIdx`/`MaxSGPRIdx`, `VGPR0`/`SGPR0`),
    HW limit, occupancy model, and `emitSwap` (VGPR-only `V_SWAP_B32`/`V_XOR_B32`).
    Phase 1 chain copies are file-agnostic plain `COPY`s.
  - A permutation cycle is always confined to one file (a VGPR dest can never equal an
    SGPR src), so the file is a property of the cycle, not the block. With the old code a
    VGPR-first block containing an SGPR cycle would emit wrong-file scratch/swaps →
    miscompile (latent; needs mixed-file PHIs + a same-file cycle to trigger).

- **Changes applied (APPROVED: per-cycle register file in resolvePermutation)**
  - Dropped `bool IsVGPR` param from `resolvePermutation` (`.h` + `.cpp`).
  - `lowerPHIs`: removed the misleading comment + dead `FirstDst`/`IsVGPR`; call updated.
  - `resolvePermutation` Phase 2: derive `IsVGPR = TRI->isVGPRClass(getPhysRegBaseClass(
    CycleStart))` per cycle; moved `MaxIdx`/`MaxHWLimit`/`CurrentOcc` inside the loop;
    removed now-dead `CurrentOcc = ScratchOcc;`.

- **Results / verification**
  - Rebuilt `llc`; full SSARA suite 27/27 pass.
  - NOTE: this is a separate fix from the still-pending subreg-on-PHI-source fix; the
    `illegal copy s[4:5] to s8` in `pipeline_loop_exit` is the subreg bug and remains
    until that one is applied.

## 2026-06-16 — PHI lowering: subreg on PHI source [BUGFIX] [SSARA]

- **Context / goal**
  - Root cause of `illegal copy s[4:5] to s8` in `pipeline_loop_exit` (loop-with-break).

- **Results / discoveries**
  - **[BUGFIX]** PHI source `%63 = PHI %33.sub0, ...` where `%33` → `$sgpr4_sgpr5`. In
    `lowerPHIs` the copy was built from `ColorMap.lookup(SrcVReg)` (the full tuple),
    dropping the `.sub0` index → emitted `$sgpr8 = COPY $sgpr4_sgpr5` (64→32, illegal).
  - `rewriteOperands` already resolved subregs (`TRI->getSubReg`); `lowerPHIs` never did.

- **Changes applied (APPROVED)**
  - `lowerPHIs`: if the PHI source operand has a subreg index, apply
    `SrcPhys = TRI->getSubReg(SrcPhys, SubIdx)` before queuing the copy. Source side only —
    PHI result operands are never subreg defs.

- **Results / verification**
  - Rebuilt `llc`. Repro now emits `s_mov_b32 s8, s4` (sub0); `-verify-machineinstrs`
    clean, no `illegal`/`error`. Full SSARA suite 27/27 pass.
  - Combined with the per-cycle register-file fix earlier today, the T1d loop-exit kernel
    is now correct end-to-end.

- **[TEST]** Added `SSARA/pipeline-loop-exit.ll` (T1d) guarding both fixes: `CHECK-NOT:
  illegal copy` catches the subreg regression, `-verify-machineinstrs` adds verifier
  coverage, structural CHECKs assert loop+exit shape. SSARA suite now 28/28.

## 2026-06-16 — Spiller under-spills at tight budget (RP validation abort) [BUG] [SPILLER]

- **Context / goal**
  - While prototyping T2a `pipeline-spill-linear.ll` (6 loads, two reductions over all
    inputs), swept `amdgpu-num-vgpr`. Clean spill at budget 4 (ScratchSize 12). At budget 3
    the SSA spiller aborts: `FINAL RP VALIDATION FAILED! Current RP: 4, RP Limit: 3` at the
    4th volatile load `%24 = GLOBAL_LOAD_DWORD_SADDR ... p3` in bb.0.

- **Verification: is 3 feasible? YES.**
  - Greedy (default pipeline) on the identical kernel: `num-vgpr=3` → succeeds, NumVgprs 3,
    ScratchSize 16. `num-vgpr=2` → "ran out of registers" (genuinely infeasible).
  - So **3 is the true minimum and is allocatable**; our spiller is under-spilling.

- **Root-cause hypothesis**
  - The SADDR offset VGPR `%30 = tid<<2` is shared/live across all six loads (1 permanent).
    The spiller left `a0,a1,a2` results un-spilled across the 4th load → RP 4. With
    store-at-definition only the shared address + the new def should be live (RP 2) across a
    load. The spiller failed to spill the earlier results, then `report_fatal_error`s instead
    of recovering.

- **Status / decisions**
  - Real `[BUG] [SPILLER]`, not infeasibility. T2a test will use budget 4 (clean spill) so it
    is not blocked by this. Investigate the under-spill separately (likely the spill-decision
    heuristic not accounting for the long-lived shared address / not iterating to the limit).

## 2026-06-16 — Spiller RP metric root cause: during-MI peak vs after-MI [DESIGN] [BUG] [SPILLER]

- **Context / goal**
  - Deep-dived the `num-vgpr=3` abort on the two-reduction `pipeline-spill-linear` kernel
    (see prior entry). Repro `/tmp/sl-3.ll`; post-RebuildSSA MIR `/tmp/sl3-rebuilt.mir`.
    Abort: `FINAL RP VALIDATION FAILED, RP=4, limit=3` at the p3 load `%24`.

- **NUA is NOT the bug (verified).** The invariant "next-use distance at a use == 0" holds.
  `llc -run-pass=amdgpu-next-use -amdgpu-next-use-dump-distance /tmp/sl3-rebuilt.mir` shows at
  `%24 = GLOBAL_LOAD ... %20`: `%20[0]` (used here), `%23[1]`,`%27[1]` (used at `%28`). The dump
  and `getNextUseDistance(I,VMP)` use the identical `InstrDist[&*I]`/`InstrOffset` path
  (NUA.cpp:521-546, dump 624-674) — no divergence.

- **Two real defects in the SPILLER (not NUA):**
  1. **Wrong NUA query slot.** `sortRegSetByNextUse` queries `AfterCurrent =
     std::next(I.getReverse())` (Spiller.cpp:461,499) — the snapshot AFTER MI. So a register
     used by MI that also lives on (the load's shared address `%20 = tid<<2`, live across all 6
     loads) is scored by its NEXT use (≥1) instead of the protective 0, and gets picked as the
     spill victim even though spilling it can't lower RP at MI. Fix direction: query at MI's
     own slot (uses→0, naturally protected; live-through get true distance).
  2. **Wrong RP metric (root cause of the abort).** Spiller uses `RPTracker->reset(MI)`
     (Spiller.cpp:343) → `GCNUpwardRPTracker::reset(MI)` resets to `getDeadSlot()` = AFTER MI,
     then reads `getPressure()` = `CurPressure` (after-MI set). This UNDERCOUNTS the true
     during-MI peak: `%28 = V_ADD3_U32 %27,%23,%24` with `%20` live-through has after-MI RP=2
     but needs 4 registers during execution (3 inputs read simultaneously + `%20` crossing).
     Spiller never sees pressure at `%28` → never spills `%20` there → RA can't color → abort.

- **Key realization (user-led): the backward tracker ALREADY computes the during-peak.**
  `GCNUpwardRPTracker::recede(MI)` (GCNRegPressure.cpp:518-576) sets `MaxPressure =
  max(write-peak {defs+survivors}, read-peak {uses+survivors})`, early-clobber-aware,
  lane-mask accurate. This inherently accounts for dying operands and operand→result reuse
  (a dying operand isn't a survivor; the def reuses its slot) — so NO hand-rolled
  `|live-in| + (noInputDies?1:0)` formula is needed. Verified: `recede` MaxPressure = 4 for
  both `%24` and `%28`. The spiller simply reads `CurPressure` (after-MI) instead of driving
  `recede()` + `getMaxPressure()`.

- **Feasibility confirmed:** greedy fits this kernel in 3 VGPRs (NumVgprs 3, ScratchSize 16);
  2 is genuinely infeasible. So 3 is the true minimum — the spiller bug, not infeasibility.

- **Agreed fix direction (NOT yet implemented — awaiting fresh start):**
  1. Drive RP via `GCNUpwardRPTracker::recede()` bottom-up, read `getMaxPressureAndReset()`
     per MI (true during-peak; also O(n) vs current O(n²) per-instruction reset).
  2. Select spill victims by querying NUA at MI's own slot (not AfterCurrent); candidates are
     the live-through regs (operands get 0 and are excluded for free).
  3. Re-validate: `num-vgpr=3` must allocate; full SSARA + SSASpiller suites green.
  - Open detail to work out tomorrow: reshaping `processFunction` into a bottom-up walk with
    incremental tracker state, and how the validator (`validateFinalRegisterPressure`) should
    likewise use the during-peak (MaxPressure).

- **Discarded approaches:** (a) "exclude MI.uses() from candidates" — treats the symptom, not
  the RP-metric root cause; (b) hand-rolled during-peak formula — reinvents `recede()`'s
  MaxPressure, worse and by hand. (c) editing NUA — NUA is correct.

- **T2a test status:** `pipeline-spill-linear.ll` at `num-vgpr=4` produces a clean verified
  spill (ScratchSize 12) — usable once we resume the test plan; the `num-vgpr=3` case is the
  bug above.

## 2026-06-17 — Spiller during-MI peak RP metric [BUGFIX] [SPILLER]

- **Context / goal**
  - Implement the agreed fix for the `num-vgpr=3` `FINAL RP VALIDATION FAILED` (after-MI metric
    undercounts the during-MI peak). Repro `/tmp/sl-3.ll`.

- **Changes applied (APPROVED, AMDGPUSSARegisterSpiller.cpp)**
  - **[BUGFIX]** `processFunction` + `validateFinalRegisterPressure`: replace `reset(MI)` +
    `getPressure()` (after-MI live set) with `reset(MI); recede(MI); getMaxPressure()` =
    true during-MI peak (max of write-peak {defs+survivors} and read-peak {uses+survivors},
    early-clobber aware). Per-MI reset scopes MaxPressure to the instruction.
  - **[BUGFIX]** PHI guard: a PHI has no read phase (sources are live out of preds, moved by
    edge copies in SSA destruction), so for PHIs use `getPressure()` (block-entry set), not
    recede — otherwise recede counts PHI sources as a read peak and over-reports (caught by
    `spill-vreg-subregister`: vreg_128 PHI reported RP 8).
  - **[REFACTOR]** `sortRegSetByNextUse`: query NUA at MI's own slot (not `AfterCurrent`), and
    subtract the lanes MI READS from each candidate (per-vreg `UsedLanes`), rebuilding `Active`
    with only the live-across lanes. Removed early-clobber Steps 1/2/4 (subsumed: an EC use is
    just a read here; recede covers EC in the metric). Lane-level subtraction keeps a
    sub-register spillable when a sibling lane is read (e.g. `%x.sub1` while `%x.sub0` is read).
    SSA has no partial defs, so the whole-register def exclusion is left as-is.
  - **[REFACTOR]** `validateFinalRegisterPressure` re-walk no longer always-on "TEMPORARY"
    `report_fatal_error`. Gated by a `cl::opt<cl::boolOrDefault>` `-amdgpu-ssa-spiller-verify-rp`
    (TargetPassConfig::VerifyMachineCode idiom): on when the flag is set, and by default under
    `#ifdef EXPENSIVE_CHECKS`. The SSASpiller suite forces it on for every test via a new
    `lit.local.cfg` that appends the flag to the `llc` substitution (Attributor/lit.local.cfg
    ToolSubst pattern) — verified the flag lands in the executed `llc` command. Member fn → no
    `-Wunused-function`.

- **Test changes (APPROVED, preserve intent)**
  - `spill-physreg-def-midblock.mir`: `%d` now consumed by `S_NOP` instead of kept live to
    `S_ENDPGM`, so ≤3 values live at the terminator (was 4 — genuinely infeasible at limit 3,
    only "passed" before because the after-MI metric ignored the terminator read peak). Mid-block
    physreg→one-spill intent preserved.
  - `spill-vreg-subregister.mir`: regenerated via `update_mir_test_checks.py`. New output adds a
    correct `SI_SPILL_V32_SAVE`/`RESTORE` in `bb.6` for the `V_ADD` result — `%1` is live-out
    (needed in bb.4), so `%1`(4)+`%14`(4)=8 > limit 7; the old recorded output was over-limit
    and the after-MI metric missed it.

- **Results**
  - `num-vgpr=3` now allocates (NumVgprs 3, ScratchSize 12), `=2` still infeasible (matches
    greedy). Suites: SSASpiller 39 + 2 XFAIL (0 unexpected), SSARA 28/28, NUA 17/17.

- **[TEST]** Added `SSASpiller/spill-unused-lane.mir` guarding the lane-granular candidate
  selection: `%c = V_ADD %x.sub0, %a` with `%x.sub0`/`%a` reused by `%e` (so they stay live and
  the def can't reuse → over limit 3 at `%c`); the only lane not read there is `%x.sub1`
  (used late) → spiller spills `%x.sub1` (partial-lane), not `%x` or `%a`. Two distinct opcodes
  (V_ADD / V_XOR) so the RHS isn't CSE-able. SSASpiller now 40 + 2 XFAIL (RP verifier on via
  lit.local.cfg).

## 2026-06-18 — E2E test plan complete + loop-coloring root cause [DESIGN] [BUG] [SSARA]

- **Context / goal**
  - Finish the 4-tier e2e test plan and freeze this worktree before two refactors.

- **Test plan: 36 SSARA tests, 34 pass + 2 XFAIL (0 unexpected).** New this session:
  T2a `pipeline-spill-linear` (+SPILLER marker check), T2b `pipeline-spill-diamond` (+marker),
  T2c `pipeline-spill-loop` (XFAIL), T3a `pipeline-mixed-width` (MFMA gfx908), T3b
  `pipeline-wide-v64`, T3c `pipeline-wide-v128` (XFAIL), T4a `pipeline-sgpr-heavy`, T4b
  `pipeline-occupancy`. Plus committing earlier T1a `pipeline-linear`, T1b `pipeline-diamond`.
  - Spill e2e tests carry a second RUN line: `-stop-after=amdgpu-ssa-register-spiller
    -amdgpu-ssa-spill-markers=1 | FileCheck --check-prefix=SPILLER` asserting
    `SI_SPILL_V32_SAVE` then `SI_VIRTUAL_SPILL_MARKER` (proves OUR spiller spilled; order is
    SAVE-before-MARKER).

- **The 2 XFAILs share ONE root cause [BUG] [REBUILDSSA]:** RebuildSSA legalizes in-place
  subregister defs (`undef %r.sub0:vreg_64 = ...; %r.sub1 = ...`) inconsistently — it splits
  the *re*-def (sub1 → separate vgpr_32 `%76`) but leaves the *first* def as a partial wide
  def `undef %39.sub0:vreg_64`. So `%39` is a vreg_64 carrying ONE live lane; the RA allocates
  the full tuple (2 VGPRs / aligned) for it → pressure inflation. T2c (divergent loop):
  color() aborts "Failed to find free physreg" at a budget greedy fits (6). T3c (v128):
  verifier "Using an undefined physical register". `repairSSAForNewDef` in MachineLaneSSAUpdater
  is lane-aware and would never emit this.

- **Spiller↔RA contract finding [Q0]:** if the spiller reports feasible but the RA can't color,
  that IS a bug — their pressure models must agree. Here the spiller counts `%39` by live lanes
  (1) while the RA spends a full tuple (2). Verified: grep shows the spiller does NOT special-case
  REG_SEQUENCE/COPY (no coalescing assumption); GCNUpwardRPTracker counts copy/reg_seq normally
  (src-lives-on ⇒ +1, matching un-coalesced RA). So the disagreement is solely the partial def.

- **Register-file alignment facts (corrected):** VGPR tuples are **stride-1** (any N CONSECUTIVE
  regs, NOT even-aligned); only SGPRs are alignment-constrained (stride 2 for 64-bit, 4 for 96+).
  So VGPR fragmentation is about consecutiveness, SGPR about even-alignment. The T2c crash is
  COUNT inflation (Q1), not alignment.

- **Cross-block fragmentation (general):** per-block width-descending packs alignment only WITHIN
  a block; a narrow value colored at an inconvenient slot in its def block, live into another
  block, can break a wider value's consecutive/aligned run there (global ColorMap fixes color at
  def). **Function-wide width-descending fixes this**: color all wider defs (function-wide) before
  any narrower, so narrower never fragments wider. Cost: needs global cross-width interference
  (replaces the cheap per-block WiderDefs accumulator the code moved to on 2026-06-12).

- **Coalescer placement:** correctness must NOT depend on coalescing (RA must color any
  spiller-feasible fn). After Q1 fix, the un-coalesced REG_SEQUENCE is fine (operands die →
  result reuses) so coalescing is pure quality and can stay POST-RA (unified general+PHI phases).
  A *post-RA* coalescer cannot rescue a *fragmentation* RA failure — that needs alignment-aware
  spiller pressure or pre-color merge — but that's not what T2c hits once Q1 is fixed.

- **Effort estimate (RebuildSSA):** local Q1 fix ≈ 0.5–1 day but throwaway + fragile (inline
  VNInfo/lane machinery). Refactor to MachineLaneSSAUpdater ≈ 1–2 days, deletes ~250 lines, uses
  `repairSSAForNewDef` (its documented primary use case = "new def of OrigVReg → rename + IDF PHIs
  + rewrite dominated uses"), fixes Q1 + reachedByThisVNI heuristic + inflation; `ssa-rebuilder`
  worktree already started. Recommendation: do the refactor.

- **Phased plan**
  1. Phase 0 (this worktree, DONE): finish test plan, XFAIL the 2 known-bug cases, commit batch.
  2. Phase 1: RebuildSSA → MachineLaneSSAUpdater (ssa-rebuilder worktree). Validates by flipping
     T2c + T3c XFAILs to passing.
  3. Phase 2: RA coloring → function-wide width-descending (closes cross-block fragmentation).
  - Tracked: unified post-RA coalescer (quality); alignment-aware spiller pressure (if needed).

## 2026-06-18 — Function-wide width-descending coloring [FEATURE] [SSARA]

- **[FEATURE] Function-wide width-descending coloring**
  Swapped loop nesting: outer=Width (descending), inner=MBB (MDT pre-order).
  Wider defs committed to ColorMap before narrower passes start. Prevents
  narrow defs from fragmenting alignment slots needed by wider tuples.

- **Cross-block interference via ColorMap scan in pickFreePhysReg**
  For narrower passes, scans ColorMap for wider entries whose LI overlaps
  the candidate. O(|ColorMap|) per pickFreePhysReg call — brute force.
  Correct but quadratic for large kernels (~50ms for 10K vregs).

- **[P1 TODO] Compile-time optimization**: replace O(|ColorMap|) scan with
  interval tree or sorted-vector binary search. Target: O(log N + k) per
  query. Analysis: current brute-force = ~48M iterations for large kernel
  vs ~30K with per-block WiderDefs. Must fix before large-kernel testing.

- **WiderDefs pre-scan retained**: for within-block wider defs not live at
  BBStart. Populated from ColorMap at block entry, O(|block|) per block.

- **Test: `align-fragmentation.mir`** (gfx90a): cross-block alignment
  fragmentation. Per-block: %2→VGPR2-3 (MaxVGPR=4). Function-wide:
  %2→VGPR0-1 (MaxVGPR=3). Saves 1 VGPR.

- **All tests green**: 26 SSARA unit + 12 E2E pipeline = 38 PASS, 0 failures.

- **Key finding: VGPR even-alignment is target-specific**
  gfx90a/940+/gfx1250: `FeatureRequiresAlignedVGPRs` → `VReg_64_Align2`
  (even-start only). gfx900/gfx10/11: stride-1, no alignment.
  SGPR alignment (stride-2/4) is universal.

---

## 2026-06-29 — Interval-tree compile-time task split to its own chat [PERF] [SSARA]

- **Context / goal**
  - Recognized the interval-tree work is a **compile-time performance optimization** (replace the
    `O(|ColorMap|)` cross-width interference scan in `pickFreePhysReg`), **separable** from
    pipeline integration. Decided to continue it in a dedicated chat to keep concerns clean.

- **Deliverables produced this session**
  - **Learning doc**: `ssa-spiller-docs/SSARA/03-Concepts/Interval_Tree.md` — concept, RB-tree
    refresher (motivation, 5 invariants, height proof, recolor/rotate across ops), rotation in
    3 colored stages (initial → rotate → recolor), `max` augmentation, search/insert/delete,
    complexity table, and practical notes for our use. (Fixed leaf `max` bug: `[26,26]` is `26`.)

- **[PERF] Evaluation of LLVM `llvm/ADT/IntervalTree.h` (decision input)**
  - It is a **centered/median** interval tree, **NOT** the augmented RB tree (so the doc describes
    our own design, not this header).
  - **Build-once, frozen**: `insert()` asserts `empty()`, then `create()`; **no incremental
    insert, no delete, no rebalancing** (per class comment).
  - **Point-stabbing only**: `getContaining(Point)` / `find(Point)`. **No interval-overlap query**
    — stabbing at query endpoints misses a stored range strictly inside the query, so it can't
    answer "wider range overlapping `[qlo,qhi]`" correctly.
  - **`PointT` must be fundamental** (`static_assert`) → `SlotIndex` must be lowered to `.index()`;
    `ValueT` fundamental/pointer (so `LiveInterval*` ok).
  - **Not subclassable**: members private, non-virtual. Only extension point is the `DataT`
    template param (subclass `IntervalData` for payload).
  - **Fit note (in our favor)**: width-descending coloring means the *wider* colored set is FIXED
    for the whole width-`W` pass → a build-once-then-query structure is viable *per pass*; the real
    blocker is overlap-vs-stabbing semantics, not staticness.
  - **Decision**: roll our own augmented overlap structure (true interval-overlap + `max` prune,
    optionally incremental); cite `IntervalTree.h` as prior art. Peek at `IntervalMap.h` first
    (dynamic insert/erase + overlap iteration, but geared to coalesced/non-overlapping keys — our
    ranges overlap heavily, so likely not a clean fit).

- **Next actions** (in the new chat)
  - Confirm exact query shape needed by `pickFreePhysReg` (per-width-pass rebuild vs incremental).
  - Implement the augmented overlap index; replace the brute-force scan from 1a21fd3.
  - Kickoff prompt + LLVM findings already captured here and in `SHARED_CONTEXT.md`.

---

## 2026-06-29 — Real-kernel testing: illegal VGPR→SGPR copy crash [BUGFIX] [SSARA]

- **Context / goal**
  - Started real-world kernel testing stage: compile big kernels with `-amdgpu-ssa-regalloc`
    and compare against greedy. First candidate `atomic_optimizations_local_pointer.ll`
    (gfx900) immediately crashed under SSA RA; greedy compiled clean.

- **Repro (isolated via freshly-built `llvm-extract`)**
  - Minimal: `add_i64_uniform` = `atomicrmw add` on an LDS i64 + store to global. Flags:
    `-mcpu=gfx900 -mattr=-flat-for-global -amdgpu-atomic-optimizer-strategy=Iterative
    -amdgpu-ssa-regalloc`. Greedy OK, SSA aborted: `illegal VGPR to SGPR copy` →
    `Found 6 machine code errors`. Real msg: `illegal copy s[0:3] to s[0:1]` (width mismatch).

- **Root cause [BUGFIX]**
  - `eliminateRegSequences()` lowered `%95:sgpr_128 = REG_SEQUENCE ..., %97:sgpr_128,
    %subreg.sub0_sub1, ...` by copying the **full** over-wide source physreg into the 64-bit
    slice: `$sgpr0_sgpr1 = COPY $sgpr0_sgpr1_sgpr2_sgpr3`. `%97` is class `sgpr_128` but holds
    a 64-bit value (only `sub0_sub1` defined — an over-wide vreg). The REG_SEQUENCE slice index
    (`sub0_sub1`) also names the matching sub-register of the source, which the lowering ignored.

- **Fix (committed pending)** `AMDGPUSSARegisterAllocator.cpp` eliminateRegSequences (~L577):
    before emitting the COPY, narrow the source to its slice subreg —
    `if (MCRegister SubSrc = TRI->getSubReg(Src, SubIdx)) Src = SubSrc;`. For 32-bit pairs
    (`%94,sub2` / `%99,sub3`) `getSubReg` returns 0 (no such subreg on a 32-bit reg) → Src
    unchanged, copies intact. For `%97` → `$sgpr0_1` == `Expected` → trivial, no copy emitted.

- **Results / verification**
  - Repro: SSA now compiles clean. Quality vs greedy: VGPR 5 vs 4, SGPR 14 vs 13, scratch 0/0,
    **occupancy 10 vs 10** (same) — correct + feasible, 1 reg looser.
  - Suites: SSARA + SSASpiller = 77 passed / 2 XFAIL / 0 regressions.

- **Second bug found via same repro [BUGFIX] — REG_SEQUENCE parallel-copy hazard (miscompile)**
  - After the width fix the verifier passed, but the descriptor build was a **miscompile**:
    `eliminateRegSequences` emitted the per-slice copies in operand order, ignoring that
    REG_SEQUENCE is a *parallel* assignment. For `$s[0:3] = REG_SEQUENCE $s10 sub0, $s0 sub1`
    it emitted `s0←s10` then `s1←s0` — the second copy read `s0` after the first overwrote it,
    so `s1` got `out.lo` instead of `out.hi` → store address high word corrupted.
  - **Fix:** collect the non-trivial `(Src→slice)` pairs and route them through
    `resolvePermutation()` (the same parallel-copy resolver used for PHI edges) instead of
    naive `BuildMI(COPY)`. Its chain phase emits `s1←s0` first, freeing `s0`, then `s0←s10`;
    cycles get the existing scratch/swap tiers for free.
  - **Verified:** descriptor now `s2=-1, s3=0xf000` with `s0/s1 = {out.lo,out.hi}` preserved;
    no scratch dance. SSARA+SSASpiller 77 pass / 2 XFAIL / 0 regressions.

- **Quality vs greedy (post-fix, correct):** VGPR 5 vs 4, SGPR 14 vs 13, occupancy 10 vs 10.
  The 1-reg gap is **missing coalescing** (un-coalesced pre-existing COPYs + REG_SEQUENCE
  shuffles greedy merges in place) — expected, absorbed by the planned coalescer; not an
  allocation deficiency.

- **Per-kernel greedy-vs-SSA sweep (atomic_optimizations_local_pointer.ll, 33 kernels, gfx900)**
  - Method: `llvm-extract` each kernel, compile greedy vs `-amdgpu-ssa-regalloc`, compare
    NumVgprs/TotalNumSgprs/ScratchSize/Occupancy.
  - **Occupancy identical (10) on all 31 compiling kernels; scratch 0/0 everywhere** — no spills,
    no occupancy regressions, no SSA-RA crashes. **Hypothesis confirmed: allocations differ only
    in coalescing quality** (un-coalesced COPY/REG_SEQUENCE shuffles). SSA sometimes *better*
    (i32 varying: −1 SGPR; add/sub_i64_varying: −1 VGPR); i64 uniform/constant slightly looser
    (e.g. max_i64_constant V=6 vs 3). All gaps are raw counts, never occupancy/spills.
  - **[BUG — RebuildSSA, not SSA-RA]** `max_i64_varying` + `min_i64_varying` (signed i64 varying
    reductions) crash in `MachineLaneSSAUpdater::performSSARepair` (MachineLaneSSAUpdater.cpp:205)
    via `AMDGPURebuildSSA` (AMDGPURebuildSSA.cpp:158): `LiveIntervalCalc` finds a use with no
    reaching def → MF.verify reports broken PHIs/vregs → abort. UPSTREAM of SSA-RA (our allocator
    never runs). `umax/umin_i64_varying` (unsigned) do NOT crash. Belongs to `ssa-rebuilder`
    worktree (loop/lane SSA-reconstruction). Repro: `llvm-extract -func=max_i64_varying`.

- **[TEST] Regression test added (committed pending)**: `SSARA/regseq-lowering.ll` — reduced
  `add_i64_uniform` (uniform i64 atomicrmw → buffer-store via REG_SEQUENCE rsrc). RUN: full
  pipeline `-amdgpu-atomic-optimizer-strategy=Iterative -amdgpu-ssa-regalloc
  -verify-machineinstrs`. Guards both bugs: Bug 1 via successful verify (was a verifier abort);
  Bug 2 via `CHECK-NOT: s_mov_b32 s1, s0` (descriptor high addr word must not be clobbered) +
  `CHECK: buffer_store_dwordx2 v[0:1], off, s[0:3], 0` + `ScratchSize: 0`. SSARA suite 38/38.

## 2026-06-29 — Updater crash root-caused: loop-header lane PHI preheader operand [BUG] [MSSA-UPDATER]

- **Repro:** `/tmp/repro_max_i64_varying.ll` (signed i64 `atomicrmw max` on LDS, iterative atomic
  optimizer → ComputeLoop). gfx900, `-mattr=-flat-for-global -amdgpu-atomic-optimizer-strategy=
  Iterative -amdgpu-ssa-regalloc`. Greedy OK; SSA pipeline aborts in `AMDGPURebuildSSA`.
- **Crash site:** `MachineLaneSSAUpdater::performSSARepair` line 192 (`createAndComputeVirtReg
  Interval(OrigVReg)`), via `repairSSAForNewDef` (MachineLaneSSAUpdater.cpp:124) from
  `AMDGPURebuildSSA.cpp:158`. NOT a SSA-RA bug — upstream of our allocator.
- **Root cause:** repairing loop-carried i64 accumulator `%101` (5 VNs, the `max` reduction).
  `insertLaneAwarePHI` synthesizes loop-header PHI `%115 = PHI %101.sub0, %bb.0, %114, %bb.3`
  (mask 0x3=sub0). Its preheader (`%bb.0`) operand stays `%101.sub0` and is never resolved:
  (1) `rewriteDominatedUses` for the loop def (NewSSA in bb.3) correctly skips it (bb.3 doesn't
  dominate the bb.0 edge); (2) no bb.0-side rewrite happens because `%101`'s Root def is
  full-width and RebuildSSA skips renaming full-width Root defs (AMDGPURebuildSSA.cpp:150-155).
  Result: preheader PHI operand has no reaching def → LiveIntervalCalc "Reading virtual register
  without a def" / "PHI operand not live-out from predecessor" → abort. `umax/umin_i64_varying`
  don't hit it (different lane-def pattern).
- **Location:** `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp` (lane-aware loop-header PHI
  construction) — shared CodeGen = `mssa-updater` worktree domain; `ssara` has a ported copy.
- **Decision pending:** fix in `mssa-updater` (canonical, avoids divergence) vs locally in `ssara`.

## 2026-06-30 — Updater fix applied: rename-map reaching-def resolution [BUGFIX] [MSSA-UPDATER]

- **Fix (Part 1, applied in ssara, uncommitted):** `MachineLaneSSAUpdater` now resolves loop-header
  PHI preheader operands to the actual reaching def instead of an unresolvable `OrigVReg.subIdx`
  placeholder.
  - New per-session map `RenamedLaneDefs: {defBlock, LaneMask} → NewReg` (OrigVReg implicit;
    defBlock keeps multiple renames of a lane distinct). Reset on OrigVReg change in
    `repairSSAForNewDef`; populated after each rename (`{NewDefMI.getParent(), DefMask}=NewSSAVReg`).
  - New `findRenamedReachingDef(PredMBB, Mask)`: among candidates covering Mask, returns the one
    whose LI is live-out of PredMBB (`getInterval(Cand).getVNInfoBefore(getMBBEndIdx(PredMBB))`).
    LI-based (precise), no dominance scan; SSA ⇒ at most one candidate live there.
  - `createPHIInBlock` else-branch consults it before falling back to the placeholder.
  - Complexity: negligible — adds `O(p·d·log s)` vs the pass's existing `O(d·N)` per-rename LI
    recompute. No asymptotic change.
- **Verified:** `max_i64_varying`, `min_i64_varying` now compile under SSA and match greedy
  EXACTLY (VGPR 6, SGPR 15, occ 10). Full `atomic_optimizations_local_pointer.ll` compiles (exit 0,
  no crashes). SSARA+SSASpiller: 78 pass / 2 XFAIL / 0 regressions.
- **Files:** `llvm/include/llvm/CodeGen/MachineLaneSSAUpdater.h`,
  `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`.
- **Part 2 (nested loops) NOT done:** record PHI results as candidates + reserve-then-fill in
  `insertLaneAwarePHI` to break the inner↔outer PHI def-use cycle. Deferred until a nested-loop
  repro exists to validate.

- **[BUGFIX] TiedOpsRewritten property mismatch (2nd updater bug, unmasked by Part 1)**
  - `-verify-machineinstrs` (verifies after every pass) flagged: `*** Two-address instruction
    operands must be identical ***` on `%117 = V_WRITELANE_B32 %113, $m0, %118(tied-def 0)`
    (def %117 ≠ tied use %118). Was masked by the %101 crash before Part 1.
  - Root cause (NOT a renaming bug): the verifier gates that check on the `TiedOpsRewritten`
    **property** (MachineVerifier.cpp:2628), not on SSA-ness. In machine SSA, tied def≠use is
    legal *until* TwoAddressInstructionPass rewrites them and SETS TiedOpsRewritten. RebuildSSA
    re-SSA-ifies (tied def≠use again) but left TiedOpsRewritten set → false verifier error.
  - **Fix (applied, uncommitted):** `AMDGPURebuildSSA` resets `TiedOpsRewritten` after rebuilding
    SSA; `AMDGPUSSARegisterAllocator::finalizeProperties` re-sets it post-RA (RA gives tied def
    its use's physreg → def==use, like VirtRegRewriter). Files: `AMDGPURebuildSSA.cpp`,
    `AMDGPUSSARegisterAllocator.cpp`.
  - **Verified:** max/min_i64_varying + full file now pass `-verify-machineinstrs` (exit 0).

- **[TEST] Regression test added (uncommitted):**
  `llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/rebuildssa-loop-i64-reduction.ll` — reduced
  `max_i64_varying`, full pipeline, WITH `-verify-machineinstrs` (now passes; guards both the
  loop-PHI crash and the TiedOpsRewritten property). PASS.

- **Suite status:** SSARA 38 + SSASpiller 42 = all pass (78 / 2 XFAIL / 0 regress). NOTE: the 4
  `MachineLaneSSAUpdater/*.mir` tests (`simple_new_def`, `phi_insertion`, `partial_lanes`,
  `spill_reload`) FAIL in **ssara** because their harness pass `test-machine-lane-ssa-updater`
  is NOT registered in this worktree (it lives in `mssa-updater`). Pre-existing, unrelated to
  these changes. Must validate Part 1 against them when porting to `mssa-updater`.

- **[RESOLVED] Part 2 (nested loops) NOT needed.** Built a nested-loop repro
  (`MachineLaneSSAUpdater/rebuildssa-nested-loop-i64.ll`): loop-carried i64 accumulator, inner
  `add i64` → per-lane sub0/sub1 defs, live across the outer loop. RebuildSSA lane-splits `%48`
  (5 VNs), IDF spans BOTH loop headers, and `insertLaneAwarePHI`'s existing **chaining**
  (`CurrentNewVReg = PHIResult`) creates both header PHIs in one call and threads the inner PHI
  result into the outer header PHI's back-edge (`%51 = PHI %48.sub0, outer-pre, %50, latch`).
  With Part 1 resolving the preheader operands, it compiles + passes `-verify-machineinstrs`.
  So the "PHI-result-as-operand" cycle is already handled by chaining — reserve-then-fill is
  unnecessary. Both updater regression tests pass.

## 2026-06-30 — DESIGN GAP: spiller RP must reflect post-coalesce reality [DESIGN] [SPILLER]

- **Concern (user):** the SSA Spiller has no coalescing awareness, so it overestimates register
  pressure and can overspill. Greedy spills only AFTER `RegisterCoalescer`; our spiller runs on
  post-RebuildSSA MIR with un-coalesced reconstruction copies/REG_SEQUENCEs.
- **Precise analysis:** a genuinely coalesceable pair (copy-related + non-interfering) is NOT
  simultaneously live except AT the copy/REG_SEQUENCE slot. So inflation is **localized spikes**,
  not uniform:
  - killing `COPY %b=%a` (%a dies): +1 at the copy slot only.
  - `REG_SEQUENCE %wide = %a:sub0, %b:sub1`: parts+whole co-live → e.g. 64-bit = 1+1+2=4 vs
    coalesced 2 (≈2× spike), exactly where RebuildSSA reconstructs wide values.
- **Why pre-RebuildSSA RegisterCoalescer doesn't help:** RebuildSSA reintroduces these copies
  AFTER it. Stock RegisterCoalescer is post-PHIElim/non-SSA → can't run on RebuildSSA's SSA+PHIs.
  A post-RA coalescer (planned for quality) is too late for the spiller. ⇒ This reframes the
  coalescer from "quality nice-to-have" to "needed before the spiller for spill-decision accuracy."
- **Spiller code check:** no REG_SEQUENCE/COPY/coalesce handling at all; RP is raw
  `GCNUpwardRPTracker` (recede + getMaxPressure) → counts every live vreg incl. parts+whole.
- **Options:**
  1. **Coalescing-aware RP in spiller (cheapest):** at REG_SEQUENCE/identity-COPY, don't count
     parts/source on top of result/dest. Local, no new pass. RISK: must fold ONLY what the
     eventual coalescer truly merges (over-folding → under-spill → missed infeasibility). Key off
     concrete patterns (REG_SEQUENCE result vs operands; identity copy whose source dies).
  2. **SSA-aware coalescer after RebuildSSA, before Spiller (most faithful to greedy):** merges
     non-interfering copies/REG_SEQUENCEs; bigger (must handle PHIs/lanes or be a focused merge).
  3. Reduce reconstruction artifacts in RebuildSSA (partial only; PHIs/lane splits inherent).
- **Recommendation:** Option 1 first (kills the spikes, low risk), evolve to Option 2 if real
  kernels still overspill. Quantify first: prototype Option 1 + measure overspill on the
  real-kernel sweep before committing.
- **TODO:** (a) add this to the spiller/coloring design doc (needs APPROVED); (b) prototype
  Option 1 and measure overspill across the sweep.

- **REFINEMENT (during-MI peak already covers most of it):** the spiller's RP is the during-MI
  peak = `max(pressure just-before MI, pressure just-after MI)` (recede + getMaxPressure); uses
  (may die) are on the "before" side, defs on the "after" side, NOT summed unless they genuinely
  co-exist (non-dying source / tied / EC). Consequences per case the user raised:
  - **Trivial copy `%x=COPY %y` (y dies): already correct, no work.** before=`…+%y`, after=`…+%x`,
    equal width → no inflation. If %y doesn't die → interfere → not coalesceable → correctly 2.
  - **REG_SEQUENCE: only inflates for PARTIAL-WIDE sources.** Full-cover, parts-dying regseq:
    before=`parts`(Σ widths) == after=`whole` → no inflation. Inflation only when a source is a
    WIDE vreg contributing just some lanes (`%rs(2)=REG_SEQUENCE %new(1), %old:sub1` with %old a
    2-unit vreg → before 3, after 2). Fix = **narrow sources to contributed lanes in the updater**
    (the MachineLaneSSAUpdater Q1 narrowing), NOT a spiller hack. If narrowing is complete,
    REG_SEQUENCE stops inflating.
  - **PHIs: liveness-charging, not coalescing overlap.** Result and sources live in DISJOINT
    regions (sources live-out of preds, result in join) → never overlap even un-coalesced. PHI
    pseudo is zero-width. Requirement: charge each PHI source to its predecessor END
    (`getMBBEndIdx(Pred)`), result to join live-ins; do NOT also count sources at the PHI slot.
    Pure liveness correctness (LIS provides it) — verify the spiller's per-block walk does this.
  - **Net:** the feared overspill is largely absorbed by during-MI peak + updater lane-narrowing.
    Residual is narrow (partial-wide sources; verify PHI pred-end charging). MEASURE to confirm:
    count kernels where SSA spills but greedy doesn't across the sweep before building anything.

## 2026-07-01 — E2E sweep round 2: 3 new SSA-RA crash buckets [BUG] [SSARA]

- Swept more test/CodeGen/AMDGPU inputs (per-kernel greedy vs `-amdgpu-ssa-regalloc
  -verify-machineinstrs`, gfx900 unless noted). All crashes are in the **SSA RA pass** (not
  RebuildSSA this time). Buckets:
  1. **Global i64 uniform/constant atomic** — `atomic_optimizations_global_pointer.ll`
     `add_i64_uniform`, `add_i64_constant`: LiveInterval assert *"Cannot overlap two segments with
     differing ValID's (did you def the same reg twice in a MachineInstr?)"* (LiveInterval.cpp:235)
     during the SSA RA. NB: the LOCAL variant of add_i64_uniform compiles fine — global addressing
     differs. Likely a double-def / interval-overlap from operand rewrite or REG_SEQUENCE lowering.
  2. **Sub-32-bit atomics (i8/i16/f16/bf16), ×8** — same file `uniform_{or,add,xchg}_i{8,16}`,
     `uniform_fadd_{f16,bf16}`: *"Illegal instruction detected: Operand has incorrect register
     class"* — 16-bit (lo16/hi16) subregister handling in SSA RA.
  3. **i64 divide** — `sdiv64.ll`, `udiv64.ll`: *"Invalid subregister index for virtual register"*.
- **Clean (compile + verify OK):** all `atomic_optimizations_{buffer,struct_buffer,raw_buffer}.ll`
  (0 crashes); `fma.f64.ll`; `idot4s.ll`, `idot8s.ll` (gfx906). Occupancy diffs where present are
  coalescing-only (same pattern as before).
- **Status:** 3 new SSA-RA bug buckets to triage/fix (double-def LI overlap; 16-bit subreg class;
  invalid subreg index). Repros via `llvm-extract` from the named files. Priority TBD.

## 2026-07-01 — STRATEGIC: 32-bit granularity validated; Bucket 2 is over-wide-vreg, not granularity [DESIGN] [SSARA]

- **Concern:** if i8/i16/f16 atomics require sub-32-bit subregisters (lo16/hi16), the whole
  32-bit-granular design (NUA, Spiller, RA) might need a from-scratch rework.
- **Investigation (gfx900):** `llvm-extract` each failing sub-32-bit kernel (`uniform_add_i8`,
  `uniform_add_i16`, `uniform_fadd_f16`, `uniform_fadd_bf16`) and compiled with GREEDY. Result:
  **all compile (rc=0) and emit ZERO 16-bit subregs** (grep `.lo16/.hi16/v.l/v.h/vgpr_16` = 0).
  Sub-32-bit types lower to **32-bit-register bit-manipulation** (v_and/v_lshl/v_bfi), not
  sub-32-bit subregs.
- **CONCLUSION: the 32-bit granularity assumption HOLDS for all current targets/tests. No
  redesign needed.** Sub-16-bit subregs (`VGPR_16` lo16/hi16) only exist under `+real-true16`
  (gfx11+), which our pipeline does NOT target — that's a deliberate, separable FUTURE scope
  decision, not an existential threat surfaced by these tests.
- **Bucket 2 reclassified:** the i8/i16/f16 "Operand has incorrect register class" crash is NOT a
  granularity issue — it's the **over-wide-REG_SEQUENCE-vreg family** (a 64-bit pointer living in
  an `sgpr_128` vreg → SSA RA colors full 128-bit → `S_LOAD_DWORD_IMM` base wants `SReg_64`).
  Pre-RA MIR: `%102:sgpr_128 = REG_SEQUENCE %100,%subreg.sub1, %106,%subreg.sub0` feeding
  `S_LOAD_DWORD_IMM`. Same class as the `%97` over-wide cases; greedy's coalescer/rewriter narrows
  it, our RA doesn't. Fixable within the 32-bit design.
- **Implication:** the paused per-lane PHI work (Approach B) is NOT undermined by a granularity
  problem — safe to resume. Bucket 2 folds into the over-wide-vreg / REG_SEQUENCE-narrowing work.

## 2026-07-01 EOD — Root-cause consolidation: 3 buckets → 2 families; Family A is a RebuildSSA bug [DESIGN] [BUG]

- **The 3 e2e crash buckets collapse into 2 root causes:**
  - **Family A — RebuildSSA over-widens reconstructed subreg-uses (CONFIRMED RebuildSSA bug, NOT a
    coalescer gap).** Covers Bucket 1 (global `add_i64_uniform` LiveInterval "def same reg twice /
    overlapping segments") + Bucket 2 (i8/i16/f16 "incorrect register class") + the already-fixed
    REG_SEQUENCE width + parallel-copy bugs.
  - **Family B — updater PHI-construction lane granularity.** Bucket 3 (`sdiv64`/`udiv64` "invalid
    subregister index") = createPHIInBlock mixing full vs per-lane PHIs. Fix = the paused per-lane
    reconciliation (Approach B).

- **DEFINITIVE evidence Family A is a RebuildSSA bug (i16 before/after RebuildSSA):**
  - `%64` is a LEGIT `sgpr_128` buffer descriptor: 4 subreg defs (`sub0=S_AND addr.lo`,
    `sub1=addr.hi`, `sub2=-1`, `sub3=61440`), consumed FULL by `BUFFER_ATOMIC_CMPSWAP %64` AND as
    `%64.sub0_sub1` (the 64-bit address) by `S_LOAD_DWORD_IMM`. NOT over-wide.
  - **Before RebuildSSA:** `%56 = S_LOAD_DWORD_IMM %64.sub0_sub1, 0, 0`  (clean 64-bit subreg use).
  - **After RebuildSSA:** `%102:sgpr_128 = REG_SEQUENCE %100,sub1, %106,sub0` (a 64-bit value in a
    128-bit class) and `%56 = S_LOAD_DWORD_IMM %102` (full 128-bit, **`.sub0_sub1` DROPPED**) →
    base wants `SReg_64` → "incorrect register class". RebuildSSA MANUFACTURED the over-wide `%102`.
  - So the malformed over-wide REG_SEQUENCEs originate in RebuildSSA, not ISel. A coalescer would
    only MASK it (greedy does). Root fix belongs in RebuildSSA.

- **Fix locus (Family A):** `rewriteDominatedUses` Case 2 (super/mixed) → `buildRSForSuperUse`
  (MachineLaneSSAUpdater.cpp ~662-688). For a use that reads a narrower subreg (`%64.sub0_sub1`) of
  a multi-subreg-def vreg, it composes the RS at the **original register width** and does
  `MO.setReg(RSReg); MO.setSubReg(0)` — over-widening + dropping the consumer's subreg. Intended
  fix: size the composed value to the **use's lane mask** (`sub0_sub1` → `sreg_64`) and/or preserve
  the consumer's subreg. NOT YET investigated at code level (next step: read buildRSForSuperUse +
  Case 2 source-first, per the check-ToT rule).

- **PAUSED — Family B / per-lane PHI reconciliation (Approach B):** design converged (sumMask +
  `\`-difference create + reuse; decompose full PHI only as narrower-vs-wider precondition; exact-
  lane reuse; dead-PHI sweep via `use_nodbg_empty`). Last patch iteration is in chat; had real
  defects the user caught (redundant post-decompose loop; bogus `SubOfNew` width test — must use
  the `countr_zero(DefMask)` namespace shift like Case 3; garbage single-lane check; compose only
  produced PHIs; member-global state should be scoped). To be reworked cleanly, in-file with
  build/test (no more paper patches). REMEMBER: verified API facts —
  `composeSubRegIndices(a,b)` requires b to be a subreg of R:a (don't misuse); `replaceRegWith`
  rewrites uses AND defs (avoid — reuse the original result vreg as the RS dest instead);
  operands get rewritten so scan `RenamedLaneDefs`, not PHI operands, to find existing lane PHIs.

- **RESUME TOMORROW:** (1) Family A — read `buildRSForSuperUse`/Case 2, confirm it over-widens +
  drops subreg, fix to size-to-use-lanes; validate on i16 + global i64 + sdiv (may also help) +
  full atomic sweep. (2) Family B — the per-lane PHI rework, once A settles. Prefer fixing A first
  (higher leverage: Buckets 1+2 + hardens fixed cases + likely removes spiller RP spikes).
  Uncommitted from prior sessions still in tree (updater rename-map + TiedOpsRewritten + 2 tests);
  commit when ready.

- **Next actions**
  - Port Part 1 (rename map) + TiedOpsRewritten fix + both regression tests to `mssa-updater`;
    run its gtests + the 4 `.mir` tests there (update CHECKs only if output legitimately changed
    — investigate, don't rubber-stamp).
  - Spiller coalescing-aware RP (Option 1) + overspill measurement (see DESIGN GAP above).

---

## Pending
_Reconciled against `git log` 2026-06-29. DONE & committed (removed from pending): Phase 0 e2e
test suite (05fcd64), Phase 1 RebuildSSA→MachineLaneSSAUpdater + dead-PHI fix (f7908c9), Phase 2
function-wide width-descending coloring (1a21fd3), the full 4-tier E2E LIT suite._

- **[NEXT] Compile-time: interval tree** for the cross-width interference query in
  `pickFreePhysReg` — replaces the O(|ColorMap|) brute-force scan from 1a21fd3 with O(log N + k)
  before large-kernel testing.
- **Unified coalescer** — ordinary REG_SEQUENCE/COPY + PHI phases; post-RA quality (reduces copies,
  not a correctness requirement).
- **Spiller tied-operand RP** fix.
- **Loop-filter fallback** — `getVMPsToSpill` TODO (~line 632).
- **reg-unit vs pressure-unit** accounting mismatch (VGPR_32 = 2 reg units but 1 pressure unit).

## 2026-07-02 — Family A fix: over-wide REG_SEQUENCE result class [BUGFIX] [SSAUPDATER]

- **Context / goal**
  - Family A crash: uniform sub-32-bit (i16) atomic lowers through the unaligned-address
    path, producing a super/mixed-lane use of a 128-bit descriptor vreg. In SSA RA
    verify: `Bad machine code: Illegal virtual register for instruction` —
    `%..:sreg_32_xm0_xexec = S_LOAD_DWORD_IMM %..:sgpr_128, 0, 0` (128-bit base where
    64-bit expected).

- **Root cause**
  - `MachineLaneSSAUpdater::buildRSForSuperUse` sized the `REG_SEQUENCE` result to
    `OrigVReg`'s **full** class (`sgpr_128`) instead of the **use's** class
    (`sub0_sub1` → `sreg_64`), and the caller cleared the operand subreg
    (`MO.setSubReg(0)`). Consumer then read an over-wide vreg → illegal reg class.

- **Fix applied** (`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`, `.h`)
  - **[BUGFIX]** Caller (Case 2 in `rewriteDominatedUses`) computes the use's class
    (`OpRC` refined by `MO.getSubReg()` via `TRI.getSubRegisterClass`) and passes it
    into `buildRSForSuperUse` (param renamed `OpRC`→`UseRC`); `Dest` created in `UseRC`.
  - **[BUGFIX]** `REG_SEQUENCE` destination subreg indices re-based from `OrigVReg`'s
    lane namespace into `Dest`'s (narrower) namespace — needed for high-slice uses
    (e.g. `sub2_sub3` → `sreg_64` only has `sub0/sub1`). No-op (shift 0) for `sub0`-based
    and full-width uses, so full-width path unchanged.
  - **[REFACTOR]** Extracted the `>> countr_zero(base)` idiom into inline
    `rebaseLaneMask(Lanes, Base)` (header), reused in the existing Subset case
    (was line 721) and the three `buildRSForSuperUse` destination sites.
  - `REG_SEQUENCE` is a single full def — no partial defs introduced; the immediates
    are structural destination-slot subreg indices.

- **Results / verification**
  - Old `llc` (pre-rebuild binary) aborts on the repro with the exact signature above.
  - Rebuilt `llc`: repro compiles, passes `-verify-machineinstrs`; illegal load now
    `s_load_dword s7, s[4:5], 0x0` (proper 64-bit base).
  - **[TEST]** New regression test
    `llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/rebuildssa-superuse-regseq-result-class.ll`
    (uniform i16 atomicrmw, gfx900, iterative + ssa-regalloc + verify).
  - Suites: SSARA (all pass), SSASpiller (all pass), updater `.ll` (3/3 pass).
    Pre-existing failures: 4 `.mir` updater tests use `-run-pass=test-machine-lane-ssa-updater`,
    which isn't registered in this build (not caused by this change).

- **Follow-up fix: misaligned wide SGPR slice (uniform_fadd_f16)**
  - After the initial narrowing fix, `uniform_fadd_f16` hit
    `Cannot create register without RegClass!` — a use reads `%45.sub1_sub2_sub3:sgpr_128`
    (96-bit at a sub1 offset). `getSubRegisterClass(sgpr_128, sub1_sub2_sub3)` = null
    (SGPR tuple alignment forbids a misaligned 96-bit slice).
  - **[BUGFIX]** Fix: the RS result is a *fresh whole* register with no offset
    constraint, so size it from the **sub0-aligned** mask:
    `UseRC = getSubRegisterClass(OpRC, getSubRegIndexForLaneMask(rebaseLaneMask(OpMask, OpMask)))`
    → `SGPR_96`. `buildRSForSuperUse` unchanged (already re-bases dest indices).
    Catenation: `%dest:sgpr_96 = REG_SEQUENCE %75(new sub1), sub0, %45.sub2_sub3, sub1_sub2`;
    consumer reads `%dest` whole (fits the sub1_sub2_sub3 slot). No partial def.

- **Sweep result (gfx900, atomic_optimizations_global_pointer.ll, per-function, SSA RA pipeline)**
  - 22 funcs → **19 pass, Family A = 0** (was the whole i8/i16/f16/bf16 bucket).
  - Remaining: 2 Bucket-1 (`add_i64_constant`, `add_i64_uniform`: LiveInterval
    "overlap two segments / def the same reg twice"); 1 new sub-bucket —
    `uniform_fadd_f16` now advances past the updater but leaves a **virtual-register
    COPY** that reaches post-RA `MachineCopyPropagation`
    (`should be run after register allocation!`). Distinct RA/destruct leftover, NOT
    Family A. Other 5 atomic_optimizations_*.ll files: all pass whole-file.

- **Bucket 1 RESOLVED — genuine UPSTREAM `SplitCriticalEdge` subrange bug (not ours).**
  `add_i64_uniform`/`add_i64_constant` crash (`LiveInterval.cpp` "Cannot overlap two
  segments with differing ValID's") was root-caused to core LLVM
  `MachineBasicBlock::SplitCriticalEdge`: its PHI-source `LiveIntervals` update loop
  extends a PHI-source register's **subranges** using the **parent** range's `VNInfo`
  instead of each subrange's own (`SR.getVNInfoAt(PrevIndex)`). The sibling
  live-through loop does it correctly — clear asymmetry. When the reg is live-through
  the freshly-inserted split block (any PHI source becomes so after its edge is
  split) the subrange already covers `[Start,End)`, so re-adding with the parent
  valno overlaps a foreign-valno segment → assert.
  - **Reproduced on clean upstream** (`main @ 4f06fa92b6cf`), stock passes, no
    downstream code: `llc -run-pass liveintervals,phi-node-elimination` on a MIR whose
    PHI sources are `%r.sub0/%r.sub1` of a subrange-carrying vreg live-out past the PHI
    (forces `PHIElimination` `ShouldSplit`). Crash in `PHIElimination::SplitPHIEdges`
    → `SplitCriticalEdge` (MachineBasicBlock.cpp:1351). The existing upstream test
    `split-mbb-lis-subrange.mir` uses the same `-run-pass` line but doesn't crash
    because its PHI sources are separate 32-bit vregs (no subranges).
  - **Debugger evidence:** at the failing add, subrange `L0003 = [144r,240B)` valno
    `0x…dc0` (subrange's own) vs new `[232B,240B)` valno `0x…dd0` (parent's) — distinct
    `VNInfo` objects, both print `0@144r`. `isLiveInToMBB(%96,succ)=false` (proper PHI
    source). Value numbering is correct; the bug is purely the parent-valno reuse.
  - **Two distinct issues untangled:** (1) the upstream `SplitCriticalEdge` bug above;
    (2) our `lowerPHIs` also *over-splits* forward-triangle critical edges that don't
    need splitting (upstream PHIElimination places the copy in the pred instead), which
    additionally trips (1). Fixing (1) resolves the crash; (2) is a separate quality
    item (still worth: don't split unless `isLiveOutPastPHIs && !isLiveIn`).
  - **[BUGFIX] Fix applied to trunk** (`/work/.../llvm-project`, branch
    `fix-splitcriticaledge-subrange-vninfo`, MachineBasicBlock.cpp:1351): subrange loop
    now uses `SR.getVNInfoAt(PrevIndex)` (guarded), mirroring the live-through loop.
    Rebuilt `llc`; reproducer no longer asserts (`-verify-machineinstrs` clean, edge
    split + PHIs lowered correctly). `check-llvm` running.
  - Artifacts in `bugs/SSARA/`: `repro.mir`, `BUG-splitcriticaledge-subrange-vninfo.md`,
    `cfg.svg`/`cfg.png`, polished collaborative email draft (`email.src.md`). Plan:
    consult the PR author (#69429, added the subrange handling) before opening a PR.

- **ssara-side fixes: lowerPHIs split-only-if-necessary + resolvePermutation tier order [BUGFIX]**
  - **[BUGFIX] lowerPHIs no longer splits every critical edge.** New helper
    `edgeCopiesNeedSplit(Pred, MBB, Copies)`: a critical edge is split only when a
    copy *destination* reg unit is live into a sibling successor (would clobber it).
    A permutation cycle does NOT force a split — resolvePermutation's scratch is
    above the high-water mark (free on all edges) and V_SWAP/XOR touch only the copy
    destinations. Single ColorMap pass filtered by a cheap reg-unit bit-test before
    the liveAt query. Result: `add_i64_uniform`/`add_i64_constant` (VGPR0<->VGPR1
    swap on a triangle edge, dead on sibling) resolve **in the predecessor, no
    split** → the i64 atomics compile without needing the SplitCriticalEdge port in
    the ssara tree. (Necessary splits, e.g. nested-loop SGPR cycle, still split.)
  - **[BUGFIX] resolvePermutation tier order.** Was scratch-first even when V_SWAP
    available → dead `v5=v1` save copy after peephole + wasted scratch. Now the
    scratch tier is gated `!(IsVGPR && ST->hasSwap())`: VGPR cycles on gfx9+ use
    `V_SWAP_B32` (clean, single instr); SGPR cycles keep scratch (emitSwap is
    VGPR-only — `V_SWAP_B32`/`V_XOR_B32_e64`; there is no scalar swap). Confirmed via
    debug+asm: `add_i64_uniform` → `v_swap_b32 v1, v0`, no dead mov.
  - **[TODO] SGPR cycle under register pressure** (scratch not occupancy-free) has no
    correct lowering — falls into VGPR-only emitSwap → illegal. Needs an `S_XOR_B32`
    scalar triplet fallback gated on SCC being dead (S_XOR writes SCC). Code TODO in
    resolvePermutation tier 2/3 + worklog TODO. `S_XOR_B32`/`_B64` exist (SOPInstructions.td).
  - **[TEST]** New `SSARA/lowerphi-critical-edge-no-split.ll` (no-split swap-in-pred).
    Updated `destruct-swap/cycle3/mixed.mir` CHECKs from scratch-COPY to `V_SWAP_B32`
    (intended gfx1200 lowering). Coverage: V_SWAP (gfx1200/gfx900), V_XOR no-swap
    (fiji, destruct-wide-swap), SGPR scratch (nested-loop). Gaps tracked: VGPR
    no-swap occupancy-free scratch; SGPR-under-pressure. SSARA+SSASpiller+updater .ll
    suites: 84/84 green.
    - **NOTE (2026-07-03, corrected):** after the S_XOR fallback landed, the
      nested-loop SGPR cycle now resolves via **S_XOR** (SCC dead there), NOT scratch
      — so the "SGPR scratch (nested-loop)" claim above is superseded. Empirical scan
      of every `-amdgpu-ssa` test: the SGPR *scratch* branch (`cycle via scratch
      SGPR`, i.e. `UseScratch = !SccDead` with SCC **live**) is hit by **zero** tests.
      Reaching it needs a successor that reads SCC (e.g. `S_CBRANCH_SCC1`). Genuinely
      uncovered — see next actions.
    - **[TEST] (2026-07-03) Gap CLOSED:** added `SSARA/destruct-sgpr-scratch.mir`.
      Loop latch computes the back-edge SGPR swap, then `S_CMP` sets SCC consumed by
      `S_CBRANCH_SCC1`; cycle copies are inserted between them, so `S_XOR` (writes SCC)
      would corrupt the branch condition → `resolvePermutation` uses scratch COPYs
      (`cycle via scratch SGPR3`, no split — exit uses a separate reg `%6`).
      `-verify-machineinstrs` clean. This pins the SGPR-scratch (`UseScratch=!SccDead`,
      SCC live) tier — the last unexercised branch of the cycle-resolution decision.
      SSARA+SSASpiller: 85 pass, 2 XFAIL.
  - **[TEST] Test hygiene: removed embedded `target-cpu` attribute from 67 SSARA/
    SSASpiller/updater tests.** The MIR/IR function attribute `"target-cpu"` silently
    *overrides* the RUN line `-mcpu` (discovered while debugging: `destruct-swap.mir`
    pinned `gfx1200` and ignored `-mcpu=fiji`). Stripped the key so RUN `-mcpu` is
    authoritative; 20 files whose only attr was `target-cpu` also had the emptied
    `attributes #N = { }` group + `#N` ref removed (empty attr group is invalid IR).
    Sibling attrs (e.g. `amdgpu-num-vgpr`) preserved. Exposed one mislabeled test —
    `SSASpiller/spill-dom-groups-a.mir` (RUN `gfx900` but attr forced `gfx1200`, a
    crash-only no-FileCheck test); it now honestly runs `gfx900`. All previously
    passing tests still green (only the 4 pre-existing `test-machine-lane-ssa-updater`
    unregistered-pass `.mir` fail).

## 2026-07-03 — E2E re-sweep: global atomics 21/22, only Family A remains [BUG] [SSARA]

- **Context / goal**
  - Re-run the per-kernel sweep on `atomic_optimizations_global_pointer.ll` (22 kernels,
    gfx900, `-mattr=-flat-for-global -amdgpu-atomic-optimizer-strategy=Iterative
    -amdgpu-ssa-regalloc -verify-machineinstrs`, each kernel `llvm-extract`ed) to see
    current state and check for regressions from the recent swap/lowerPHIs work.

- **Results / discoveries**
  - **21/22 OK. Only `uniform_fadd_f16` fails** — and it's the already-root-caused
    **Family A** unaligned wide SGPR `REG_SEQUENCE` slice bug: SSA-RA output contains
    `$noreg = COPY $sgpr4_sgpr5` and `$noreg = COPY $sgpr4_sgpr5_sgpr6`
    (`getSubReg(Dst, sub1_sub2[_sub3])` → `NoRegister`), which later trips
    `MachineCopyPropagation.cpp:889` assert (`RegDef/RegSrc must be physical`). NOT new.
  - **Previously-failing buckets are now GREEN** (vs 2026-07-01 round-2 sweep):
    - Bucket 1: `add_i64_uniform`, `add_i64_constant` → OK.
    - Bucket 2 (sub-32-bit): `uniform_{or,add,xchg}_i{8,16}`, `uniform_fadd_bf16`,
      `uniform_fadd_v2f16`, `uniform_fadd_v2bf16` → all OK.
  - **No new failures introduced.** Sibling files whole-file clean:
    `atomic_optimizations_{local_pointer,buffer,struct_buffer,raw_buffer}.ll`.

- **Decision / next**
  - The single remaining global-atomics crash == the tracked Family A fix (decompose
    unaligned wide SGPR slice into aligned addressable sub-registers in
    `eliminateRegSequences`/`rewriteOperands`). Everything else from the atomics sweep
    is resolved.

- **Next actions**
  - ~~Bucket 1 (lowerPHIs SplitCriticalEdge overlap)~~ **RESOLVED** (see "Bucket 1
    RESOLVED" above): root cause was the upstream `SplitCriticalEdge` subrange-VNInfo
    bug (fix on branch `fix-splitcriticaledge-subrange-vninfo`), and the ssara side no
    longer hits that path (lowerPHIs split-only-if-necessary + SGPR S_XOR fallback,
    completed 2026-07-03). Remaining Bucket-1 work is *upstream only*: consult PR
    #69429 author, then open the PR for the `SplitCriticalEdge` fix.
  - Bucket 3 (sdiv64 invalid subreg) still open in AMDGPUSSARegisterAllocator
    SSA-destruct.
  - **[TODO][BUG] Root-caused — SSA-RA unaligned SGPR REG_SEQUENCE slice.**
    `uniform_fadd_f16`: after the SGPR_96 updater fix, the allocator colors
    `%73:sgpr_128 → SGPR4_5_6_7` and `%76:sgpr_96(=RS result) → SGPR4_5_6`. The
    consumer `%73 = REG_SEQUENCE %72, sub0, %76, sub1_sub2_sub3` (the `sub1_sub2_sub3`
    *dest slot* pre-exists in ISel output; updater only rewrote the source).
    `eliminateRegSequences` (AMDGPUSSARegisterAllocator.cpp:595) computes
    `Expected = TRI->getSubReg(Dst, SubIdx)` = `getSubReg(SGPR4_5_6_7, sub1_sub2_sub3)`
    = **NoRegister** — AMDGPU SGPR tuples are alignment-constrained, so *unaligned*
    wide SGPR sub-tuple indices (`sub1_sub2`, `sub1_sub2_sub3`) have no physical
    sub-register. Result: `$noreg = COPY $sgpr4_5_6` → post-RA MachineCopyPropagation
    assert. Two `$noreg` copies observed (both sub1-based).
    **Locus:** SSA-RA `eliminateRegSequences` + `rewriteOperands` (getSubReg line 511)
    assume `getSubReg(Dst/Src, SubIdx)` always succeeds. Fix: when it returns 0,
    decompose the slice into aligned addressable sub-registers (down to sub0-granular
    copies). **Independent of the updater** — same RS would fail without it.
  - Port patch + test to `mssa-updater` worktree.
  - **[TEST][TODO]** Keep MachineLaneSSAUpdater **unit tests** (`CodeGenTests`) in sync:
    `MachineLaneSSAUpdaterTest.cpp` + `MachineLaneSSAUpdaterSpillReloadTest.cpp` currently
    fail to compile — they call the stale 2-arg `repairSSAForNewDef(MI, Reg)` while the
    API is 3-arg `repairSSAForNewDef(MI, Reg, SmallVectorImpl<MachineOperand*>&)`
    (8 call sites). Pre-existing bit-rot, not from the Family A fix. Update call sites
    and re-enable in CI.

## 2026-07-03 — SGPR permutation-cycle S_XOR swap: coverage tests [TEST] [SSARA]

- **Context / goal**
  - The refined `emitSwap` (SGPR cycles broken in place with the widest scalar XOR:
    `S_XOR_B32` / `S_XOR_B64`, plus 64+32 decomposition for odd-dword widths) had
    **no lit coverage** — every existing destruct/swap test used VGPRs (V_SWAP /
    scratch). Fill the gap.

- **Verification method**
  - Probed candidate MIR via `llc -run-pass=amdgpu-ssa-register-allocator` from
    `/tmp` (never wrote temp files under `llvm-project`) to capture real output
    before writing CHECK lines, so the tests assert *correct* expected behavior
    rather than being back-fitted to output.

- **Results / discoveries**
  - SGPR 2-cycle with SCC dead at the branch routes to `emitSwap` (not scratch),
    because `resolvePermutation` sets `UseScratch = !SccDead` for SGPRs (S_XOR
    writes SCC, so scratch is only used when SCC is live). Confirmed at all widths:
    - **32-bit** → one `S_XOR_B32` triplet.
    - **64-bit** → one `S_XOR_B64` triplet (widest scalar XOR for a 64-bit chunk).
    - **96-bit** → aligned 64-bit chunk (`S_XOR_B64` on `sub0_sub1`) + trailing
      32-bit chunk (`S_XOR_B32` on `sub2`). Allocator colors the two sgpr_96
      operands to `SGPR0_1_2` / `SGPR4_5_6` (skips SGPR3 for alignment).

- **Tests added** (all `-mcpu=gfx1200`, `-run-pass=amdgpu-ssa-register-allocator`)
  - **[TEST]** `SSARA/destruct-sgpr-swap.mir` — 32-bit `S_XOR_B32` triplet.
  - **[TEST]** `SSARA/destruct-sgpr64-swap.mir` — 64-bit `S_XOR_B64` triplet.
  - **[TEST]** `SSARA/destruct-sgpr96-swap.mir` — 96-bit 64+32 decomposition
    (`S_XOR_B64` + `S_XOR_B32`). CHECK pins physregs (sgpr0/4/6) so it is
    coloring-sensitive; accurate for the current allocator.
  - All modeled on `destruct-swap.mir` (diamond CFG, two cross-referencing PHIs).

- **Suite result**
  - SSARA + SSASpiller: **83 pass** (was 80, +3), 2 XFAIL, no regressions.
  - (The 4 `MachineLaneSSAUpdater/*.mir` failures remain pre-existing:
    `test-machine-lane-ssa-updater` run-pass is not registered in the `ssara`
    build — unrelated to this change.)

- **Next actions**
  - Optional: SCC-*live* SGPR-cycle test to cover the scratch branch of the same
    decision (currently only the S_XOR branch is pinned).

## 2026-07-03 — lowerPHIs critical-edge split: positive test + rename [TEST] [SSARA]

- **Context / goal**
  - `lowerPHIs` edge splitting had only a *negative* test
    (`lowerphi-critical-edge-no-split.ll`). The *positive* (split-required) path was
    exercised only incidentally by `rebuildssa-nested-loop-i64.ll` and
    `pipeline-spill-diamond.ll` — neither asserts the split in its CHECKs. Genuine
    coverage gap.
  - Also: `destruct-swap-noswap-scratch.mir` had a misleading name (it is about the
    *scratch* cycle-resolution tier, not "swap vs no-swap").

- **Results / discoveries**
  - Confirmed (via `-debug-only` scan of all `-amdgpu-ssa` tests) that only those two
    `.ll` tests hit `edgeCopiesNeedSplit → SplitCriticalEdge`, and only as a
    side-effect (no split-asserting CHECKs).
  - Built a minimal positive repro: a critical edge `bb.1→bb.3` where the PHI-result
    color (VGPR0) is also live into the sibling `bb.2` (via `%0`), so the edge copy
    `VGPR0 = COPY VGPR1` would clobber it at `bb.1`'s terminator. `lowerPHIs` splits
    the edge into a fresh block (`bb.4`) that carries the copy; sibling `bb.2` keeps
    `$vgpr0` unclobbered. Verified: coloring `%0/%2/%3→VGPR0`, `%1→VGPR1`.

- **Changes applied**
  - **[TEST]** Added `SSARA/lowerphi-critical-edge-split.mir` — positive counterpart;
    asserts the split block + isolated copy (gfx900, run-pass).
  - **[REFACTOR][TEST]** Renamed `SSARA/destruct-swap-noswap-scratch.mir` →
    `SSARA/destruct-cycle-scratch.mir`; internal fn + CHECK-LABEL
    `test_destruct_swap_noswap_scratch` → `test_destruct_cycle_scratch`. Content
    otherwise unchanged.

- **Suite result**
  - SSARA + SSASpiller: **84 pass** (was 83, +1 net: +split test, rename is neutral),
    2 XFAIL, no regressions.

## 2026-07-04 — MachineLaneSSAUpdater redesign: VNInfo-driven reconstruction (Bucket 3) [DESIGN] [BUGFIX] [MSSA-UPDATER]

Plan file: `~/.cursor/plans/vninfo-driven_lane_ssa_aaab8fb3.plan.md`.

- **Root cause (Bucket 3, sdiv64/udiv64 + c3/c6):** the updater decided "which value
  reaches a use/PHI-operand" by **block-dominance + WorkList order + operand-name scan**
  — unsound. `findRenamedReachingDef` also failed because it checks the *in-flight*
  renamed vreg's liveness, which doesn't exist mid-repair (chicken-and-egg). Proven via a
  probe study: `OrigVReg`'s (old) LiveInterval subrange VNInfos give the correct reaching
  def on every edge, incl. the crashing cases; `IDF == {isPHIDef VNI blocks}`.

- **KEY DESIGN DECISIONS (converged after long discussion):**
  1. **VNInfo-driven oracle.** Decide ownership by reaching-VNInfo identity, read from a
     **frozen deep copy of OrigVReg's LI** taken at session start (renames strip renamed
     defs' VNInfos from the live LI → must query the frozen copy). `collectReachingVNIs` /
     `reachingVNIForLaneGroup` + `renamedForReachingVNI` (VNI def-slot → `DefInstrToRenamed`
     `{vreg, OrigLanes}`; null for PHI-def/unrenamed → OrigVReg placeholder patched later).
  2. **SSAUpdaterImpl is out** — not lane/subreg aware (fundamental; user tried it before).
  3. **Approach A: one PHI per subrange** (single-source operands, placeholder-patch; NO
     per-edge REG_SEQUENCE). Rejected approach B (multilane PHI + edge-RS) because edge-RS
     can't be incrementally patched (unresolved piece) and hits unaligned-subreg bugs;
     extra PHIs are coalescer-pruned. Granularity is data-driven (follows subranges), so it
     auto-adapts to true16 / 8-bit / VReg_1024.
  4. **Reload = re-def (option 3).** Spiller will emit stores + **reload-redefs of OrigVReg**
     (SSA-violating) and a **2nd RebuildSSA** reconstructs — spiller carries ZERO SSA-repair
     code (~1000-1100 LOC deletable), same reaching path fixes both. Pipeline:
     `RebuildSSA → Spiller(breaks SSA) → RebuildSSA → Allocator`. Compile-time == per-reload
     repair (one LI recompute vs many). This also lets **IDF be dropped entirely** later
     (PHI placement from OrigVReg's isPHIDef VNIs — unconditional once reloads are re-defs).
  5. **LIS is a hard requirement** — no `if(!LIS)` fork.
  6. **Integration = option 1 (incremental)** with a **transient `UseReachingOracle` gate**:
     rebuild path uses the new oracle; spiller keeps legacy `createPHIInBlock`/dominance
     until its option-3 redesign, then the gate + legacy path + `repairSSAForReload` +
     `insertPHIAtBlock` are deleted. End state == one sound path, spiller SSA-free.

- **Implementation status (Steps 1-5 done, gated, compiles):** in
  `MachineLaneSSAUpdater.{h,cpp}`. New: `FrozenOrigLI`/`FrozenAlloc` snapshot,
  `DefInstrToRenamed`, `LanePHIs` dedup, `collectReachingVNIs`,
  `reachingVNIForLaneGroup`, `renamedForReachingVNI`, `createPHIInBlockReaching`,
  `rewriteUseReaching`; `insertLaneAwarePHI` returns `{op,lane}` pairs (threads per-PHI
  lane so subreg rebasing uses the PHI's real coverage, not the whole DefMask — that was a
  bug found & fixed: `%5.sub1` on a 32-bit reg). PHI-result ownership matches the frozen
  PHI-def VNInfo **by block** (not instr slot). No `PHILane` side-map (rejected; lane
  threaded via return).
- **Test results:** permutation set **c1..c7 ALL PASS** (incl. previously-crashing c3/c5/c6);
  **`s_test_sdiv` (Bucket 3) FIXED**. Probe MIRs in `/tmp/perm/c*.mir`.
- **REMAINING (next):** `v_test_sdiv` (VGPR i64 divide, SI `Flow` control-flow blocks) still
  fails in the reaching path: degenerate dead PHIs (`%495 = PHI %484.sub1, %484.sub1` —
  same value both edges → should be elided), `PHI operand not live-out`, `reading vreg
  without a def`, `defs don't dominate uses`. All in v_test_sdiv; likely redundant-PHI
  elision + operand resolution across Flow-lowered edges. Then: udiv64, SSARA/SSASpiller/
  updater suites, atomics sweep, IDF-drop cleanup, option-3 spiller redesign, remove gate.
- **Workflow:** step-by-step in-editor review; user presses Accept + says "go on" (agent
  does NOT perceive the Accept button). Probe instrumentation was reverted; changes are
  substantial and UNCOMMITTED (user commits manually).

### 2026-07-05 – v_test_sdiv reaching-path fix: drop IDF, place PHIs from frozen PHI-def VNInfos [BUGFIX] [DESIGN] [SSAUPDATER]

- **Context / goal**
  - Resume: `v_test_sdiv` (VGPR i64 divide, SI `Flow` blocks) still crashed in the RebuildSSA
    reaching path with a degenerate dead PHI + undefined operand.

- **Root cause (diagnosed)**
  - Repair session for the full def `%484:vreg_64 = IMPLICIT_DEF` in bb.3 (`DefMask=0xF`).
  - `insertLaneAwarePHI` called `computePrunedIDF` **once** with the full mask. Because
    `DefMask == full`, pruning used the **main** interval liveness (union of all lanes), so
    the `Flow` block (bb.1) qualified. That single IDF block set was then applied to **every**
    lane group (sub0 *and* sub1).
  - `%484` sub1 is **never used** anywhere (only a dead def in bb.3), so its PHI was dead. With
    no renamed reaching def on either edge, both operands fell back to the unrenamed `%484.sub1`
    placeholder → after renaming, `%484` has no def → `dead %495 = PHI %484.sub1, %484.sub1`
    ("reading vreg without a def", "not live-out", "defs don't dominate uses").
  - Abort mechanism: `createAndComputeVirtRegInterval(OrigVReg)` failed on the malformed PHI;
    `LiveRangeCalc::findReachingDefs` force-runs `MF.verify()`, which surfaced all 7 errors
    (incl. spurious `NoPHIs` — that property is only reset at `AMDGPURebuildSSA.cpp:167`, after
    the repair loop, so it's collateral, not a real bug).

- **Fix applied (APPROVED)** — `MachineLaneSSAUpdater.cpp::insertLaneAwarePHI`
  - **[DESIGN]** Reaching (full-rebuild) path no longer computes an IDF at all. `LiveIntervalCalc`
    already recorded the exact per-lane join points as `isPHIDef()` VNInfos in the frozen interval
    (`FrozenOrigLI`), which preserves each VNInfo's def `SlotIndex` + `isPHIDef` flag. Those markers
    **are** the pruned IDF. New logic: for each frozen subrange intersecting `DefMask`, iterate
    `valnos`, and for each `isPHIDef()` VNI place a PHI at `LIS.getMBBFromIndex(VNI->def)` for that
    lane (fallback to main range + `DefMask` when no subranges). Dead lanes have no PHI-def VNI →
    no PHI, automatically. `createPHIInBlockReaching` dedups via `LanePHIs` so multi-def sessions
    don't duplicate.
  - **[REFACTOR]** `computePrunedIDF` kept ONLY for the legacy spiller path (reload defs aren't in
    `OrigVReg`'s interval, so PHI-def VNInfos can't drive placement there). Moved its call + debug
    dump out of the shared prologue into the legacy branch.
  - Note on `DefBlocks`: stays `{InitialDefBB}` — the new def writes all of `DefMask` ⊇ every lane
    group, so it's a correct seed for each lane; per-lane distinction only affects LiveIn pruning
    (now moot since IDF dropped from this path).

- **Results / discoveries**
  - `v_test_sdiv` RebuildSSA now **verifies clean** (`-run-pass=amdgpu-rebuild-ssa
    -verify-machineinstrs`); dead sub1 PHI gone, only legitimate merge PHIs remain.
  - Regression sweep: **perm c1..c7 ALL PASS**, **udiv64 full codegen OK**, **SSARA lit 45/45 PASS**.
  - **NEW downstream failure uncovered** (was previously masked by the earlier crash): full `sdiv64`
    codegen now reaches SSA-destruction and aborts in
    `AMDGPUSSARegisterAllocator::lowerPHIs` (`AMDGPUSSARegisterAllocator.cpp:588`,
    `SplitCriticalEdge` on the critical edge `bb.0 → bb.1(Flow)`): LiveInterval `addSegment`
    assert "Cannot overlap two segments with differing ValID's (did you def the same reg twice)".
    This is a distinct bug in the critical-edge-split / LiveInterval-update path of SSA destruct,
    NOT in RebuildSSA/MachineLaneSSAUpdater.

- **Downstream fix (same session)** — `MachineBasicBlock::SplitCriticalEdge` subrange valno bug
  - **[BUGFIX]** The critical-edge split during SSA destruction (`AMDGPUSSARegisterAllocator::lowerPHIs`,
    edge `%bb.0 → %bb.1(Flow)`) asserted `addSegment` "Cannot overlap two segments with differing
    ValID's". Root cause: in `MachineBasicBlock.cpp` the PHI-source LiveInterval update loop added
    the **parent** interval's `VNInfo` to every subrange (`SR.addSegment(Seg(Start,End, VNI))`),
    while the sibling **live-through** loop correctly used the subrange's own
    `SR.getVNInfoAt(PrevIndex)`. When a subranged PHI source is *live through* the split block, the
    subrange already has a segment (its own valno) spanning the renumbered NMBB region, so overlaying
    the foreign parent valno collides. Our rebuilt i64 PHI sources in `v_test_sdiv` are exactly such
    live-through subranged regs.
  - **Fix:** mirror the live-through loop — use `SR.getVNInfoAt(PrevIndex)` per subrange (guarded).
    This is a **core LLVM** fix (not AMDGPU); made yesterday, not yet upstreamed.
  - **Merge strategy (decided):** keep it as an ISOLATED commit touching only `MachineBasicBlock.cpp`
    with only this hunk. When the same fix lands in trunk, an identical isolated change auto-resolves
    on merge (both sides identical vs base → no conflict) and is dropped as already-applied on rebase
    (patch-id). Enable `git rerere` as insurance; worst case `git revert` the isolated commit before
    pulling. Do NOT bundle it into a larger SSA-RA commit (guarantees hand-resolve).

- **Results after BOTH fixes:** `v_test_sdiv` fully fixed. **sdiv64 + udiv64 full codegen PASS**
  (`-amdgpu-ssa-regalloc -verify-machineinstrs`); **SSARA lit 45/45**; perm c1..c7 pass. Bucket 3
  (sdiv64/udiv64) now green end-to-end.

- **Next actions**
  - Continue option-3 spiller redesign; remove `UseReachingOracle` gate + legacy IDF/`createPHIInBlock`
    path once spiller is unified; port both fixes to mssa-updater/ssa-rebuilder; atomics sweep;
    broader AMDGPU codegen regression run.
  - Two separate isolated commits to make (user commits manually): (1) MachineLaneSSAUpdater reaching
    per-lane PHI-def placement (drop IDF from reaching path); (2) MachineBasicBlock SplitCriticalEdge
    subrange valno fix.

### 2026-07-05 – Triage tooling + visibility convention [FEATURE] [CFG-VIEWER]

- **[FEATURE]** New `scripts/mir2cfg.py`: GDB-free viewCFG-style renderer. Parses YAML MIR
  (`llc -stop-before/-stop-after -o dump.mir`), MachineVerifier crash dumps, or stdin; emits a
  Graphviz graph (one node per block with full MIR, edges = successors) to png/pdf/svg via `dot`.
  `mir2cfg.py <file|-> --function NAME --out /tmp/x.png`. Verified on `max_i64_varying`.
- **Replaces** the abandoned `llvm-cfg-viewer/` Cursor extension + `python/llvm_gdb_helpers.py`
  (`viewCFG`/`viewCFGOnly` gdb commands calling `MF->viewCFG()`). That tool was fragile: needed a
  live interactive gdb session with MF in scope, the Cursor webview + /tmp watcher, and a hard-coded
  `scripts/view-cfg.sh` converter. mir2cfg needs none of that (no debug build, no breakpoints).
- **[DESIGN]** New always-apply rule `.cursor/rules/bug-triage-visibility.mdc`: during MIR triage,
  surface CFG (inline PNG via mir2cfg), key MIR (defs/PHIs/uses of the vreg), trimmed verifier/assert
  output, and a one-line hypothesis in the VISIBLE response (user can't see hidden reasoning). No
  abstract mermaid for MIR CFGs.
- Also added `.cursor/rules/commit-message-no-double-quotes.mdc` (broadened to avoid `"`, backtick,
  `$`, unbalanced `'`; prefer here-doc `-F -`), after a backtick in a commit message triggered shell
  command substitution and silently dropped a phrase.
- Added `.cursor/rules/bug-triage-visibility.mdc` (surface CFG/MIR/errors/hypothesis in visible chat)
  and `.cursor/rules/stop-and-present-before-fix.mdc` (root-cause discovery is a STOP-and-present
  point; present patch in chat, apply only after explicit approval; every source edit, no size
  exception). mir2cfg later gained `-H`/highlight and `-a RENAMED=ORIGIN` rename-context annotation +
  deduped successor edges (the `successors:` line lists each succ twice: hex weight `;` then %).

### 2026-07-05 – max_i64_varying: early-clobber slot mismatch in reaching use-rewrite [BUGFIX] [SSAUPDATER]

- **Context:** `rebuildssa-loop-i64-reduction.ll` (`@max_i64_varying`, atomic i64 reduction loop,
  `-amdgpu-atomic-optimizer-strategy=Iterative`) aborted in AMDGPU Rebuild SSA. Real error (rest were
  the usual mid-rebuild forced-verify collateral, incl. the V_WRITELANE tied-def which yesterday's MF
  attribute already handles): `Reading virtual register without a def` on
  `%128 = REG_SEQUENCE %127, %subreg.sub2, %70.sub0_sub1, %subreg.sub0_sub1`.
- **Root cause:** `%70` (sgpr_128) is rebuilt from 3 partial defs — `sub0_sub1` (a 2-lane group),
  `sub2`, `sub3` — then used full (BUFFER_STORE), recomposed via a REG_SEQUENCE chain. The `sub0_sub1`
  def is **early-clobber** (`S_LOAD_DWORDX2_IMM_ec`). In `rewriteUseReaching`, ownership matched the
  reaching VNInfo with `V->def == LIS.getInstructionIndex(*DefMI).getRegSlot()`. An early-clobber
  def's VNInfo sits at the **early-clobber slot** (`Ne`), but `getRegSlot()` returns the regular slot
  (`Nr`) → `Ne != Nr` → the def owned no lanes → its placeholder use `%70.sub0_sub1` was never patched
  to the renamed `%129`. The `sub2`/`sub3` defs are plain `S_MOV_B32` (regular slot) so they matched.
- **[BUGFIX]** `rewriteUseReaching`: keep exact-slot equality but make it early-clobber-aware —
  `DefSlot = LIS.getInstructionIndex(*DefMI).getRegSlot(EC)` where `EC` = the NewSSA def operand's
  `isEarlyClobber()`; then `V->def == DefSlot`. (First cut used `SlotIndex::isSameInstr`, but that
  matches ANY slot on the instr; reviewer noted it could misfire if one instruction defines two
  lane-groups of the same vreg with mixed EC/normal slots — the exact EC-aware slot is precise and
  avoids that ambiguity.)
- **Results:** `rebuildssa-loop-i64-reduction.ll` passes; sdiv64/udiv64 OK; SSARA 45/45; no
  regressions. MachineLaneSSAUpdater suite: only the 4 stale `test-machine-lane-ssa-updater` harness
  tests remain (unregistered pass — infra, not correctness).
- **Next:** re-wire/retire the 4 harness tests; audit other exact-slot `V->def ==` comparisons in the
  file for the same early-clobber blind spot; continue spiller redesign / gate removal.
- Three isolated commits pending (user commits manually): (1) reaching per-lane PHI-def placement;
  (2) SplitCriticalEdge subrange valno (core, has upstream test); (3) this early-clobber isSameInstr fix.

### 2026-07-05 – Legacy dead-code cleanup, Stage A: spiller [REFACTOR] [SPILLER]

- **Context / goal:** After the Option-3 (reload-as-redef + inline reaching-VNI repair) redesign
  stabilized, the old dominance/dom-group/IDF reload path in `AMDGPUSSARegisterSpiller` became fully
  orphaned. Deleting it to leave a single unified reload path.
- **Verification before deletion:** `rg` for callers proved the cluster's entry points
  (`processPIdfBlock`, `processKillDominatedGroups`, `reloadAtEnd`) have **no live callers**; the whole
  set was internally self-referential dead code. Live path is intact:
  `emitReloadsAndRepairSSA` (called at processFunction) → `getOrCreateReloadInBlock` /
  `insertReloadForUse` + `optimizeReloadPlacing` + `canHoistReloadTo`.
- **[REFACTOR] Removed (defs + `.h` decls):** `emitReloadToReg`, `fixPathologicalPHIs`,
  `processPIdfBlock`, `processKillDominatedGroups`, `processKillDominatedGroupsWithList`, `emitReload`,
  `repairSSAForReload` (spiller wrapper), `reloadBefore`, `reloadAtEnd`, plus the now-unused static
  debug helper `getRegNameForDebug`.
- **Results:** `LLVMAMDGPUCodeGen` builds clean (no unused-function warning). Lit
  `SSASpiller`+`SSARA`: **86 passed, 1 XFAIL, 0 regressions** (87 total). Working state was committed
  green before this stage; each function deleted individually so a tool/shell hang could never leave a
  half-edited block.
- **Next actions:** Stage B — retire the legacy dominance path in `MachineLaneSSAUpdater`
  (`createPHIInBlock`/`insertPHIAtBlock` IDF placement, `findRenamedReachingDef`, `computePrunedIDF`,
  `UseReachingOracle` gating, updater `repairSSAForReload`) once each is confirmed callerless; this is
  delicate SSA-repair core, so verify-then-delete per symbol. Stage C — drop `,amdgpu-rebuild-ssa` from
  SSASpiller RUN lines; reconcile remaining CHECK mismatches (no blind matching); revisit the XFAIL.

### 2026-07-05 – Legacy dead-code cleanup, Stage B: MachineLaneSSAUpdater [REFACTOR] [SSAUPDATER]

- **Context / goal:** Retire the legacy dominance/IDF-based SSA-repair path in `MachineLaneSSAUpdater`,
  now that the reaching-VNI (frozen PHI-def VNInfo) path is the only live reconstruction path.
- **Enabling fact (verified):** updater `repairSSAForReload` is callerless across the whole worktree
  (the spiller's only call site lived inside the Stage-A-deleted `processKillDominatedGroupsWithList`).
  Since `repairSSAForReload` was the *only* place `UseReachingOracle` was set `false`, the flag is now
  always-true — so every `if (UseReachingOracle)` legacy `else` branch is dead.
- **[REFACTOR] Removed (defs + `.h` decls):** `repairSSAForReload`, `createPHIInBlock` (dominance PHI),
  `findRenamedReachingDef`, `insertPHIAtBlock` (already callerless), `getPrunedIDF` (already callerless).
  Removed the `UseReachingOracle` member + its `= true` set site; collapsed the two guarded branches:
  `insertLaneAwarePHI` now unconditionally places PHIs from frozen PHI-def VNInfos (dropped its unused
  `InitialVReg`/`InitialDefBB` params — caller `performSSARepair` updated); `rewriteDominatedUses` now
  unconditionally calls `rewriteUseReaching` (dropped the whole legacy Case 1/2/3 dominance tail and the
  now-unused `TRI` local). Fixed the stale `repairSSAForReload` comment in the spiller's
  `finalizeLiveIntervals`.
- **[DESIGN] Kept deliberately:** `computePrunedIDF` + `defDominatesUse` survive **only** inside
  `isUseReachableFromDef`, which the spiller calls at spill-*planning* time (`buildDomGroupsForSpill`).
  That query asks "is this non-dominated use downstream of a hypothetical spill?" — reachability about a
  def that does not exist yet, so there is no VNInfo/PHI-def to read; it is NOT SSA reconstruction. The
  "IDF eliminated" design win applies to reconstruction (PHI placement reads PHI-def VNInfos that
  LiveIntervalCalc already computed) and stands. Per-user decision: eliminating IDF from the spiller's
  planning reachability too (replace `isUseReachableFromDef`'s IDF slow-path with an old-LI liveness /
  plain CFG-reachability test, then delete `computePrunedIDF`/`getPrunedIDF`/`defDominatesUse`) is a
  **separate change planned for tomorrow**, validated against `spill-use-before-spill`,
  `spill-diamond-phi-merge`, `spill-multi-path-independent`.
- **Results:** `LLVMCodeGen`+`LLVMAMDGPUCodeGen` build clean (no warnings). Lit `SSASpiller`+`SSARA`:
  86 passed, 1 XFAIL, 0 regressions (== baseline). `MachineLaneSSAUpdater`: 3 real-pipeline `.ll` tests
  pass; the 4 `test-machine-lane-ssa-updater` harness `.mir` tests still fail as before (unregistered
  pass — infra, not caused by this change).
- **Next actions:** Stage C test hygiene (drop `,amdgpu-rebuild-ssa` from SSASpiller RUN lines;
  reconcile the 2 CHECK mismatches with output-correctness review; revisit XFAIL). Tomorrow: the
  IDF-from-spiller elimination change above.

### 2026-07-05 – Legacy dead-code cleanup, Stage C: test hygiene (audit) [TEST] [SPILLER]

- **Finding:** Stage C was already satisfied — no edits needed.
  - RUN-line flag: no SSASpiller test contains `amdgpu-rebuild-ssa` (all single-pass
    `-run-pass=amdgpu-ssa-register-spiller`); removed in an earlier session.
  - The 2 "CHECK-mismatch" tests (`spill-triangle-phi`, `spill-diamond-phi-merge`) both PASS — CHECKs
    already reconciled to verified output; no blind-matching change required.
  - The remaining XFAIL is `spill-loop-skip-def-inside.mir` (not the earlier `-reload-inside-fallback`,
    which was resolved before). It is a **genuine** XFAIL (lit: Expectedly Failed, not XPASS) marking a
    real unimplemented feature: `# FIXME: Loop-aware spill candidate filter can empty;
    validateFinalRegisterPressure fails until fallback exists`. Kept as-is — clearing it needs the
    loop-aware spill fallback (a feature), not a cleanup edit.
- **Net:** legacy-path cleanup (Stages A+B) is the whole change set; Stage C is a no-op audit. Tree is
  green (SSASpiller/SSARA 86 pass + 1 legit XFAIL). Uncommitted (user commits manually).

### 2026-07-05 – Legacy dead-code cleanup, residual orphans [REFACTOR] [SSAUPDATER]

- **Context:** Post-Stage-B audit for symbols the legacy removal left dead.
- **[REFACTOR] Removed:** `incomingOnEdge` (def + `.h` decl; callerless after legacy removal) and
  `RenamedLaneDefs` (the whole DenseMap + its `.clear()` + its write site — it became write-only once
  its only reader, the deleted `findRenamedReachingDef`, was gone; the live identity-keyed map is
  `DefInstrToRenamed`). Reworded the `DefInstrToRenamed` doc comment that referenced `RenamedLaneDefs`.
- **[DESIGN] Kept:** `clearIDFCache`/`IDFCache`/`computePrunedIDF`. `clearIDFCache` is callerless but
  that is *pre-existing* (nothing this cleanup deleted ever called it), and IDF itself is still live via
  `isUseReachableFromDef`. Open question for tomorrow's IDF review: `IDFCache` (keyed by (VReg,
  LaneMask)) is never invalidated despite CFG edits (e.g. critical-edge splitting) — possible staleness;
  the fix would be *calling* clearIDFCache at the right points, not deleting it.
- **Results:** clean build; SSASpiller/SSARA 86 pass + 1 XFAIL; MachineLaneSSAUpdater 3 `.ll` pass, 4
  unregistered-harness `.mir` fail (pre-existing infra). No regressions. Legacy cleanup now COMPLETE;
  only tomorrow's IDF-from-spiller elimination remains.
- Cleanup committed + pushed (single commit, -967/+54).

### 2026-07-06 – Agenda / next session plan [DESIGN]

1. **IDF – do we still need it?** Decision already scoped (see Stage B/residual notes): reconstruction
   no longer needs IDF. The only live use is the spiller's `isUseReachableFromDef` (spill *planning*),
   whose query is plain reachability of a not-yet-created reload def. Plan: replace its IDF slow-path
   with an old-LI liveness / CFG-reachability test, validate on `spill-use-before-spill`,
   `spill-diamond-phi-merge`, `spill-multi-path-independent`; then delete `computePrunedIDF`,
   `getPrunedIDF`, `defDominatesUse`, `IDFCache`, `IDFCacheKey`, `clearIDFCache`. Also resolves the
   IDFCache-never-invalidated staleness concern by removing the cache entirely.
2. **AMDGPU e2e test harness script** (goes in `/work/atimofee/sandbox/github/scripts/`, NOT in
   llvm-project): run the full `llvm/test/CodeGen/AMDGPU` corpus through the ssara pipeline, capture
   stderr/exit per test, classify failures into buckets (MachineVerifier errors, "reading virtual
   register without a def", crashes/asserts, FileCheck mismatches, timeouts), emit a report (counts +
   representative examples per bucket) to seed a test/fix plan. Then run + analyze + write the plan.
3. **Update design docs** in `ssa-spiller-docs/SSARA/04-Design/` (esp. `SSA_RA_Coloring.md`) to reflect
   the unified reaching-VNI repair, Option-3 spiller (reload-as-redef + inline repair), and legacy-path
   removal.
4. **SSARA team kickoff presentation** (short deck): project overview, pipeline architecture
   (RebuildSSA -> SSA spiller -> SSA coloring RA), current status, the 3 engineer workstreams, roadmap.
   NEEDS INPUT: the 3 task areas to assign to the 3 engineers.

### 2026-07-06 – IDF fully removed; isUseReachableFromDef -> CFG reachability [REFACTOR] [SSAUPDATER] [SPILLER]

- **Context / goal:** Agenda item #1. Established (via a long design discussion) that IDF is not needed
  anywhere in our code: SSA reconstruction places PHIs from the frozen `LI(X)`'s `isPHIDef` VNInfos
  (computed by `LiveIntervalCalc` when we recompute the interval after inserting reload re-defs — the
  reload-as-redef keeps the value live through merges because X still owns its original uses until the
  rewrite). The spiller's `isUseReachableFromDef` only answered "is this use downstream of the kill?",
  which for SSA `X` is exactly plain CFG reachability (dominance ⊂ reachability); its IDF slow-path was
  set-equivalent to that.
- **[REFACTOR] Done (APPROVED):** rewrote `isUseReachableFromDef(MI*, MI*, Register)` as a
  successor-closure BFS from the kill block to the use's target block (PHI use → predecessor block),
  with same-block handled by slot order and a `MDT.dominates` fast-path (keeps MDT used). Dropped the
  `DefMask` param and updated the one spiller call site. Deleted `computePrunedIDF`, `IDFCache`,
  `IDFCacheKey` (+ its `DenseMapInfo`), `clearIDFCache`, `defDominatesUse`, `defReachesUse`, the
  `isUseReachableFromDef(MO&, MO&, Register)` overload, and the
  `GenericIteratedDominanceFrontier.h` include. Kept `DenseMapInfo<LaneBitmask>` (still used by
  `LanePHIs`). **No IDF anywhere in MachineLaneSSAUpdater/spiller now** — the only DF work left is
  inside core `LiveIntervalCalc`, which we get for free by recomputing the interval.
- **Results:** clean build (no new warnings); SSASpiller/SSARA 44+... = 89 pass + 1 XFAIL, 4
  pre-existing unregistered-harness `.mir` fails — identical to baseline, i.e. behavior-preserving as
  the reachability≡IDF equivalence predicted. Uncommitted (user commits manually).
- **Deferred (agenda #1b):** the deeper spiller-planning redesign — place reloads for kill-dominated
  uses only and let reconstruction's VNInfo oracle handle parallel-path merges — which would remove
  `isUseReachableFromDef` entirely. Separate change; needs its own validation.

### 2026-07-06 – Full "our" suite green after redesign [BUGFIX] [TEST] [SPILLER]

- **Context / goal**
  - After the cut-copy + dominance-ordered reload-on-demand + inline-reconstruction redesign, 3 SSASpiller
    tests failed. User: "Full OUR test suite." Triage each; distinguish real bugs from intentional
    behavior changes.
- **Results / discoveries**
  - **[BUGFIX]** `spill-physreg-pressure` aborted the MachineVerifier: "MBB has allocatable live-in
    ($vgpr0), but isn't entry". Root cause: `emitReloadsAndRepairSSA` reset the `NoPHIs` property whenever
    *any* reload was placed (`!ReloadDefs.empty()`), even when reconstruction inserted **no** PHI. The
    verifier's physreg-live-in check is gated on `!hasNoPHIs()` (`MachineVerifier.cpp:727`); wrongly
    clearing `NoPHIs` turned it on and flagged a construct that is *legal for a PHI-free function*. Fix:
    track `InsertedPHI` from `repairSSAForNewDef`'s `PHIDefs` out-param and reset `NoPHIs` only when a PHI
    was actually inserted (mirrors `X86CmovConversion.cpp:872`). The test MIR is **correct as-is** — the
    verifier deliberately permits allocatable physreg live-ins when `NoPHIs` is set; "fixing" it via a
    COPY-to-vreg would destroy the physreg-pressure coverage. Added a NOTE to the test documenting the
    PHI-free coupling.
  - **[TEST]** `spill-triangle-phi`: new output is correct + better — 2 reloads (bb.2, bb.3); bb.4 merges
    the original `%x` (bb.0 bypass, never spilled) with the bb.3 reload via a PHI instead of a 3rd reload.
    Updated bb.4 CHECK.
  - **[TEST]** `spill-reload-opt-basic`: old CHECK enshrined the *removed* dominance-frontier reload
    optimizer (ONE reload hoisted to entry NCD — objectively bad: reloads straight back into the pressure
    region). New design places per-branch on-demand reloads (bb.1, bb.2). Rewrote CHECKs.
- **Decisions / rationale**
  - B/C are legitimate test updates (deliberate design change, each new output verified as the *intended*
    behavior), not output-chasing.
- **Results:** SSASpiller/SSARA/MachineLaneSSAUpdater = **89 pass + 1 XFAIL**; only 4 fails remain, all
  the pre-existing `test-machine-lane-ssa-updater is not registered` harness gap (unrelated). Uncommitted
  (user commits manually).

### 2026-07-06 – PHI→PHI reconstruction test (nested diamonds) [TEST] [SPILLER]

- **Context / goal**
  - Design-sanity Q from user: when a reconstruction PHI result is consumed by another PHI, is the PHI-def
    reaching value available, and is its LiveInterval extended to the downstream PHI's predecessor end?
    Reading alone couldn't fully guarantee the interval extension for a PHI feeding *directly* into a PHI,
    so added a targeted test (APPROVED).
- **Design (one-by-one flow: CFG+liveness reviewed → approved → created → ran)**
  - `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-nested-phi-phi.mir`. Nested diamonds: `%x` def+SAVE in bb.0,
    freed by pressure at bb.1 (marker). Inner diamond bb.2/bb.3 both use `%x` (→ two reloads) merging at
    bb.4 (inner PHI R1). Outer bypass bb.0→bb.5 keeps ORIGINAL `%x`. Outer join bb.5 merges R1 (bb.4) with
    original `%x` (bb.0) → outer PHI R2. bb.4 has no use of `%x`, so R1's only consumer is R2 (PHI→PHI).
- **Results / discoveries**
  - **No bug.** Output: `bb.4: %12 = PHI %14,%bb.2, %11,%bb.3` (inner merge of the two reloads, no reload);
    `bb.5: %13 = PHI %x,%bb.0, %12,%bb.4` (outer merge of original `%x` and inner PHI `%12`, no reload).
    Genuine PHI-result-feeds-PHI. Passes under `-verify-machineinstrs` — the placeholder-then-patch path
    (`createPHIInBlockReaching` emits `%x` placeholder for a PHI-def reaching value; `rewriteUseReaching`
    matches PHI-defs by `isPHIDef && block==DefBB` and patches to R1) is sound, and R1's interval is
    correctly extended to bb.5's predecessor end.
  - CHECKs tightened to assert the PHI→PHI relationship with verified operand order (`PHI %x, %bb.0,
    [[INNER]], %bb.4`), not just presence. Collateral `%a0`/`%a1` spills (num-vgpr=3) are harmless.
- **Results:** SSASpiller+SSARA = **87 pass + 1 XFAIL, 0 fails** (new test included). Uncommitted.

### 2026-07-06 – Remove redundant 2nd RebuildSSA [REFACTOR] [SPILLER]

- **Context / goal**
  - Pre-commit sanity check: the `EnableSSARegAlloc` pipeline still had a second `RebuildSSA` after the
    spiller (added as "Option 3 groundwork"). With inline reconstruction the spiller now returns SSA MIR
    (`emitReloadsAndRepairSSA` resets `SSAInvalidated=false`), making that pass a no-op.
- **Changes applied (APPROVED)**
  - **[REFACTOR]** `AMDGPUTargetMachine.cpp`: dropped the 2nd `createAMDGPURebuildSSALegacyPass()` between
    the spiller and the allocator; comment now states the spiller repairs SSA inline.
  - **[REFACTOR]** `AMDGPUSSARegisterSpiller.cpp`: refreshed stale comments (getOrCreateReloadInBlock,
    insertReloadForUse x2, end-of-pass IsSSA guard) that referenced "RebuildSSA #2"/"Option 3". The
    end-of-pass `if (SSAInvalidated) reset(IsSSA)` is kept as a fail-loud net (no rebuild follows, so an
    unrepaired path would make the SSA-requiring allocator fail rather than silently consume non-SSA MIR).
- **Results:** rebuilt llc; SSASpiller+SSARA+MachineLaneSSAUpdater = **90 pass + 1 XFAIL**; only the 4
  pre-existing unregistered-harness fails remain. SSARA (full pipeline through the allocator) green,
  confirming the removed pass was a genuine no-op. Uncommitted (user commits manually).

### 2026-07-06 – Dead-code + lint + clang-format cleanup [REFACTOR] [SPILLER]

- **Context / goal**
  - Final cleanup pass over the new source: remove dead code, fix all lint warnings, clang-format
    (--style=LLVM) the spiller, MachineLaneSSAUpdater, and SSA RA files (APPROVED).
- **Dead code removed**
  - **Spiller** (`AMDGPUSSARegisterSpiller.{h,cpp}`): `sortByDominanceOrder`, `spillAtEnd`,
    `getRegSetSizeInRegs`, `blockHasUse`, `cutFromLiveRange`, `optimizeReloadPlacing`,
    `tryHoistSpillToNCD`, `collectDominatedBlocks` (old reload-optimizer/IDF era, zero call sites), the
    loop-aware scaffolding `hasDefInLoop`/`hasUseInLoop`/`getLoopExitDominatingSpill` (deferred #1b, dead
    now — recover from git when needed), and the unused member `SpillToReloadMap`. Kept
    `canHoistReloadTo`/`getMaxRP*`/`walkPathsToUses` (still reached via `adjustReloadForLoop` ←
    `insertReloadForUse`).
  - **MachineLaneSSAUpdater** (`.h`/`.cpp`): `extendPreciselyAt`, fluent no-op knobs
    `setUndefEdgePolicy`/`setVerifyOnExit` + members `UndefEdgeAsImplicitDef`/`VerifyOnExit` + the
    no-op verify stub, dead trailing "REMOVED" comment, unused `MachinePostDominatorTree` fwd-decl.
- **Lints fixed**: case-style renames (`needsReload`→`NeedsReload`, `laneNeedsReload`→`LaneNeedsReload`,
  `placePHIsFor`→`PlacePHIsFor`, `stopOnBad`→`StopOnBad`, `MFI_Local`→`LocalMFI`, loop `i`→`I`); include
  sorting via clang-format. Stale comments refreshed (IDF-reachability, `SSAInvalidated`/second-RebuildSSA).
- **clang-format** `--style=LLVM -i` on all 6 files (spiller .h/.cpp, updater .h/.cpp, RA .h/.cpp). RA
  files had no dead code and no lints — format-only.
- **Results:** ReadLints clean on all files; rebuilt llc; SSASpiller+SSARA+MachineLaneSSAUpdater =
  **90 pass + 1 XFAIL**, only the 4 pre-existing unregistered-harness fails. Uncommitted.

### 2026-07-06 – HANDOFF: test plan + docs update (for a fresh chat) [HANDOFF] [SPILLER] [DOC] [TEST]

This section is a self-contained handoff so a new chat can drive the **test plan** and **docs update**
without re-reading the whole history. Nothing below requires re-deriving the design — it is settled.

#### A. Repo / build / test state
- Worktree: `/work/atimofee/sandbox/github/ssara`, branch `ssara`. Build: `ninja -C build/user-debug llc`
  (~2 min). Tests: `python3 build/user-debug/bin/llvm-lit -sv llvm/test/CodeGen/AMDGPU/SSASpiller
  llvm/test/CodeGen/AMDGPU/SSARA llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater`.
- **Committed** (HEAD `c69c6f8` "SSA spiller: dominance-ordered reload placement on a frozen cut copy"):
  the reload-placement redesign, inline reaching-VNI reconstruction, the `NoPHIs`-reset-only-on-real-PHI
  fix, removal of the 2nd `RebuildSSA` from `AMDGPUTargetMachine.cpp`, the updated CHECKs
  (triangle/diamond/reload-opt-basic/physreg-pressure), and the new `spill-nested-phi-phi.mir`.
- **Uncommitted** (user commits manually): cleanup diff over 6 source files only — dead-code removal +
  lint fixes + clang-format for `AMDGPUSSARegisterSpiller.{h,cpp}`, `MachineLaneSSAUpdater.{h,cpp}`
  (updater header in `include/llvm/CodeGen/`), `AMDGPUSSARegisterAllocator.{h,cpp}`. Suite green
  (90 pass + 1 XFAIL). Commit message: subject like "[AMDGPU] Cleanup: remove dead spiller/updater code,
  fix lints, clang-format".
- **Only remaining suite failures** are 4 pre-existing infra fails: `MachineLaneSSAUpdater/*.mir` error
  `run-pass test-machine-lane-ssa-updater is not registered` (a lit harness pass not built into llc —
  unrelated to any of this work; do NOT try to "fix" by editing the spiller).

#### B. Design as it now stands (settled — for doc writing)
- **Spiller reload placement** (`emitReloadsAndRepairSSA`): dominance-ordered walk over uses; per-use a
  per-edge availability query on a **frozen deep COPY of the spilled vreg's LiveInterval pruned at the
  kill** (`pruneValue`, main range + subranges). Reload iff some spilled lane is unavailable on an
  incoming edge; a value live-in on ALL preds is a genuine merge → left to reconstruction (PHI). The live
  LIS is NEVER pruned (RPTracker input preserved). Old dominance-frontier reload optimizer + IDF removed.
- **Inline SSA reconstruction** (`MachineLaneSSAUpdater::repairSSAForNewDef`, one call per reload redef):
  freezes OrigVReg's recomputed interval as the reaching oracle; places PHIs exactly at the interval's
  PHI-def VNInfos (= LiveIntervalCalc's pruned IDF, no IDF recompute); resolves PHI operands and uses via
  reaching-VNI; PHI-def reaching values use placeholder-then-patch. Spiller returns SSA
  (`SSAInvalidated=false`), so no 2nd RebuildSSA. `NoPHIs` reset only when a PHI is actually inserted.
- **RA** (`AMDGPUSSARegisterAllocator`): unchanged by this work (only clang-format'd); clean.

#### C. Test coverage matrix + GAPS (the test-plan work)
Existing SSASpiller tests (44 files) cover: linear/diamond/triangle joins, dom-groups, loops
(def-in/def-out/reload-inside-fallback/preheader-shift/skip), SGPR lane packing/budget, physreg live-ins,
subregister/partial-lane spills, critical edges, early-clobber. Recent additions:
`spill-triangle-phi` (original survives bypass, merge PHI), `spill-diamond-phi-merge` (two reloads merge +
outer PHI with original), `spill-nested-phi-phi` (PHI result feeding a PHI — placeholder-then-patch).
- **GAP 1 (recommended next test):** partial-lane / subregister **PHI→PHI** — a subrange merge-PHI whose
  result feeds another subrange merge-PHI (the `spill-nested-phi-phi` analog but lane-masked, exercising
  REG_SEQUENCE composition across nested joins). Only full-register PHI→PHI is currently proven.
- **GAP 2:** loop-carried reload where the header PHI merges preloop value with an in-loop reload (Q1 from
  this session was answered by-design as correct, but has no dedicated minimal test asserting the header
  PHI + no dead preheader reload).
- **GAP 3:** multi-lane spill where different subranges are freed on different edges at the same join.
- Test authoring rules (STRICT, from AGENTS.md): design one-by-one (CFG diagram + liveness → APPROVED →
  create file → run); NEVER edit a test to match output (tests define expected behavior); pin only
  incidental vreg numbers/operand order after confirming behavior is correct. gfx1200,
  `"amdgpu-num-vgpr"="3"`, flags `-amdgpu-ssa-spill-no-reload-opt -amdgpu-ssa-spill-markers
  -verify-machineinstrs -run-pass=amdgpu-ssa-register-spiller` (see `spill-triangle-phi.mir`).

#### D. Docs to update (`ssa-spiller-docs/SSARA/04-Design/`)
- `Reload_optimizer.md` — now describes REMOVED code (dominance-frontier NCD hoisting / clique reload
  placement). Mark deprecated/historical or delete; point to the new on-demand scheme.
- `SSA_SPILLER_DESIGN.md` — update the reload-placement + SSA-repair sections to the frozen-cut-copy +
  dominance-ordered on-demand + inline reconstruction design; note the 2nd RebuildSSA is gone.
- `Reload_join_phi_coalescing.md` — the new design note; verify it matches shipped behavior and cross-link
  from `SSA_SPILLER_DESIGN.md` and `MachineLaneSSAUpdater.md`.
- `MachineLaneSSAUpdater.md` — document the frozen-interval reaching oracle, PHIs-at-PHI-def-VNInfos,
  placeholder-then-patch for PHI-def reaching values, and that `NoPHIs` is reset only on real PHI insert.
- Conventions: KaTeX `$...$`, mermaid for diagrams (no ASCII art), convert via
  `ssa-spiller-docs/SSARA/tools/md2pdf.py`.

#### E. Deferred (separate future change, NOT part of test/doc work)
- **Agenda #1b:** deeper spiller-planning redesign — reload only kill-dominated uses and let
  reconstruction's VNInfo oracle absorb parallel-path merges, which would remove
  `isUseReachableFromDef`. The loop-aware scaffolding (`hasDefInLoop`/`hasUseInLoop`/
  `getLoopExitDominatingSpill`) was deleted in cleanup — recover from git (pre-cleanup) when #1b starts.

### 2026-07-06 – READY TO IMPLEMENT: replace SI_VIRTUAL_SPILL_MARKER with MFI YAML metadata [DESIGN] [SPILLER] [READY]

Approved design (decisions locked; NOT yet implemented — do later). Goal: delete the
`SI_VIRTUAL_SPILL_MARKER` pseudo-instruction and instead record the virtual spill point as
`SIMachineFunctionInfo` metadata serialized in the MIR `machineFunctionInfo:` YAML.

**Why:** the marker is a test-only artifact (hidden flag `-amdgpu-ssa-spill-markers`, default off) with NO
logic consumer (its only reader, `tryHoistSpillToNCD`, was deleted). As a real instruction it is inserted
via `LIS->InsertMachineInstrInMaps`, consuming a slot index and perturbing slot numbering DURING the pass
— so tests (markers on) can diverge subtly from real codegen (markers off). MFI metadata removes that.

**Locked decisions** (from Q&A): storage = `SIMachineFunctionInfo` YAML (zero generic-CodeGen changes,
idiomatic MIR metadata, printed at the function header — NOT inline at the block, because
`MachineBasicBlock::print` is generic with no target hook). Precision = block + slot; slot rendered to a
string at record time. Tests assert `bb`+`vreg`+`lanes` only (stable); `slot:` is emitted for precision
but NOT pinned in CHECKs (SlotIndex numbers shift when surrounding instrs change).

**Remove the pseudo (3 files):**
- `llvm/lib/Target/AMDGPU/SIInstructions.td` — delete the `SI_VIRTUAL_SPILL_MARKER` def (~lines 509-516,
  the `SPseudoInstSI<(outs),(ins i32imm:$virt_idx,i64imm:$lane_mask)>`, isMeta, Size 0).
- `llvm/lib/Target/AMDGPU/SIInstrInfo.cpp` — delete the `case AMDGPU::SI_VIRTUAL_SPILL_MARKER:` in
  `expandPostRAPseudo` (~2112-2114, `MI.eraseFromParent(); return true;`).
- `llvm/lib/Target/AMDGPU/AMDGPUMIRFormatter.cpp` — delete the custom print case (~28) and parse case
  (~60) for operand 0.

**Data model (`SIMachineFunctionInfo.h` + `.cpp`):**
- Real class `llvm::SIMachineFunctionInfo`:
  ```cpp
  struct VirtualSpillPoint { unsigned MBBNum; std::string Slot; Register VReg; LaneBitmask Lanes; };
  SmallVector<VirtualSpillPoint, 4> VirtualSpillPoints;
  void addVirtualSpillPoint(unsigned BB, StringRef Slot, Register VReg, LaneBitmask L);
  ArrayRef<VirtualSpillPoint> getVirtualSpillPoints() const;
  ```
  `Slot` is rendered from the live `SlotIndexes` AT RECORD TIME (a raw `SlotIndex` would dangle after the
  SlotIndexes analysis is freed before MIRPrinting).
- YAML DTO `yaml::SIMachineFunctionInfo` (struct ~260) gets `std::vector<SIVirtualSpillPoint>
  VirtualSpillPoints;` where `SIVirtualSpillPoint { unsigned BB; std::string Slot; std::string VReg;
  std::string Lanes; }`, with its own `MappingTraits` (flow style) and a `mapOptional("virtualSpillPoints",
  ...)` line in `MappingTraits<SIMachineFunctionInfo>::mapping` (~317). Omitted when empty.
- Real→YAML conversion (the `yaml::SIMachineFunctionInfo` ctor / `convertToYAML` path in
  `SIMachineFunctionInfo.cpp`): render `VReg` via `printReg(VReg, TRI, 0, &MRI)` (preserves `%x` names) and
  `Lanes` as 16 hex digits (matches the old marker's `getAsInteger()` print). Parse side: tolerated but not
  copied back to the real class (the spiller regenerates each run).
- YAML output shape:
  ```
  machineFunctionInfo:
    ...
    virtualSpillPoints:
      - { bb: 1, slot: '80B', vreg: '%x', lanes: '0000000000000003' }
  ```

**Spiller (`AMDGPUSSARegisterSpiller.cpp/.h`):** rename `insertVirtualSpillMarker` →
`recordVirtualSpillPoint`; replace the `BuildMI(...SI_VIRTUAL_SPILL_MARKER...).addImm(virtidx).addImm(mask)`
+ `InsertMachineInstrInMaps` with: compute the slot string from `LIS` at the insert position
(`I==end() ? getMBBEndIdx(&MBB) : getInstructionIndex(*I)`, `.print()` to a string) and call
`MF.getInfo<SIMachineFunctionInfo>()->addVirtualSpillPoint(MBB.getNumber(), SlotStr, VMP.getVReg(),
VMP.getLaneMask())`. Keep the `-amdgpu-ssa-spill-markers` (`EnableVirtualSpillMarkers`) gate and both call
sites (PHI-predecessor case + normal case). Keep the "avoid dropping right after the store" guard.

**Tests (21 files):** all references are in CHECK/`SPILLER:` lines (none in input MIR bodies), so only
CHECK rewrites. For each, replace `# CHECK: SI_VIRTUAL_SPILL_MARKER %x[, mask]` with a YAML assertion
placed AFTER `# CHECK-LABEL: name: ...` and BEFORE the body/bb CHECKs, e.g.:
`# CHECK: - {{.*}}bb: 1,{{.*}}vreg: '%x',{{.*}}lanes: '0000000000000003'` (assert bb+vreg+lanes; do not
pin slot). Files: the 18 SSASpiller `.mir` (spill-triangle-phi, spill-diamond-phi-merge,
spill-reload-opt-basic, spill-nested-phi-phi, spill-unused-lane, spill-vreg-subregister,
spill-use-before-spill, spill-dominated-branches, spill-multi-predecessor-join, spill-linear-dominated,
spill-multi-path-independent, spill-vreg-many-lanes, spill-empty-blocks, spill-multi-ncd,
spill-store-at-def-use-before, spill-two-pass-sgpr-vgpr, spill-function-livein, spill-double-same-register,
spill-loop-fallback-preheader, spill-loop-def-outside-use-outside) + 3 SSARA `.ll`
(pipeline-spill-linear/loop/diamond, prefix `SPILLER:`). NOTE the SSARA `.ll` run full pipeline: confirm
the `machineFunctionInfo:` YAML is actually emitted at the stage they FileCheck (they may print asm, not
MIR — if so, migrate those 3 to check nothing marker-related, or drop the marker line, since asm output
won't contain MFI YAML). Verify per-file before editing.

**Validation:** rebuild `llc`; SSASpiller+SSARA+MachineLaneSSAUpdater should stay green (90 pass + 1 XFAIL,
same 4 pre-existing harness fails). Watch for: the 3 SSARA `.ll` (asm vs MIR output — see note above), and
that `printReg` naming matches the pre-existing `%x` expectations.

**Test-authoring caveat:** this is a representation migration of an existing assertion (marker → YAML),
same semantic content — allowed. Do not change WHICH block/vreg/lanes are asserted; if the YAML shows a
different bb/vreg than the old marker did, that's a real behavior change to investigate, not a CHECK to
silently adjust.

## Further Improvements (standing backlog)

Open, not-yet-implemented items (most actionable first):

1. **[READY] Replace `SI_VIRTUAL_SPILL_MARKER` with `SIMachineFunctionInfo` YAML metadata.** Full
   ready-to-implement spec is in the "READY TO IMPLEMENT" diary entry immediately above (dated
   2026-07-06). Decisions locked; do later. Touches `SIInstructions.td`, `SIInstrInfo.cpp`,
   `AMDGPUMIRFormatter.cpp`, `SIMachineFunctionInfo.h/.cpp`, `AMDGPUSSARegisterSpiller.cpp/.h`, and 21
   tests. No generic-CodeGen changes.
2. **[TEST PLAN] Fill SSASpiller coverage gaps** (see the HANDOFF entry above): (a) partial-lane /
   subregister PHI→PHI; (b) loop-carried reload with a header merge-PHI; (c) multi-lane spill freeing
   different subranges on different edges at a join. One-by-one, CFG+liveness → APPROVED → create → run.
3. **[DOCS] Refresh design docs** to the shipped design: deprecate/retire `Reload_optimizer.md`; update
   `SSA_SPILLER_DESIGN.md` (on-demand reload placement + inline reconstruction; 2nd RebuildSSA gone);
   verify/cross-link `Reload_join_phi_coalescing.md`; update `MachineLaneSSAUpdater.md` (frozen reaching
   oracle, PHIs-at-PHI-def-VNInfos, placeholder-then-patch, NoPHIs-on-real-PHI-only).
4. **[Deferred #1b] Deeper spiller-planning redesign** — reload only kill-dominated uses and let
   reconstruction's VNInfo oracle absorb parallel-path merges (would remove `isUseReachableFromDef`).
   Recover the deleted loop-aware scaffolding from pre-cleanup git when starting. Own change + validation.

### 2026-07-06 — AMDGPU corpus harness + full-corpus triage [FEATURE] [TRIAGE]

- **[FEATURE]** New `scripts/ssara_corpus_harness.py` (lives in `github/scripts/`, NOT llvm-project).
  Per test: reuse the test's OWN RUN line, strip `| FileCheck ...`/`-o`, inject `-amdgpu-ssa-regalloc`
  (+ `-verify-machineinstrs` as the correctness gate), run our stack; on success run the same command
  minus the flag (Greedy) and diff per-function `; TotalNumSgprs/NumVgprs/ScratchSize/Occupancy` +
  `.set *.num_vgpr/.numbered_sgpr/.private_seg_size`. Buckets: CRASH (by normalized signature),
  OK_EQUAL/OK_BETTER, DIFF_COALESCING (occ/scratch-neutral, reg-count only), MIXED,
  REGRESSION_OCC_OR_SPILL, PREEXISTING_FAIL, TIMEOUT, NO_METRICS, and SKIP_* (O0, r600, custom
  regalloc, run-pass/stop, pipeline, expected-fail, generated-input). Parallel `--jobs` (default
  ncpu/2), `--timeout`, resumable `results.jsonl`, `run`/`report` subcommands. Parser gotchas handled:
  bash treats `<` as a metachar (`-< %s` == `- < %s`, `<%s` == `< %s`) so `<` is space-normalized
  before shlex; `2>&1`/`2>file` stripped; lone `-` (stdin) dropped; `%t.bc` (from a prior `opt`)
  skipped as SKIP_GENERATED_INPUT.
- **[TRIAGE] Full run (`scripts/out/ssara-corpus/full-run2`, report + TRIAGE_PLAN.md there).** 3060
  `.ll`; 850 skipped (not applicable); 2210 attempted → **852 CRASH (38.6%)**, 1 timeout, 1357 compiled.
  Of the 1357 compiled, allocation quality ~= Greedy: OK_EQUAL 565, OK_BETTER 228, DIFF_COALESCING 239,
  MIXED 276, NO_METRICS 40, and only **9 REGRESSION_OCC_OR_SPILL** (spiller over-spilling: fewer VGPRs
  but adds scratch — the known coalescing-unaware RP overestimate). **Headline: crashes are the problem,
  not allocation quality.** Confirmed SSARA-specific: every crash class has a representative that
  compiles clean under Greedy (4 outliers also fail Greedy+verify).
- **Crashes by owner (26 classes):** SSA-RECONSTRUCTION 257 (117 `Use not jointly dominated by defs`,
  85 `Reading virtual register without a def`, 47 `PHI with NoPHIs` — the last mostly collateral from
  the forced `MF.verify()` on the LiveRangeCalc fatal path, i.e. same root as the 117); RA-COLORING 319
  (286 `Virtual register not colored`, 17 tied-use, 11 failed-to-find-physreg); OPERAND-REWRITE 259
  (119 `use operand subreg has no register class`, 85 `Using an undefined physical register`, 24
  incorrect-reg-class, 13 two-address, ...). Top 6 classes = 739/852 = 87%.
- **[ROOT CAUSE — SSA reconstruction, RMW partial-def chains].** Minimal repro `add.ll -mcpu=verde`,
  function `@s_add_v8i32`, a single straight-line block (no PHIs). `%17:sgpr_128` is built by a chain
  of partial subreg defs where ONLY the first has `undef`: `undef %17.sub3=S_MOV` (lanes 0xC0), then
  `%17.sub2=S_MOV` (0x30) and `%17.sub0_sub1=S_LOAD` (0x0F) WITHOUT `undef`. A subreg def without
  `undef` read-modify-writes the super-register (unwritten lanes stay live), so the later partial defs
  IMPLICITLY read the establishing def's lanes. RebuildSSA sees 3 VNs and splits them as independent
  re-defs; when it renames the establishing `undef` def (sub3→%54) and rewrites the EXPLICIT uses
  (BUFFER_STOREs → REG_SEQUENCE), it MISSES the IMPLICIT RMW reads at the sub2/sub0_sub1 def
  instructions. `%17` then has no def for the 0xC0 lanes that sub2 still RMW-reads →
  `createAndComputeVirtRegInterval(%17)` aborts `Use not jointly dominated by defs` at `%17.sub2`.
  Pattern (wide reg assembled by successive subreg writes: descriptors, vector stores, bitcasts) is
  pervasive → explains the largest correctness bucket. Fix approach TBD with user (no source edit yet;
  approval-gated). Candidate directions: (A) treat each partial-def instruction's implicit super-reg
  RMW read as a use to be rewritten to the reaching renamed def; (B) normalize RMW partial-def chains
  to `undef` + REG_SEQUENCE before splitting; (C) recognize a linear partial-def chain as one value.
- **Next:** decide fix approach for the RMW-partial-def class, then re-run the harness to re-bucket;
  proceed down the prioritized list (coloring `not colored` 286 next by impact).

### 2026-07-06 — RMW single-block fix applied; exposes latent UseRC-null (NET REGRESSION, decision pending) [BUGFIX] [SSAUPDATER]

- **[APPLIED, uncommitted] `AMDGPURebuildSSA.cpp` single-block RMW-chain fix.** For a vreg whose defs
  are all in ONE block and include a non-`undef` subreg def (RMW chain): Root = establishing (earliest
  slot) def via a `(DomPreorder, slot)` tie-break; re-defs renamed in REVERSE order (latest first) so
  each still-present def only reads dominating, not-yet-renamed lanes; Root processed last and narrowed
  normally (no wide leftover → pressure-neutral). Gated by `SingleBlock && HasRMWRedef`; multi-block/loop
  vregs keep byte-identical old behavior. First cut kept Root wide (`if HasRMWRedef continue`) which
  regressed `pipeline-spill-loop` (num-vgpr=5 pressure) — removed; narrow-Root-last is the fix.
- **Result — NOT a clean win.** SSARA+SSASpiller lit = 87 pass + 1 XFAIL (0 curated regressions).
  Harness full re-run (`scripts/out/ssara-corpus/postfix` vs `full-run2`): **`LLVM ERROR: Use not
  jointly dominated by defs` 117 -> 0 (eliminated)**; `Two-address ... identical` 13->1; net CRASH
  852 -> 785 (-67). BUT per-test transition analysis: **192 files fixed (CRASH->compile) and 125 files
  REGRESSED (compiled-before -> CRASH-now)** — 123 of the 125 are `UseRC && "use operand subreg has no
  register class"`, overwhelmingly wide-descriptor intrinsics (image/buffer, dwordx3 = 96-bit).
- **Root of the regression:** the reverse-order reconstruction changes which def owns which lanes at
  each use, pushing wide-descriptor uses out of `rewriteUseReaching`'s clean whole-operand early-return
  (MachineLaneSSAUpdater.cpp:448) into the partial-REG_SEQUENCE path (line 465-468), where
  `TRI.getSubRegisterClass(OpRC, MO.getSubReg())` returns null for those subreg widths -> assert. It's a
  LATENT weakness in the reconstruction that the reorder exposes, not a coloring/spiller bug.
- **Decision pending (user):** (a) REVERT to baseline (clean, but loses the 192 fixes + reintroduces the
  117), or (b) KEEP and add the coupled fix — handle null `UseRC` in `rewriteUseReaching` (derive the
  REG_SEQUENCE result class for the lanemask when `getSubRegisterClass` is null), then re-run harness to
  confirm net-positive with 0 compile->crash regressions. Recommendation: (b) if the UseRC-null handling
  proves small; else revert and tackle as a scoped follow-up. Repro: `llc -mtriple=amdgcn -mcpu=tonga
  -amdgpu-ssa-regalloc llvm.amdgcn.buffer.store.dwordx3.ll` (@raw_buffer_store_format_immoffs_x3).

### 2026-07-07 — Housekeeping: workflow rules + Cursor command-allowlist/hook investigation [WORKFLOW] [TOOLING]

Meta session — no SSARA compiler code touched. Tuned the human/AI interface and Cursor's auto-run
guardrails. All findings below are EMPIRICALLY verified (Cursor 3.2.16, Windows client + Linux remote).

- **[RULES — added, `.cursor/rules/`]** Two new always-apply rules (APPROVED by user):
  - `evidence-over-memory.mdc` — never assert root cause/behavior/fix from memory or theory; ground every
    claim in real-execution evidence (debug dumps, logs, reproducing run, verifier output); memory/NOTES/
    SHARED_CONTEXT are leads not verdicts; explicitly prefix unverified statements with HYPOTHESIS.
    Motivation (user): repeatedly went astray following confident guesses; labeling saves time.
  - `regression-baseline-is-truth.mdc` — known-good baseline is the sole arbiter of a behavior change; a
    failure that merely MOVES/reshapes (different pass, different error message, different test, original
    assert gone while a new failure appears) is STILL an unresolved regression, never progress; only
    baseline-or-better with no new failure = done.
- **[CURSOR AUTO-RUN — the real mechanism, verified via subagent probes]** Auto-Run Mode = Use Allowlist.
  The authoritative gate is the Settings-UI Command Allowlist, stored CLIENT-SIDE (Windows
  AppData/Roaming/Cursor) — NOT reachable from the Linux worktree, so entries must be added via the UI.
  Matching is command-string PREFIX-based (proved: subagent auto-ran `ninja -C build/user-debug -n` from
  the `ninja -C build/user-debug` entry). It GOVERNS BACKGROUND SUBAGENTS — probe 1: a non-allowlisted
  `echo` in a subagent surfaced a View/Allow prompt in the parent UI and BLOCKED the subagent (transcript
  frozen at 0 lines); probe 2 (after adding `echo`): subagent auto-ran both `echo` and the scoped `ninja`
  with no prompt. Scope builds via the entry `ninja -C build/user-debug`; add the read-only set so
  subagents stop stalling on inspection commands.
- **[SED/FIND LIMIT]** Prefix matching can't carve exceptions -> allowlisting bare `sed`/`find` also allows
  `sed -i` / `find -delete|-exec`. Mitigation applied by user: scope `sed`->`sed -n`, keep `find` OFF the
  allowlist. OPEN ITEM (user: get back to this soon): `find` is agent-critical -> either (a) test whether a
  beforeShellExecution hook DENY is honored INSIDE subagents (then allowlist `find` + deny mutating forms)
  or (b) upgrade to Cursor 3.6+ Auto-review (read-only vs mutating classifier, subagent-aware).
- **[HOOK — installed as audit-only]** `.cursor/hooks.json` -> `.cursor/hooks/shell-guard.sh`. Verified: the
  hook FIRES for subagents (logs their input) but its `permission:allow` is NOT honored for subagents (they
  fall back to the UI allowlist); for the parent it appears honored (confounded by Run Mode). Logging-only
  pattern (read stdin, write NOTHING, exit 0) safely ABSTAINS — verified via probe 3: a non-allowlisted
  `touch` in a subagent still blocked (marker never created), so empty output does NOT default to allow;
  the UI allowlist stays authoritative. `failClosed:false` so logging errors never block. Raw audit trail
  at `.cursor/hooks/state/shell-guard.log`; subagent discriminator = `transcript_path==null`.
- **[HOOK INPUT SCHEMA]** fields: command, cwd, sandbox, session_id, conversation_id, generation_id, model,
  hook_event_name, cursor_version, workspace_roots, user_email, transcript_path.
- **[EXTERNAL-FILE PROTECTION]** The Accept prompt when editing NOTES.md/SHARED_CONTEXT.md is Cursor's
  External-File Protection (they live in the `ssa-spiller-docs` worktree, OUTSIDE the `ssara` workspace
  root) — orthogonal to our approval rule. No per-file/glob auto-accept setting exists in 3.2.x docs;
  options: click `Allow <path>` (persistence undocumented), multi-root `.code-workspace` adding
  ssa-spiller-docs (unverified), or disable External-File Protection globally (UI toggle).

### 2026-07-07 — Corpus-driven SSA-RA crash bucket + 6 fixes (COMMITTED 656baf05) [BUGFIX] [SSAUPDATER] [SPILLER] [SSARA]

- **Method:** ran `scripts/ssara_corpus_harness.py` (built this session; see below) over the full
  `llvm/test/CodeGen/AMDGPU` corpus (3060 .ll) under `-amdgpu-ssa-regalloc`, reusing each test's own RUN
  line, diffing per-function VGPR/AGPR/scratch/occupancy vs Greedy (same cmd minus the flag). Bucketed
  crashes by normalized signature; drove root-cause fixes off the biggest classes. Baseline snapshot
  `scripts/out/ssara-corpus/full-run2` (852 CRASH); final `postfix6` (490 CRASH). Per-test transition
  analysis (compiled-at-baseline -> crash-now) is THE regression gate, not net class counts (net counts
  mislead: fixing one class advances files to the next layer).
- **Six fixes (one commit 656baf05, files: `AMDGPURebuildSSA.cpp`, `MachineLaneSSAUpdater.cpp`,
  `AMDGPUSSARegisterAllocator.{cpp,h}`):**
  1. **RebuildSSA single-block RMW partial-def chains** — a wide vreg built by a chain of subreg defs
     where only the FIRST has `undef` is read-modify-write (a non-undef subreg def implicitly reads the
     super-reg). Fix: gated by `SingleBlock && HasRMWRedef`, choose Root = establishing (earliest-slot)
     def via `(DomPreorder, slot)` tie-break, rename re-defs in REVERSE dom order (latest first) so each
     still-present def reads only dominating not-yet-renamed lanes, Root narrowed LAST. Eliminated
     `Use not jointly dominated by defs` (117->0) and its verifier twin `Reading vreg without a def`.
     Repro `add.ll -mcpu=verde` @s_add_v8i32.
  2. **MachineLaneSSAUpdater `rewriteUseReaching` UseRC** — derive the REG_SEQUENCE result class from the
     base-0 REBASED lane mask (`rebaseLaneMask(OpMask,OpMask)` -> `getSubRegIndexForLaneMask` ->
     `getSubRegisterClass`), not the raw operand subreg. Unaligned super-reg subregs (e.g. sub1_sub2_sub3
     of sgpr_128) have NO class via `getSubRegisterClass`. Repro `llvm.amdgcn.buffer.store.dwordx3.ll`.
  3. **`eliminateRegSequences` unaligned dest slice** — when `getSubReg(Dst,SubIdx)` is NoRegister
     (SGPR tuples >=64-bit exist only at aligned bases: SGPR_64 stride 2, SGPR_96/128 stride 4 per
     SIRegisterInfo.td), lower that source as per-dword 32-bit copies via `getChannelFromSubReg` +
     `getSubRegFromChannel`. Fixed the `$noreg = COPY` -> MachineCopyPropagation assert.
  4. **`rewriteOperands` undef operands** — a vreg appearing only as an `undef` operand has no value to
     color; assign `RegClassInfo.getOrder(RC).front()` (undef flag preserved so verifier permits the
     read). Fixed 175 of the `Virtual register not colored` (286->111).
  5. **`resolvePermutation` AGPR cycles** — AGPR is a distinct file (no swap/xor primitive); an AGPR
     permutation cycle must use an AGPR scratch (plain COPYs, legalized downstream), not the SGPR path
     that emitted an illegal `$sgpr0 = COPY $agpr15`. Added `MaxAGPRIdx`; track high-water by the CHOSEN
     physical register's file (also fixes latent av_*->VGPR undercount). Repro
     `llvm.amdgcn.mfma.form.ll -mcpu=gfx950 --amdgpu-mfma-vgpr-form=0`.
  6. **RebuildSSA `flattenRegSequences`** — lane-by-lane reconstruction wraps each re-def in a 2-source
     REG_SEQUENCE, producing a growing-width tower (areg_64->96->...->384); with no coalescer these live
     wide intermediates inflate pressure (bf16 MFMA: 43 AGPR / occ 5 vs greedy 32 / occ 8). Single
     forward pass, per-parent local drain, inline single-use whole-read child RS composing lanes via
     `composeSubRegIndexLaneMask` (NOT `composeSubRegIndices`, which silently mis-handles compositions
     that miss a defined subreg index). Restored bf16 MFMA to 32 AGPR / occ 8 (== greedy).
- **Result (postfix6 vs full-run2): CRASH 852 -> 490 (-362), 362 files fixed, 0 compiled->crash AND 0
  compiled->worse-alloc regressions; SSARA+SSASpiller lit 87 pass + 1 XFAIL.** Clean Pareto improvement.
- **Key learnings (also new always-apply rules the user added: `evidence-over-memory.mdc`,
  `regression-baseline-is-truth.mdc`):** (a) a test that ABORTS has NOT passed — never call a fix good
  because the crash moved to another pass; (b) baseline for "regression" = OUR pre-change stack, and the
  harness dOcc/dVgpr is SSARA-vs-GREEDY — always state which; (c) grep the component for existing
  helpers (`rebaseLaneMask`, `getSubRegIndexForLaneMask`, `composeSubRegIndexLaneMask`,
  `getCoveringSubRegsForLaneMask`) BEFORE theorizing from stack traces; (d) `composeSubRegIndices(a,b)`
  = b within a (a outer) AND silently returns garbage for illegal compositions — prefer lane-mask
  composition. `SmallPtrSet<Register>` does not compile (Register is not a pointer) -> use `DenseSet`.
- **Remaining top crash buckets (postfix6):** `Virtual register not colored` 111 (non-undef sub-cause),
  `Reading vreg without a def` ~98, `Using an undefined physical register` ~87, `PHI with NoPHIs` ~47
  (mostly fatal-path MF.verify collateral), `incorrect register class` ~27, tied-use ~18, failed-physreg
  ~13. Next targets by impact: the residual `not colored` 111 and `undefined physical register` 87.
- **Corpus harness `scripts/ssara_corpus_harness.py` (github/scripts/, NOT llvm-project):** `run`/`report`
  subcommands; per test reuse RUN line, strip FileCheck/`-o`, inject `-amdgpu-ssa-regalloc`
  (+`-verify-machineinstrs`), diff vs Greedy; buckets CRASH(sig)/OK_*/DIFF_COALESCING/MIXED/
  REGRESSION_OCC_OR_SPILL/PREEXISTING_FAIL/TIMEOUT/NO_METRICS/SKIP_*; parallel `--jobs` (def ncpu/2),
  resumable `results.jsonl`. Regression check = per-test bucket transition vs a baseline run dir.
  Metrics parsed from `; TotalNumSgprs/NumVgprs/ScratchSize/Occupancy` + `.set *.num_vgpr/.numbered_sgpr/
  .num_agpr/.private_seg_size`. NOTE `.num_vgpr` omits AGPRs — occupancy can drop with VGPR unchanged
  (MFMA); check `.num_agpr` too.

### 2026-07-07 (PM) — Corpus crash reduction continued: 4 more fixes (#7-#10) [BUGFIX] [SSARA] [SSAUPDATER]

- **Continuation of the corpus-driven crash triage.** Baseline for regression gating stays
  `scripts/out/ssara-corpus/full-run2` (852 CRASH). Iterated fix -> build -> lit -> harness, using the
  per-test bucket TRANSITION (compiled-at-baseline -> crash-now) as the ONLY regression gate. Runs
  postfix .. postfix11. **Net today: CRASH 852 -> 275 (-577, -68%), 577 files fixed, 0 compiled->crash
  and 0 compiled->worse-alloc regressions across ALL 10 fixes; SSARA+SSASpiller lit 87 pass + 1 XFAIL
  throughout.**
- **Commits (user commits manually):** 6-fix commit `9b30c8ab` (amended from the mangled-subject
  `656baf05`; force-pushed with `--force-with-lease` after the amend diverged from remote — content
  identical, only subject fixed). Then `4cb211e6` (#7), `867d2e17` (#8), `60727a8a` (#9). **#10 is
  UNCOMMITTED** (working tree: `AMDGPUSSARegisterAllocator.{cpp,h}`) — user is holding it until the
  call-site `undefined physical register` class is FULLY resolved (only the call-crossing sub-cause is
  fixed; the CSR save/restore sub-cause remains).
- **#7 [AMDGPU] color defs/uses by operand FLAG, not position** (`AMDGPUSSARegisterAllocator.cpp`
  `color()`): `MI.defs()`/`MI.uses()` key off operand position (`getNumExplicitDefs()`), which is 0 for
  INLINEASM (flag-interspersed operands), so inline-asm-defined vregs were never colored. Iterate
  `MI.operands()` filtered by `isDef`/`isUse`. Implicit defs EXCLUDED (`|| MO.isImplicit()`): they are
  call/instr clobbers (`implicit-def $scc/$sgpr32`) that `MI.defs()` also skipped; marking them occupied
  (never freed) would exhaust the file (regressed `cc-update.ll` until excluded). INLINEASM constraint
  reg defs are EXPLICIT (verified: MIR prints `def %8`, not `implicit-def`); only clobbers are implicit.
  `Virtual register not colored` 286 -> 1.
- **#8 [CodeGen][MachineLaneSSAUpdater] source undef lanes of a super-use as undef** (`buildRSForSuperUse`):
  a whole-register use of a partially-undef wide value (e.g. buffer descriptor with a poison base ptr,
  `%17.sub0_sub1` never written) decomposed into a REG_SEQUENCE sourced the undef lanes as a plain read
  -> `Reading vreg without a def`. Split `LanesFromOld` into defined (union of OldVR subrange lanemasks;
  NO `liveAt(QueryIdx)` — that is too strict, base slot, and wrongly marked defined lanes undef, which
  regressed 3 SSASpiller reload tests) vs undef (no subrange) -> source undef part with `RegState::Undef`
  so Dest stays fully covered. `Reading vreg without a def` 85 -> 43.
- **#9 [AMDGPU] do not reuse a dying-use physreg for an early-clobber def** (`color()`): kills-before-defs
  frees a dying source so a def can reuse it; INVALID for early-clobber defs (live while uses are read).
  `early-clobber $sgpr0_sgpr1 = S_LOAD_ec $sgpr0_sgpr1` shared the source reg -> clobbered read. Fix:
  when the MI has an early-clobber def, DEFER freeing dying uses (two lists: `DeferredUnits` for physreg
  per-unit resets, `DeferredFree` for colored-vreg `markFree` — the two free at different granularity
  because physreg reg-units are independently live while a colored vreg dies atomically) until AFTER the
  def loop (still freed for later instrs -> no leak). Two loops over operands = kills-before-defs phase
  separation (all use-frees must precede all def-colorings).
- **#10 [AMDGPU] do not color a live-across-call vreg to a clobbered reg (UNCOMMITTED, INCOMPLETE)**
  (`color()` + `pickFreePhysReg`, new member `CallSites`): coloring ignored call clobbers, so a vreg live
  across a call got a reg the call destroys (caller-saved via `csr_amdgpu` regmask, OR an explicit call
  def like the return-address `$sgpr30_sgpr31`) -> `Using an undefined physical register`. Fix: collect
  `(callDefSlot, MachineInstr*)` per call (regmask-bearing MI); in `pickFreePhysReg` reject a candidate
  if, for any call the vreg is `liveAt(CallSlot.getRegSlot())`, `CallMI->modifiesRegister(PR, TRI)` OR a
  regmask operand `clobbersPhysReg(PR)`. (First cut checked only the regmask -> missed the explicit
  `$sgpr30_sgpr31` def; refined to `modifiesRegister` + regmask.) `undefined physical register` 64 -> 30.
  **REMAINING (why uncommitted):** the other 30 are a DIFFERENT sub-cause — CSR save/restore in the frame
  prologue/epilogue, e.g. `$sgpr33 = frame-destroy COPY $sgpr6` in `callee_saved_sgpr_vgpr_func`
  (`call-preserved-registers.ll`, `callee-frame-setup.ll`). Root-cause that next to finish the class.
- **Remaining crash classification (postfix11, 275 crashes / 25 classes), by owner:** SSA-RECONSTRUCTION
  113 (43 `Found PHI with NoPHIs` = mostly fatal-path MF.verify collateral; 43 `Reading vreg without a
  def` non-poison sub-cause; 18 `DefOp NewDefMI should have a def operand` e.g. InlineAsmCrash.ll; 5
  multiple-defs; ...), OPERAND-REWRITE/physreg 92 (30 `undefined physical register` = CSR save/restore;
  26 `Invalid subregister index`; 25 `Operand has incorrect register class`; 6 remaining-vreg; 3
  MachineCopyPropagation), RA-COLORING 50 (24 `Failed to find free physreg` sdiv/srem i64 + a few from
  the new call-clobber constraint; 18 tied-use; 6 reg-class-not-set), INSTR-LEGALITY 9, FRAME/harness 10
  (3 `Too many positional` = harness parse residue, not SSARA).
- **NEXT (tomorrow):** (1) finish the call-site class — root-cause the CSR save/restore `undefined
  physical register` (frame prologue/epilogue COPYs of callee-saved regs), then commit #10; (2) then by
  impact: `Reading vreg without a def` (43), `Invalid subregister index` (26), `Operand has incorrect
  register class` (25), `DefOp NewDefMI` (18). The `Found PHI with NoPHIs` (43) should shrink as
  underlying fatal-path errors are fixed (diagnostic collateral).

### 2026-07-08 — [REFACTORING] AMDGPUSSARegisterAllocator::color() cleanup (DEFERRED until crash-free)

Fact-collection for a `color()` refactor to do ONCE the AMDGPU corpus is crash-free (user decision:
not now). All observations below are about `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp`.

- **[ROOT SMELL] `color()` is a HYBRID of two occupancy models** bolted together:
  1. a FORWARD-WALK model — `OccupiedRegUnits` mutated by `seedOccupiedAtBBEntry`, the per-instruction
     kill-scan (`markFree` dying uses), `markOccupied` on defs, and the early-clobber deferred-free; and
  2. an INTERFERENCE model — `LI.overlaps(VI)` scans inside `pickFreePhysReg`.
  The same question ("what is occupied for this pick?") is answered two ways, which is why WIDER-def
  handling is spread across THREE places and call clobbers are re-checked per candidate.

- **[TARGET DESIGN] Collapse to a single interference-based greedy** (width-descending). `pickFreePhysReg`
  overlaps the candidate against: all already-colored vregs (`ColorMap` + `LIS`), physreg live ranges,
  and call-clobber masks. Consequences:
  - kills-before-defs reuse FALLS OUT for free (a source dying at the def does not overlap the def, so
    its physreg is reusable — no `markFree` juggling);
  - early-clobber becomes UNIFORM (the EC def DOES overlap the instruction's uses, so no reuse — no
    special deferred-free lists needed);
  - `OccupiedRegUnits`, `seedOccupiedAtBBEntry`, `WiderDefs`, and the `!= Width` block's `markOccupied`
    all DISAPPEAR (one mechanism instead of four).
  - PERF caveat: naive is O(V x colored) overlaps (already flagged: P1 interval-tree TODO). Correctness
    surface is large (PHIs, wide-tuple alignment, physreg live-ins) -> full lit + corpus-harness
    0-regression gate required.

- **[REDUNDANCIES confirmed today]**
  - `WiderDefs` per-block pre-scan (build ~line 248 + use in `pickFreePhysReg` ~80-85) is a SUBSET of the
    function-wide `ColorMap` wider-overlap scan in `pickFreePhysReg` (~86-92). Functionally redundant —
    an O(block) fast path layered on the O(|ColorMap|) backstop; both run.
  - The `markOccupied` in the `width != Width` block (~343-350) is redundant with those overlap scans
    (the pick re-derives wider occupancy via `overlaps()` each call) AND is never paired with a
    `markFree` -> can leave a wider def occupied past its death (mildly PESSIMISTIC, not incorrect). The
    ESSENTIAL part of that block is only the `continue` (color CURRENT-width defs; skip wider=colored and
    narrower=future-pass). NOTE: `if (WiderDefs.count(Reg)) continue` is NOT an equivalent rewrite — it
    would miss NARROWER defs (which must also be skipped) and `WiderDefs` is keyed by physreg, not vreg.

- **[STATIC vs DYNAMIC — combining the pre-scans]** `CallSites` (~229-236) is STATIC (regmasks + call
  defs don't change during coloring) -> correctly precomputed ONCE before the width loop. `WiderDefs` is
  DYNAMIC because it reads `ColorMap` (colors accrue per width pass) -> cannot be precomputed with colors
  up-front. BUT its STRUCTURAL part (per-def `{LiveInterval*, width, defSlot}`) IS static and can be
  collected in the SAME single function-wide walk as `CallSites`, keyed by vreg; the color is a
  `ColorMap.lookup` at pick time. So the refactor should do ONE function-wide pre-scan producing (a)
  per-call clobber unit `BitVector`s and (b) a per-vreg `{LI, width}` index; `WiderDefs` as a distinct
  list is then eliminated.

- **[CONTAINED WINS to fold into the refactor]**
  - Per-width def WORKLISTS: bucket defs by width up-front and iterate only current-width defs, instead
    of re-walking every instruction each pass and filtering `!= Width`.
  - Per-call clobber precompute: change `CallSites` to `(SlotIndex, BitVector ClobberedUnits)` built once
    (regmask-clobbered regs' units + explicit call-def units); in `pickFreePhysReg` replace the
    per-candidate `modifiesRegister`/regmask loop (~102-120) with `if (VI.liveAt(CallIdx)) OccupiedAtDef
    |= Clob;` -> O(calls) instead of O(calls x candidates x operands).
  - Small helper `static bool hasEarlyClobberDef(const MachineInstr &MI)` for the ~278-283 inline scan
    (no standard `MachineInstr::hasEarlyClobber()` exists).

- **[INVARIANTS worth keeping as asserts]** In the WiderDefs/interference lookup: a WIDER def must be
  colored by an earlier width pass; the ONLY legit uncolored case is a dead vreg (`reg_nodbg_empty`,
  whose width `classifyVRegs` never added to the order). Guard as `assert(found ||
  MRI->reg_nodbg_empty(Reg))` rather than silently skipping — a live wider def with no color is a bug.
  (Proposed earlier this session; not yet applied.)

- **[WHY the current split exists — do NOT flatten blindly]** `markFree`/`markOccupied` are WHOLE-register
  (all units) and valid only for atomically-live values (colored vregs); PHYSREG uses free at per-unit
  granularity because reg-units carry independent `LIS->getRegUnit(Unit)` liveness (a wide physreg use
  can have one unit dead, one live). The two operand loops (kill-scan then def-loop) implement
  kills-before-defs ordering. The early-clobber deferred-free uses TWO lists (`DeferredUnits` per-unit for
  physregs, `DeferredFree` whole-reg `markFree` for colored vregs) for the same granularity reason. ALL
  of this folds away in the interference model but must be preserved as long as the forward-walk model
  stays.

- **[PRE-EXISTING PHYSREGS ARE STATIC — added 2026-07-08]** During `color()` we only populate
  `ColorMap`; no operand is rewritten until `destroySSAAndRewrite()` runs afterward. Therefore every
  physical register already present in the input MIR (ABI live-ins, inline-asm clobbers, call clobbers,
  physreg defs/uses) is IMMUTABLE for the whole coloring phase, and its liveness + clobber points are a
  STATIC per-function property. Consequences for the refactor:
  - The physreg half of the forward walk is redundant RE-DERIVATION of `LIS->getRegUnit(Unit)`: the
    per-unit free-on-kill scan (~303-313), the `markOccupied` for physical defs (~347-349), and the
    physreg branch of `seedOccupiedAtBBEntry` all just reconstruct "which pre-existing physreg unit is
    live at slot S", which `LIS->getRegUnit(U).liveAt(S)` / `.overlaps(VI)` answers directly. In the
    interference model, `pickFreePhysReg` tests a candidate `PR` against (a) DYNAMIC vreg occupancy
    (`ColorMap`, this pass only) + (b) STATIC reg-unit overlap + (c) the regmask set — and (a) becomes the
    ONLY thing the walk maintains. `OccupiedRegUnits` stops conflating physreg + vreg occupancy.
  - The ONE clobber kind NOT captured by reg-unit ranges is REGMASKS (calls) — they create no reg-unit
    segment. So the static pre-scan's genuine payload is exactly the regmask/`CallSites` set (+ the
    `MRI.addPhysRegsUsedFromRegMask` fold). Everything else (inline-asm dead-clobbers, ABI live-ins,
    physreg defs) is already in `LIS->getRegUnit`.
  - User's framing (this session): collect the static pre-existing-physreg facts ONCE in the function-wide
    pre-scan and PROMOTE them into the blockwise structures (seed `OccupiedRegUnits` etc.), instead of
    re-querying `liveAt(NextSI)` per instruction per width pass.
  - CAVEAT: the early-clobber def/use reuse ordering (`HasEC`/`DeferredUnits`, ~307-308) must survive as a
    SLOT choice (query at `RegSlot` vs `EarlyClobberSlot`), not as incremental free/defer; expected to fall
    out of slot-accurate `overlaps` but VERIFY, don't assume.

- **[CLOBBER-SITE COLLECTION GAP — crash root cause, 2026-07-08]** The minimal crash fix landing before
  this refactor already generalizes the pre-scan clobber-site collection: `CallSites` was built ONLY from
  `MO.isRegMask()`, so INLINE-ASM physreg clobbers (`call void asm sideeffect "", "~{v4},..."` lowered to
  `INLINEASM ... implicit-def dead early-clobber $vgprN`, no regmask) were invisible to `pickFreePhysReg`'s
  live-across check -> a value live across the asm got colored onto a clobbered reg -> "Using an undefined
  physical register" (9 corpus tests; cs-chain, spill-scavenge-offset, vgpr-tuple-allocation,
  spill-vgpr-block, vgpr-mark-last-scratch-load, ...). Fix predicate: an instruction is a clobber site if
  it has a regmask OR defines a non-reserved physical register
  (`MO.isReg() && MO.isDef() && MO.getReg().isPhysical() && !MRI->isReserved(...)`). Completeness rests on
  the MachineVerifier invariant that EVERY physreg write is a def operand or a regmask; `isDef()` covers
  implicit/early-clobber/dead defs; the `!isReserved` filter is lossless (allocatable candidates from
  `getOrder` share no reg unit with a reserved-only def). In the refactor this same set feeds the
  per-call/per-clobber `BitVector ClobberedUnits` precompute (the [CONTAINED WINS] bullet above).

### 2026-07-08 — [DESIGN] Fragmentation-aware spiller + greedy fallback (for "Failed to find free physreg") [SPILLER] [RA] [THEORY]

Captured for the FUTURE spiller redesign (do NOT start until crash-free milestone; recorded so the
full reasoning is preserved). Triggered by triaging the `Failed to find free physreg` corpus bucket
(`spill-scavenge-offset.ll` @test on verde). All evidence gathered live this session.

**Symptom / evidence.** `@test` (kernel, NO attributes) fails coloring on a `VReg_128`. The RA's
allocation order for VReg_128 is `VGPR0_1_2_3 ... VGPR60_61_62_63` (only v0-v63 available). The kernel's
inline asm clobbers `v4,v8,...,v224` (every 4th VGPR) via `call void asm sideeffect "","~{v4},~{v8},..."`
→ `INLINEASM ... implicit-def dead early-clobber $vgprN`. Within v0-v63 the clobbers `v4,v8,...,v60`
fragment the file so the ONLY 4-wide contiguous free run is `v0-v3`; every inter-clobber gap is 3 wide.
So at most ONE VReg_128 can be placed; a second live VReg_128 → assert.

**Greedy comparison (ground truth, corrected mid-investigation).** Greedy `@test`: NumVgprs=225,
Occupancy=1. INITIALLY hypothesized greedy lowers occupancy to get a bigger budget — WRONG. Evidence:
greedy MIR has only 59 distinct `$vgpr`; every VGPR >= 64 (up to v224) appears ONLY inside INLINEASM
(clobbers), ZERO real value allocations above v63. So greedy ALSO allocates values in v0-v63; the
NumVgprs=225 / Occupancy=1 is FORCED by the inline-asm clobber of v224 (highest referenced reg), not by a
larger allocation budget. Greedy survives because it SPILLS ON PLACEMENT FAILURE (allocator-level
fallback) — it keeps <=1 wide tuple live at a time. `ST.getMaxNumVGPRs(MF)` = 64 for @test (default
occupancy); this is a red herring — both paths allocate within v0-v63.

**Root cause (not what the bucket name suggests).** NOT "spiller ignores inline-asm clobbers" (it counts
them into `LivePhysRP`, spiller line ~340-343) and NOT an occupancy bug. It is: the spiller decides spills
from a SCALAR 32-bit-slot pressure metric (`CurRP < RPLimit`), which is blind to tuple ALIGNMENT /
FRAGMENTATION. The scalar count can be satisfied while wide-tuple placement is impossible because scattered
fixed clobbers carve the file so no W-wide contiguous block remains. (Secondary, separate bug to confirm:
dead inline-asm clobbers are added to `LivePhysRP` as PhysDefs but, being dead, never decremented by a
killing use → `LivePhysRP` likely stays inflated AFTER the asm = an over-count. The redesign's static
matrix eliminates this by construction.)

**Theory framing (why this does NOT defeat SSA RA).** The SSA colorability theorem (chordal interference,
MAXLIVE<=k ⟹ k-colorable via PEO) holds ONLY for (a) uniform/non-aliased unit registers and (b) NO
pre-coloring. AMDGPU breaks both here: register aliasing (VReg_128 over 4 units → "register allocation by
puzzle solving", Pereira & Palsberg) AND scattered pre-colored inline-asm clobbers. Coloring with
pre-assigned registers + aliasing is NP-hard (Bouchez et al.). So `MAXLIVE<=k` in 32-bit slots is
NECESSARY but NOT SUFFICIENT. For the common case (no adversarial scattered clobbers) the theorem holds and
the corpus is mostly OK; the failure is the pre-color+aliasing fringe.

**What the design ALREADY handles (recap from SSA_RA_Coloring.md §3-4,§8).** (1) Alignment (SGPR 64-bit
stride 2 / 96-bit+ stride 4; VGPR Align2 on gfx90a+) via the register-class allocation ORDER —
`RegClassInfo.getOrder(RC)` yields only validly-aligned tuples; overlap checked at reg-unit granularity.
(2) SELF-fragmentation (our narrow defs blocking our wide defs) via WIDTH-DESCENDING multi-pass coloring
(widest first sees an unfragmented file). NEITHER handles EXTERNAL fragmentation from scattered pre-colored
physregs — width-descending's precondition "the widest pass sees an unfragmented file" is FALSE when fixed
clobbers pre-fragment it; we can reorder OUR allocations but not un-fragment pinned obstacles.

**HARD ARCHITECTURAL INVARIANT (the reason SSA RA exists — do not violate).** COLORING MUST NEVER INSERT
INSTRUCTIONS. Spill/reload placement on AMDGPU is only correct when store and reload observe consistent
EXEC (`EXEC(spill)==EXEC(reload)`) or run in WWM. After SI_CF is lowered, finding such a point needs full
exec-mask analysis and is fragile/error-prone. The EARLY SPILLER exists to make that placement decision
ONCE, in a dedicated pass, so no later stage must. Therefore a greedy-style "spill when pickFreePhysReg
fails" is FORBIDDEN — it drags the fragile EXEC/WWM analysis back into the allocator at the worst time.
Consequence: coloring must be GUARANTEED to succeed BEFORE it starts; there is NO in-flight recovery.

**Chosen design (records both halves).**

1. **Fragmentation-aware pressure in the early spiller.** Replace scalar `CurRP<limit` with a per-width,
   per-position feasibility test. `F` is NOT additive — it is a capacity/packing test parameterized by
   width. At slot P for class RC (width W units, stride s):
   - `preColored(P)` = fixed obstacles at P = `{u : LIS->getRegUnit(u).liveAt(P)}` (physical defs/uses:
     inline-asm clobbers, ABI live-ins, physreg defs) ∪ regmask clobbers at call slots. NOTE: regmasks
     create NO reg-unit segment (stored as RegMaskSlots) → LIS alone MISSES call clobbers; fold in the
     `CallSites` regmask set as point-obstacles. This "static pre-colored liveness" is otherwise FREE from
     LIS reg-unit ranges (no separate matrix needed) and REPLACES the buggy incremental `LivePhysRP`
     forward-walk (fixing the dead-clobber over-count).
   - `freeUnits(P) = AllUnits(RegFile) \ preColored(P) \ widerColored(P)`.
   - `capacity_W(P) = Σ_runs alignedBlocks(run_len, W, s)` (⌊len/W⌋ for stride-1 VGPR; aligned-start count
     for stride-2/4 SGPR) over maximal contiguous free runs.
   - `demand_W(P)` = # live vregs of class RC at P (from LIS, per-width — NOT the scalar `RPTracker.maxRP`,
     which stays only as the coarse necessary bound).
   - Spill class-RC values where `demand_W(P) > capacity_W(P)`.
   - The 4th term `widerColored(P)` is NOT static (depends on coloring placement). Resolve by running the
     spiller WIDTH-DESCENDING (mirror coloring): for W=Wmax there are no wider vregs so capacity is EXACT
     from pre-colors; for narrower W charge kept wider vregs as `Σ ceil(width/W)` blocks (worst-case count,
     sound, possibly pessimistic).
   - Signature crystallized: `feasible_W(P) = F(defRC, demand_W(P) from LIS, preColored(P) arrangement,
     widerFootprint_W(P))`. The pre-color arg must carry ARRANGEMENT (which units / runs), NOT a count —
     the fragmentation lives entirely in positions.

2. **Early, whole-function greedy fallback gate (the ONLY recovery, since coloring can't spill).** Because
   there is no coloring-time safety net, decide BEFORE `RebuildSSA` whether the SSA path is safe; if not,
   route the ENTIRE function to the greedy chain (which owns the legacy EXEC/WWM spill machinery — accepted
   for the rare fringe). Sound local infeasibility test (static): for each instruction I at slot P and each
   width W, `needW = #width-W operands of I that must coexist` (its own defs+uses, tied/EC-aware); if
   `needW > capacity_W(P)` then NO spilling can help (can't spill an operand being read now) → INFEASIBLE →
   fall back. CRITICAL: this local test is NECESSARY-NOT-SUFFICIENT (global alignment+precolor assignment
   is NP-hard), and with NO coloring-time recovery the gate MUST be SOUND-TOWARD-FALLBACK / conservative:
   over-approximate risk (e.g. fall back if the function merely contains scattered physreg clobbers
   overlapping any wide-tuple W>=64 live range) rather than risk a no-recovery crash. Start CONSERVATIVE
   (few lines, provably safe, converts the whole bucket from crashes → correct greedy codegen = baseline
   restored); tighten toward the precise `needW>capW` trigger later as the fragmentation-aware spiller
   matures to shrink fallback frequency.

**Mechanical hurdle for the fallback.** The two allocators are different pass chains added at module scope
(SSA: RebuildSSA→SSA-Spiller→SSA-RA; greedy: PHIElim→TwoAddr→RAGreedy→VirtRegRewriter). Per-function
routing options: (1) early feasibility pre-pass sets a per-function flag before RebuildSSA; SSA-path passes
early-return on flagged fns and the greedy chain (present in the pipeline) runs only on flagged fns —
heaviest, reuses greedy verbatim, aligns with "pre-scan decides"; (2) in-allocator split-at-color — RULED
OUT by the no-insertion invariant. → Option 1 is the path. Decision MUST precede RebuildSSA (it re-SSAs the
function).

**Net layering (no coloring-time spills anywhere):** fragmentation-aware early spiller handles all it can
PROVABLY guarantee (spill-free coloring preserved) → conservative early gate routes the residual NP-hard
fringe to greedy. Goal: make the spiller strong enough that greedy fallback is rare, while the gate
guarantees correctness. Coloring stays a pure, non-inserting assignment — the whole point of the effort.

### 2026-07-08 — Housekeeping: workspace-layout rule, AGENTS drift fix, gdb debugging tooling [WORKFLOW] [TOOLING]

Meta/workflow session (no SSARA compiler code changed).

- **[RULE] `.cursor/rules/workspace-layout.mdc`** (always-apply, APPROVED): canonical worktree layout under
  `github/` (ssara [primary/integration], next-use-analysis [NUA], early-ssa-spiller [SSA Spiller],
  mssa-updater [+gtest harness], llvm-project [clean upstream], scripts [permanent tools], ssa-spiller-docs
  [the "docs" repo]) + script placement policy: permanent/multi-session → `scripts/`, throwaway → `/tmp`.
- **[AGENTS DRIFT — root cause + fix]** User noticed the corpus harness (built 07-06, used through 07-07)
  had NO reference in AGENTS.md though richly in SHARED_CONTEXT/NOTES. Evidence-based root cause: AGENTS is
  fed ONLY by `agents-memory-updater`, whose transcript index was stale/divergent — two files:
  `ssara/.cursor/hooks/state/continual-learning-index.json` (@2026-07-04, key `last_updated`) vs
  `~/.cursor/projects/…/…` (@2026-07-06T18:01, key `updated_at`) — never processed the 07-07 sessions.
  "Save context" reliably updates NOTES/SHARED_CONTEXT but the AGENTS promotion step didn't run. Fixed:
  recorded the harness as a durable AGENTS fact, marked agenda item (2) DONE, corrected the stale worktree
  bullet. LESSON: on "save context", promote durable tools/facts DIRECTLY into AGENTS, not just the updater.
  Open: reconcile the two divergent index files / run agents-memory-updater to catch up 07-07.
- **[TOOL] `scripts/gdbctl.sh`** — persistent, agent-driven gdb across separate tool calls (background gdb
  reads a FIFO; sentinel-synced; `start`/`send`/`log`/`status`/`stop`; each `send` returns only that
  command's output; breakpoints + frame persist). Tested end-to-end on a small binary AND verified
  controlling the 1.8 GB debug `llc` (first symbol-resolving `break` ~1-2 min then fast; `GDBCTL_TIMEOUT`
  default 60s, `GDBCTL_DIR` for a 2nd session).
- **[SKILL] `~/.cursor/skills/gdb-debugging/SKILL.md`** (personal, APPROVED) — wraps gdbctl + a 6-step
  "debug the test crash" algorithm (reproduce+capture signature → baseline check → gdb bt/inspect → narrow
  via `-debug-only`/`-stop-after` + `scripts/mir2cfg.py` → root-cause with evidence → STOP+present patch),
  chaining the triage/evidence/regression/approval rules; auto-invokes on "debug the test crash".
- **[CURSOR FACT] skill loading:** skills are discovered at startup/chat-start → a newly added/edited skill
  is available only in NEW chats (or after restart), NOT already-open ones (verified empirically: the
  just-created skill was absent from the creating chat's own available-skills list). Rules differ — they are
  re-scanned per message and reach open chats on the next turn.

### 2026-07-08 — [MEETING] RPTracker per-register-class pressure for the fragmentation-aware spiller [SPILLER] [RA]

Direction agreed on a call, to IMPLEMENT the fragmentation-aware spiller design recorded earlier today
(the per-width capacity `F`). Implementation vehicle = extend the register-pressure tracker itself instead
of a side computation:

- **Augment `GCNUpwardRPTracker` (GCNRegPressure) with a BitVector**: one bit per PRECOLORED physreg
  (the pre-existing, immutable physregs — inline-asm clobbers, ABI live-ins, call/physreg defs). The
  tracker already walks liveness; it bookkeeps physreg liveness ALONGSIDE vreg liveness as it recedes.
- **New API: report RP PER REGISTER CLASS**, `RP(RC)` — how many slots of that class's width are
  free/used at the current SlotIndex.
- **Naive model** (first cut): a class limit = `NumAvailVGPR / K` where K = the class's dword width
  (meeting example said "VReg_64 limit = NumAvailVGPR/4"; NOTE arithmetic check: VReg_64 = 2 RU so a
  pure count model is `/2`; `/4` is VReg_128 — reconcile which was meant. The general query is "how many
  free 4-RU (128-bit) slots are available/used at this SlotIndex", i.e. per-tuple-width slot counting).
- **Query the tracker**: "how many free {K}-RU slots available/used at this SlotIndex" → the spiller
  compares demand-per-class vs this and spills when a class's slots are exhausted.

CONNECTION / caveat (from prior design entry): a pure `NumAvail/K` COUNT is the necessary bound but is
still fragmentation-BLIND (it counts free RUs, not free CONTIGUOUS aligned windows). The
scattered-precolor case (spill-scavenge-offset) needs the CONTIGUOUS-slot query (Σ ⌊run/K⌋ over free
runs after removing precolored bits) — which the same precolored-BitVector-in-RPTracker can compute by
scanning runs rather than popcount/K. So: start with the naive per-class count (catches the a-v-* pinned
wide-value high-pressure cases where greedy also spills), then upgrade the same API to run-based counting
for true fragmentation. This keeps the "coloring never spills" invariant: the tracker-backed per-class
pressure drives EARLY spill decisions only.

Evidence backing this (gdb triage of `global_atomic_xchg_i32_ret_av_av_no_agprs`, gfx90a): two live
`vreg_1024_align2` values pin all of v0-v63 (inline-asm implicit-def $vgpr0..63 + copies), leaving no room
for a `vreg_64_align2` REG_SEQUENCE `%21` → `Failed to find free physreg`. Greedy compiles it at
NumVgprs=64 + ScratchSize=132 (it SPILLS). So our spiller UNDER-spills at that point; a per-class RP that
sees the two 1024-bit values consuming the VReg_64 slot budget would have forced the spill. This is a
distinct sub-cause from scattered-precolor fragmentation, but the SAME per-class-RP mechanism addresses
both (count first, runs later).

---

## 2026-07-09/10 (late) — crash-cluster fixes; corpus 224→195 good, then +22 regression from 3 risky changes

ALL UNCOMMITTED (working tree, ssara). Full detail distilled into SHARED_CONTEXT.md
(2026-07-09/10 section). Summary:

- CORPUS-SAFE (KEEP, net CRASH 224→195): (1) loop-carried PHI self-reference fix in
  `MachineLaneSSAUpdater::rewriteDominatedUses` (`UseMI==DefMI && !DefMI->isPHI()`); (2) partial
  reload-as-redef preserves un-spilled lanes — drop unconditional `RegState::Undef` in
  `SIInstrInfo::loadRegFromStackSlot` (SubRegIdx!=0, spiller-only caller) + spiller re-applies undef only
  when complement dead at reload (`liveAt(RegSlot)`); (3) `CallSites` predicate `!isReserved`→
  `isAllocatable`; (4) stale `v_swap` CHECK regen in lowerphi-critical-edge-no-split.ll.
- RISKY (run2 +22, likely REVERT #7 first): (5) spiller call-clobber pressure charge; (6) RA
  call-clobber color-choice bias (dominance-order-safe per Hack); (7) RebuildSSA single-partial-def
  narrowing — fixed undef-handling-crash-in-ra.ll but +10 "Invalid subregister index" +3 "even aligned
  vector regs" (illegal subreg/align2 from narrowing). 
- FINDINGS: "Failed to find free physreg" is a CROSS-CALL COLORING problem (greedy ScratchSize:0, no
  spill) needing coalescing/eviction, not spilling. Spiller vs RA RPLimit mismatch (getMaxNumVGPRs=128
  incl AGPR half vs allocatable VGPR_32=64) — HIGH PRIORITY, recorded in BACKLOG, not yet changed.
- NEXT: revert #7 → re-run corpus → confirm ~195; commit safe set #1–#4; attack free-physreg via
  coalescing. Corpus JSON: /tmp/ssara-corpus-run (195), /tmp/ssara-corpus-run2 (217).

## 2026-07-10 (evening) — bitcast-padding fix committed; corpus 195→103; guard-test backlog

All the 2026-07-09/10 crash-cluster work is now COMMITTED (git log tip series: fad0fc8..75b82eb),
i.e. the "risky #7 narrowing" was dropped and the safe set + 4 further fixes (self-tied undef 030d4d,
V_SWAP_B16 effb63, NewDefMI 400c67, WMMA-EC tied-use 75b82e) landed. Then this session:

- **NEW FIX committed (36154bd): oversized-padding super-use** in `MachineLaneSSAUpdater.cpp`
  `buildRSForSuperUse`. A value in an oversized RC (e.g. 384/448-bit bitcast held in sgpr_512) makes
  LiveIntervalCalc fabricate a subrange over never-defined padding lanes (values = undef @x inputs
  joined into a PHI-def). The reaching-VNI query returned that PHI-def → padding emitted as a live
  OrigVReg placeholder never patched → dangling use + illegal subreg. Fix: (a) restrict the query to
  lanes with a REAL establishing def (VNInfo `!isUnused() && !isPHIDef()`; `@x` in a LiveRange dump ==
  isUnused, confirmed LiveInterval.cpp:1001), routing padding to the undef NoSub piece; (b) gate the
  direct-subreg fast path on `TRI.getSubClassWithSubReg(RC, Idx)`, else decompose via
  getCoveringSubRegsForLaneMask (sgpr_512 has no single sub12_..._sub15 / sub14_sub15 index).
  Repro amdgcn.bitcast.{384,448}bit.ll (320bit still fails — DIFFERENT class, PHI-after-non-PHI).

- **CORPUS: CRASH 195 → 103** (`/tmp/corpus-postfix/{report.md,results.jsonl}`, 3060 tests, no new
  crash-class regressions). Remaining top classes: (30) Failed to find free physreg [cross-call
  coalescing]; (10) Operand incorrect register class; (10) Found PHI after non-PHI [amdgcn.bitcast.
  320/512/640/704/1024bit]; (7) Invalid Object Idx; (6) Register class not set [GISel]; (6) VOP const
  bus; (6) Remaining virtual register [GWS]; (5) Multiple vreg defs SSA; (4) v_div_scale; + singletons.

- **GUARD-TEST BACKLOG (the dev-rule: each fix needs a guarding LIT test).** 14 fixes since the first
  corpus run (2026-07-06) had shipped with NO test (only 23a3 touched an existing one). Committed 6
  guard tests (all in `llvm/test/CodeGen/AMDGPU/SSARA/`), each PROVEN by revert (revert the fix in the
  sandbox → documented crash; with fix → clean):
    * rebuildssa-bitcast-oversized-padding.ll (36154bd padding; committed w/ fix)
    * rebuildssa-wmma-early-clobber-tied-use.ll (75b82e; wmma f32 16x16x16 gfx1200; reading vreg w/o def)
    * rebuildssa-newdef-among-all-operands.ll (400c67; v_shuffle_v3f32_v2f32__3_0_u gfx900; NewDefMI assert)
    * ra-undef-self-tied-def.ll (030d4d; load_local_hi_v2i16_undeflo gfx900; Tied use must be colored)
    * rebuildssa-undef-phi-operand.ll (392cc; bitcast_v2f64_to_v8f16 tahiti; Found PHI with NoPHIs)
    * ra-color-by-operand-flag.ll (4cb21; ds_atomic_xchg_i32_ret_a_a gfx90a; non-undef vreg not colored)
  Test commits: 50bef5c (#2/#3/#5), 402d82a (#6/#14). NOTE #6's NoPHIs symptom == same assert family as
  the padding test but a DISTINCT fix/mechanism (undef PHI-lane sourcing vs padding lanes).

- **DEFERRED guard tests (with reasons):**
    * V_SWAP_B16 (effb63): needs a 16-bit PHI PERMUTATION CYCLE; no small .ll triggers a swap (bf16
      atomicrmw / mad-mix / f16 all clean even reverted, on true16 gfx1100/gfx1250) → hand-crafted MIR only.
    * RMW subreg re-def ordering (c8c11): no documented repro found; needs same-block RMW subreg chain.
    * loop-carried PHI self-ref (fad0): loop-live-out-copy-undef-subrange.ll AND existing
      rebuildssa-loop-i64-reduction.ll both stay CLEAN when reverted → their repro is elsewhere; not found.
    * partial reload lanes (90a2): reverting yields NOISY "Failed to find free physreg" (overlaps
      class-A) — no stable unique signature for a guard.
    * 867d/b293c/c100e: older reconstruction/coloring commits that DO NOT cleanly `git revert` (later
      commits rewrote the code) → cannot isolate a pre-fix state; likely partially covered by tests above.
    * dying-use early-clobber (60727): cleanly reverts but its class not yet pinned to a minimal repro.
  CallSites isAllocatable (316d) = perf-only, no behavior change → no functional test possible.

- **GUARD-TEST INFRA (reusable, still on disk):** isolated detached worktree
  `/work/atimofee/sandbox/github/ssara-guard` + minimal build `build/guard` (llc/FileCheck/llvm-extract
  only, no clang/lld; ~10G). Built path-independently by REUSING the warm ccache via
  `CCACHE_BASEDIR=/work/atimofee/sandbox/github CCACHE_NOHASHDIR=true` in LLVM_CCACHE_PARAMS (this ccache
  REJECTS CCACHE_HASHDIR=no/false; must use CCACHE_NOHASHDIR=true) — first build ~4.6min (mostly cache
  hits, +100k). Pinned fixed binaries at /tmp/ssara-pin (llc/FileCheck/llvm-extract at HEAD 36154bd) for
  verifying tests PASS without touching the user's tree/build. Scratch test authoring in /tmp/ssara-tests.
  Revert-proof loop: `cd ssara-guard && git reset --hard HEAD && git revert -n <commit> && ninja -C
  build/guard llc` (~2min incremental) then run repro → expect documented crash; restore with reset.
  Discovery trick: revert several fixes at once, run the corpus harness with `--llc ssara-guard/.../llc`,
  diff crash classes vs the 103 baseline → each new/expanded class + its first file = a candidate repro.

- **UNCOMMITTED (user's, to commit TOMORROW with a guard test): PHI-after-non-PHI spiller fix** in
  `AMDGPUSSARegisterSpiller.cpp::spillAtDefinition` (~line 1441). When the spilled value's def is a PHI,
  the store was inserted at `std::next(PHI)` — landing BETWEEN PHIs (verifier "Found PHI after non-PHI").
  Fix: `InsertAfter = DefMI->isPHI() ? DefMBB->getFirstNonPHI() : std::next(DefMI->getIterator())`.
  Diff saved (survives working-tree loss) at
  `ssa-spiller-docs/SSARA/08-Worklog/UNCOMMITTED_phi-after-nonphi-spiller-fix_2026-07-10.patch`.
  Target class: the (10) "Found PHI after non-PHI" — amdgcn.bitcast.{320,512,640,704,1024}bit.ll etc.

- NEXT: (1) user commits the PHI-after-non-PHI fix + a guard test tomorrow (candidate repro
  amdgcn.bitcast.320bit.ll, which currently sits in that class). (2) Optionally resume the deferred guard
  tests using the ssara-guard sandbox. (3) Corpus 103→lower: next tractable classes B/D/H/I; class A
  (free physreg) needs the coalescer. Sandbox + /tmp/ssara-pin + /tmp/corpus-postfix still on disk.
