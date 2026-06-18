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

## Pending
- **[P1] Compile-time: interval tree for wider interference query**
- **Commit Phase-0 test batch** (10 SSARA .ll: T1a/b, T2a/b/c, T3a/b/c, T4a/b).
- **Phase 1**: RebuildSSA → MachineLaneSSAUpdater. **Phase 2**: function-wide RA coloring.
- **E2E LIT tests** — 4-tier plan: T1 (CFG) 2/4 formal done; T2 (spill) blocked on margin
  design; T3 (widths), T4 (target) not started.
- **Refactor RebuildSSA to `MachineLaneSSAUpdater`** — def-first renaming, removes the
  `reachedByThisVNI` heuristic entirely (see FUTURE_IMPROVEMENTS.md).
- **PHI coalescer** (paper §4.3) — reduce copies by recoloring PHI operands.
- **Spiller tied-operand RP** fix.
- **Loop-filter fallback** — `getVMPsToSpill` TODO ~632.
