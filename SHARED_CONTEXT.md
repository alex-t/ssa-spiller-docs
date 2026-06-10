# Shared Context — SSA RA Project

Cross-worktree knowledge base. Updated after significant sessions.
Last updated: 2026-06-05

## Worktree Layout

| Worktree | Branch | Purpose |
|----------|--------|---------|
| `ssara` | ssara | SSA Register Allocator (main development) |
| `early-ssa-spiller` | early-ssa-spiller | SSA Spiller (synced with ssara) |
| `next-use-analysis` | next-use-analysis | Next Use Analysis pass |
| `mssa-updater` | mssa-updater | MachineLaneSSAUpdater |
| `ssa-rebuilder` | ssa-rebuilder | AMDGPURebuildSSA refactoring |

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
- `countSGPRSpillVGPRs()` (2026-06-11): pure frame-size accounting replaces
  `lowerSGPRSpills()`. `VGPRLimit -= countSGPRSpillVGPRs(MF)` between Pass 1
  and Pass 2. No physreg side effects in the spiller.
- 56 RA+Spiller tests passing, 3 XFAIL (2 loop-filter, 1 balanced-use-before)
- End-to-end RA pipeline fully functional (coloring → SSA destruction → operand rewrite)
- RebuildSSA pass ported and registered (9 fixes applied)

### Pipeline Integration (WIP, 2026-06-08)
- AMDGPURebuildSSA ported from PR #156049 into ssara worktree (9 bug fixes applied)
- Pipeline plan: `-amdgpu-ssa-regalloc` flag in `addRegAssignAndRewriteOptimized()`
  replaces greedy path with RebuildSSA → SSA Spiller → SSA RA
- Pre-RA sequence unchanged (PHIElim + TwoAddress + RegCoalescer + RenameIndependentSubregs)
- RebuildSSA is temporary bridge: converts post-PHIElim non-SSA MIR back to SSA
- Testing: end-to-end `.ll` smoke tests (basic-loop, spill-cfg-position, mfma-phi)
- Pipeline hookup and e2e testing: pending

### Removed
- LR splitter removed 2026-05-26. Width-descending coloring already reuses freed slots.
- PHI false-interference fix loop removed 2026-06-05. PHI sources are live only
  to predecessor boundaries in LLVM's LiveIntervals — no false interference exists.

### Not Started
- Spill lowering: `countSGPRSpillVGPRs()` accounting is done (2026-06-11); physical
  materialization delegated to existing `SILowerSGPRSpills` pass (runs after SSA RA
  when pipeline is wired). `SILowerSGPRSpills` uses `getAnalysisIfAvailable` for LIS —
  works without LIS after `leaveSSA`/`invalidateLiveness`.
- Pipeline integration: wire `-amdgpu-ssa-regalloc` in `addRegAssignAndRewriteOptimized()`:
  `RebuildSSA → SSA Spiller → SSA RA → SILowerSGPRSpills → (rest)`. No allocator
  restructuring needed; SSA RA colors bottom-up; top-of-file VGPRs naturally free for
  `SILowerSGPRSpills`. End-to-end verified with `-run-pass` chain (2026-06-11).
- Phi coalescer (paper section 4.3)
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

See [SSA RA Coloring Design](SSARA/04-Design/SSA_RA_Coloring.md) for coloring documentation.
See [SSA RA Test Patterns](SSARA/05-Testing/SSA_RA/SSA_RA_TEST_PATTERNS.md) for test documentation.

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

## Tools
- md2pdf.py: ssa-spiller-docs/SSARA/tools/md2pdf.py
- Design doc: ssa-spiller-docs/SSARA/04-Design/SSA_RA_Coloring.md

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

## User Preferences
- No source changes without APPROVED: line
- User commits manually (no AI commits, no trailers)
- Patches shown as unified diffs
- Never update tests to match output — tests define expected behavior
- Always verify user claims independently
- Minimal code, no over-engineering
