# Backlog — SSARA / SSA Spiller / Pipeline

Living list of unfinished work, test debt, and in-code TODOs.  
Sources: `NOTES.md`, `SHARED_CONTEXT.md`, `AGENTS.md`, `TODO.md`, `AMDGPUSSARegisterSpiller.cpp` comments, worklog `issues/`.

---

## HIGH PRIORITY

| Item | Location | Notes |
|------|----------|--------|
| **Spiller and RA size the RP budget differently — reconcile** | `AMDGPUSSARegisterSpiller.cpp` `runOnMachineFunction` (`VGPRLimit = ST.getMaxNumVGPRs(MF)`) vs `AMDGPUSSARegisterAllocator` `RegClassInfo.getOrder(RC)` | The spiller budgets in physical 32-bit reg-units from `getMaxNumVGPRs/getMaxNumSGPRs` (gfx90a example: 128, −10% → 116). The RA colors into the **allocatable count of the exact class** (`getNumAllocatableRegs == getOrder().size()`, gfx90a example: **64** for `VGPR_32`; the other 64 are AGPRs). So on gfx90a the VGPR pass targets ~2× the registers the allocator actually has → under-spills. **Open question: which is correct, and can the two be reconciled** (single source of truth for "available 32-bit registers of a class")? Likely the spiller should query `RegClassInfo.getNumAllocatableRegs(VGPR_32/SGPR_32)` like the RA. Watch: the spiller's 10% margin may double-count reserved regs once the base is already reserved-aware; and resolvePermutation scratch needs a few regs of headroom above the high-water mark. Discovered 2026-07-10 triaging the corpus "Failed to find free physreg" crash class. |
| **Call-clobber-aware coloring in the RA (cross-call values → callee-saved)** | `AMDGPUSSARegisterAllocator::pickFreePhysReg` | `"Failed to find free physreg"` corpus class (29 tests): greedy compiles these WITHOUT spilling (`ScratchSize:0`), so it is a **coloring** deficiency, not a spiller one. A value live across a call may only occupy a callee-saved (regmask-preserved) reg; the current greedy-smallest-free assignment lets non-cross-call values grab callee-saved regs first, starving cross-call (esp. wide *aligned*, e.g. `vreg_128_align2`) values. **Constraint (Hack): coloring an SSA/chordal graph is only guaranteed to succeed in DOMINANCE ORDER — do NOT reorder to color cross-call values first (unsound).** The fix must stay in dominance order and only bias the *color choice*: non-cross-call values prefer caller-saved regs, leaving callee-saved for cross-call values. This is sound (still picks a free color per Hack) and sufficient **iff** `#(values live across the call) ≤ #callee-saved` at every point — which the spiller's call-clobber charge (applied 2026-07-10) guarantees by spilling the excess (only when even greedy would). Discovered 2026-07-10 (`undef-handling-crash-in-ra.ll`). |

---

## Blocked / failing tests (must fix code or clarify spec)

| Item | Location | Notes |
|------|----------|--------|
| Loop: no spill candidates → `validateFinalRP` | `spill-loop-skip-def-inside.mir` | Red since introduction (`3bfb42ab59ef`). Loop filter empties candidate set; needs fallback — see `getVMPsToSpill` TODO ~632. **Marked `XFAIL`** in tree until fixed. |
| Loop: reload fallback | `spill-loop-reload-inside-fallback.mir` | Same as above. **Marked `XFAIL`** in tree until fixed. |
| ~~Group A phys live-in CHECK drift~~ | `spill-linear-dominated.mir`, `spill-dominated-branches.mir`, `spill-multi-predecessor-join.mir` | **Addressed:** phys `liveins` removed (IMPLICIT_DEF + COPY); FileCheck hand-maintained for virtual spill marker + `SI_SPILL_V128_*` where emitted. |

## SSA Spiller — algorithm / implementation

| Item | Source |
|------|--------|
| **Loop filter fallback**: when `ValidCandidates.empty()` after loop filter, pick strategy (invalid candidate + loop-exit sinking, etc.) | `AMDGPUSSARegisterSpiller.cpp` ~632, `NOTES.md` 2026-06-10 |
| ~~Partial subreg spill~~ | **Fixed 2026-06-11.** `getVMPsToSpill` now uses `getRegSplitParts` to take only the needed 32-bit parts; `SIInstrInfo::storeRegToStackSlot` now honours `SubRegIdx` in the SGPR path. Single VGPR lane used for partial spills. See NOTES 2026-06-11. |
| **CFG cache invalidation** if CFG mutates during spill | cpp ~245 `FIXME` |
| **Correct debug message** for `spillAndReload` when RP > limit | cpp ~781 |
| **Profitability**: early return when RP > Limit | cpp ~872 |
| **Reload API**: emit reload into a specific register when required | cpp ~1542 |
| ~~`lowerSGPRSpills()` crash~~ | **Resolved 2026-06-11.** Replaced with `countSGPRSpillVGPRs()` (accounting only). Materialization delegated to `SILowerSGPRSpills`. Pipeline verified end-to-end with `-run-pass` chain. See NOTES 2026-06-11. |
| **`LivePhysRP` / reg-unit vs pressure-unit** | `AGENTS.md`: VGPR_32 two reg units vs one pressure unit — verify no underflow after physreg path changes. |
| **Tied-operand RP** in spiller | `SHARED_CONTEXT.md` Not Started |
| **`handleReachableUse` / `splitBlockBeforeReload`** | Currently commented at call site; bodies removed in `4794a5f9910b`. Restore + cost model if non-dominated uses need split-before-reload | `issues/SSA_Spiller/Unused_code.md`, `NOTES.md` |

## SSA Register Allocator

| Item | Source |
|------|--------|
| **PHI coalescer** (paper §4.3) — fewer copies | `NOTES.md` Pending, `SHARED_CONTEXT.md` |
| **Physreg tracking edge cases** | Reserved/filtered; wide partial kills — keep aligned with spiller pressure model |

## Pipeline / passes

| Item | Source |
|------|--------|
| **Pipeline wiring** — `-amdgpu-ssa-regalloc` flag in `addRegAssignAndRewriteOptimized()`: `RebuildSSA → SSA Spiller → SSA RA → SILowerSGPRSpills → (rest)`. `SILowerSGPRSpills` must come immediately after SSA RA (stock ordering). No allocator restructuring needed. | `NOTES.md` 2026-06-08, 2026-06-11 |
| **VGPR spill lowering proof** — `SIRegisterInfo::eliminateFrameIndex` handles `SI_SPILL_V*_SAVE/RESTORE` via standard PEI. Requires: physical regs (SSA RA delivers), `ScratchRSrcReg` reserved (SIFrameLowering prologue), frame indices present. **NOT yet empirically verified** — the E2E smoke tests are the proof. | `SIRegisterInfo.cpp:2374` |
| **End-to-end `.ll` smoke** — `basic-loop.ll`, `spill-cfg-position.ll` (with `amdgpu-num-vgpr` to force VGPR spill), `rewrite-vgpr-mfma-to-agpr-phi.ll` with pipeline flag. These also prove VGPR lowering works. | `NOTES.md` |
| **`MF.verify()` policy** for RebuildSSA (debug-only vs always) | `NOTES.md` (currently debug-guarded) |

## Documentation / process

| Item | Source |
|------|--------|
| Revise / systematize **SSA Spiller test approach** | `08-Worklog/TODO.md` |
| Review **SSA_SPILLER_TEST_PATTERNS** | `08-Worklog/TODO.md` |
| Update **`SHARED_CONTEXT.md`** “Last updated” and Implemented/Not Started vs current tree | Stale 2026-06-05 |
| **MachineLaneSSAUpdater** unit tests vs “avoid spilling vregs from SSA repair” design | `TODO.md` wiki links |

## Cross-component (other worktrees)

| Item | Source |
|------|--------|
| Next Use Analysis: memory / compile-time follow-ups | Stashes / `next-use-analysis` branch (out of scope here; track in NUA backlog) |

---

## How to use this file

- Promote items to `NOTES.md` when work starts (dated section).
- Close rows when tests pass and docs updated.
- Prefer one MIR + one bugfix at a time per project rules.
