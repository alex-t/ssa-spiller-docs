- Check if [[SSA_Spiller/02-Components/MachineLaneSSAUpdater|MachineLaneSSAUpdater]] unit tests is broken because of the design changes [[Decisions#Static Next Use Analysis limitation|Avoid spilling of the VRegs created by SSA repair]]
- Revise and systemize [[SSA_Spiller Test Approach]]
- Review [[SSA_Spiller/05-Testing/SSA_Spiller/SSA_SPILLER_TEST_PATTERNS|SSA_SPILLER_TEST_PATTERNS]]
- **[BUG][SSA-RA] Unaligned wide SGPR REG_SEQUENCE slice → `$noreg` COPY.** `eliminateRegSequences`/`rewriteOperands` in `AMDGPUSSARegisterAllocator.cpp` (lines 595, 511) assume `TRI->getSubReg(Reg, SubIdx)` always yields a physical sub-register. For alignment-constrained AMDGPU SGPR tuples, unaligned wide sub-tuple indices (`sub1_sub2`, `sub1_sub2_sub3`) return `NoRegister`, so lowering `%dst:sgpr_128 = REG_SEQUENCE ..., %src, sub1_sub2_sub3` emits `$noreg = COPY ...` → post-RA `MachineCopyPropagation` assert. Fix: when `getSubReg` returns 0, decompose the slice into aligned addressable sub-registers (down to sub0-granular copies). Independent of MachineLaneSSAUpdater. See NOTES 2026-07-02.

  Reproducer (self-contained, crashes today; extracted from `uniform_fadd_f16` in `atomic_optimizations_global_pointer.ll`):

  ```llvm
  ; RUN: llc -mtriple=amdgcn -mcpu=gfx900 -mattr=-flat-for-global \
  ; RUN:   -amdgpu-atomic-optimizer-strategy=Iterative -amdgpu-ssa-regalloc \
  ; RUN:   -verify-machineinstrs < %s

  define amdgpu_kernel void @uniform_fadd_f16(ptr addrspace(1) %result, ptr addrspace(1) %uniform.ptr, half %val) {
    %rmw = atomicrmw fadd ptr addrspace(1) %uniform.ptr, half %val monotonic, align 2
    store half %rmw, ptr addrspace(1) %result
    ret void
  }
  ```

  Current failure: `MachineCopyPropagation.cpp:889 Assertion 'RegDef.isPhysical() && RegSrc.isPhysical()'` (a `$noreg = COPY $sgpr4_sgpr5_sgpr6` reaches post-RA). When fixed, promote this to a lit regression test under `llvm/test/CodeGen/AMDGPU/SSARA/` (or `MachineLaneSSAUpdater/`).
- **[BUG][UPSTREAM][FIX-APPLIED] `SplitCriticalEdge` subrange VNInfo.** Root cause of the `add_i64_uniform`/`add_i64_constant` crash is a genuine upstream bug in core `MachineBasicBlock::SplitCriticalEdge`: the PHI-source `LiveIntervals` update loop (MachineBasicBlock.cpp:1351) extends a PHI-source reg's **subranges** with the **parent** range's `VNInfo` instead of `SR.getVNInfoAt(PrevIndex)` (the sibling live-through loop does it right). When the reg is live-through the freshly split block, its subrange already covers `[Start,End)` → foreign-valno overlap → `LiveInterval.cpp` "Cannot overlap two segments with differing ValID's". Reproducible on clean upstream with stock passes (`-run-pass liveintervals,phi-node-elimination`). Our `lowerPHIs` also over-splits forward-triangle critical edges (separate quality item: only split when `isLiveOutPastPHIs && !isLiveIn`). **Fix applied** to trunk branch `fix-splitcriticaledge-subrange-vninfo`; crash gone; `check-llvm` running. Full report + repro: `bugs/SSARA/BUG-splitcriticaledge-subrange-vninfo.md`, `bugs/SSARA/repro.mir`. Next: consult PR #69429 author, then open PR with `repro.mir` as regression test; port fix to ssara worktree.

  Reproducer (self-contained, crashes today):

  ```llvm
  ; RUN: llc -mtriple=amdgcn -mcpu=gfx900 -mattr=-flat-for-global \
  ; RUN:   -amdgpu-atomic-optimizer-strategy=Iterative -amdgpu-ssa-regalloc \
  ; RUN:   -verify-machineinstrs < %s

  define amdgpu_kernel void @add_i64_uniform(ptr addrspace(1) %out, ptr addrspace(1) %inout, i64 %additive) {
  entry:
    %old = atomicrmw add ptr addrspace(1) %inout, i64 %additive syncscope("agent") acq_rel, align 8
    store i64 %old, ptr addrspace(1) %out, align 4
    ret void
  }
  ```

- **[BUG][SSA-RA] SGPR permutation cycle under register pressure has no correct lowering.** `resolvePermutation`/`emitSwap` (AMDGPUSSARegisterAllocator.cpp): `emitSwap` only emits VGPR ops (`V_SWAP_B32`/`V_XOR_B32_e64`) — there is no scalar swap on AMDGPU. SGPR cycles rely entirely on the scratch tier; if an SGPR cycle fails the scratch occupancy condition (SGPR pressure over limit), it falls into `emitSwap` and emits VGPR ops on SGPRs → illegal machine code. Fix: add an `S_XOR_B32` scalar triplet fallback for SGPR cycles, **gated on SCC being dead** at the insertion point (S_XOR writes SCC; else save/restore SCC or keep requiring a scratch). Test still needed: SGPR cycle under pressure (currently miscompiles). (VGPR no-swap occupancy-free scratch path is now covered by `SSARA/destruct-swap-noswap-scratch.mir`.) See code TODO in resolvePermutation tier-2/3. Related: tier order now prefers V_SWAP for VGPR cycles (gated `IsVGPR && hasSwap`).
- **[TEST] Keep MachineLaneSSAUpdater unit tests up to date.** `MachineLaneSSAUpdaterTest.cpp` + `MachineLaneSSAUpdaterSpillReloadTest.cpp` fail to compile — stale 2-arg `repairSSAForNewDef(MI, Reg)` vs current 3-arg `repairSSAForNewDef(MI, Reg, SmallVectorImpl<MachineOperand*>&)` (8 call sites).
- **[BUG][SSA-RA] Memory-spill floor does not shorten a long live range; `floorViable` accepts it anyway.** `recoverUncolorable`'s Floor case (AMDGPUSSARegisterAllocator.cpp ~3617) spills a value only if `floorViable` says a reload fits, yet for a width-1 SGPR that is live-out across many blocks the reload placed at block end reconstitutes the SAME long range under a new name. Evidence (`schedule-amdgpu-trackers.ll [tonga]`, `excess_soft_clause_reg_pressure`): spilling `%13998 [51744r,88492B)` yields `%14001 [51756r,88512B)`. A second, dependent defect: the worklist fixpoint sets `Progress` only when the item itself acquires a color, so a pass that only spilled records no progress, breaks, and reports values queued during that pass as infeasible without ever attempting them — that is why `%1248` has no `FALLBACK` line. Fixing only the progress metric (`Progress |= recoverUncolorable(Failed)`) turns the 7 s abort into an unbounded cascade of 4257 spills; TRIED AND REVERTED 2026-08-21. Fix direction: make `floorViable` exact for live-out-across-blocks values, and/or reload per use instead of at block end. See HANDOFF-2026-08-21 §10.
- **[BUG][UPSTREAM] Machine scheduler reorders two partial defs without moving the `undef` flag.** The register coalescer flattens a REG_SEQUENCE into partial defs with `undef` on the first in program order; the scheduler swaps them and leaves the flag on the now-second one, so the first def reads lanes with no reaching def. Any from-scratch live-interval recomputation aborts in `LiveRangeCalc::findReachingDefs` ("Use not jointly dominated by defs"); the machine verifier accepts the MIR and Greedy never recomputes, so only `MachineLaneSSAUpdater::performSSARepair` trips. Repro: `shufflevector-physreg-copy.ll` on gfx900/gfx90a/gfx942. Fix options: normalize `undef` across a partial-def chain before recomputing, or fix the scheduler. See HANDOFF-2026-08-21 §9.
- **[INFRA] Harness overrides a test's own `-verify-machineinstrs=0`.** `scripts/ssara_corpus_harness.py` appends `-verify-machineinstrs` after the test's flags, silently reversing the test's intent. Fixed only in the throwaway `/tmp/harness_rescue.py` (skip appending when any arg already starts with the flag prefix). Port it.
- **[TASK] Drop the Greedy tails when SSARA mode is active.** Measured 2026-08-21: with `-amdgpu-prealloc-sgpr-spill-vgprs`, 7363 of 7364 compiling corpus records have ZERO vregs surviving past `si-pre-allocate-wwm-regs`. Check the one exception (`sgpr-regalloc-flags.ll`, function `control_flow`, `%0` — it does not force another allocator), then propose the pipeline change in `AMDGPUTargetMachine.cpp`.
- **[DIAG] Replace `llvm_unreachable("physreg not found for WWM expression")`** in `SIPreAllocateWWMRegs::processDef` with a real diagnostic, modelled on "cannot find enough VGPRs for wwm-regalloc" in `SILowerSGPRSpills.cpp`.
