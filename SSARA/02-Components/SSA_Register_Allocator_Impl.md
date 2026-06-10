# SSA Register Allocator

**SSA-based register allocation for AMDGPU Machine IR**

## Status

✅ **Implemented** — coloring, SSA destruction, operand rewrite, physreg tracking. Pipeline end-to-end verified (2026-06-11). Wiring into `addRegAssignAndRewriteOptimized()` pending.

---

## Input MIR

**SSA-form Machine IR**
- Register pressure within limits (post-spilling)
- Virtual registers only
- Valid LiveIntervals

## Output MIR

**Non-SSA Machine IR with physical registers**
- All virtual registers assigned to physical registers
- SSA destroyed: PHIs resolved to COPYs, operands rewritten
- SGPR spill pseudos (`SI_SPILL_S*_SAVE/RESTORE`) still present — lowered by `SILowerSGPRSpills` in the next pipeline stage

---

## Strategy

- **Graph-free allocation**: avoid explicit interference graph construction
- **Dominator-based**: operate over the dominator tree, not program order
- **Chordal/PEO-based**: greedy coloring is optimal on chordal graphs when processed in `Perfect Elimination Order (PEO)`

## Why SSA Changes RegAlloc

SSA provides two key properties:
1. **Single definition** per value
2. **Dominance-shaped liveness**: all uses are dominated by the def

This implies the interference graph is **chordal** (or close enough), enabling efficient greedy coloring with PEO rather than general graph coloring.

## High-Level Workflow

### Skeleton

1. **Build analyses**:
   - Dominator tree (`MachineDomTree`)
   - Per-instruction next-use info ([Next_Use_Analysis](Next_Use_Analysis.md))
   - Register class constraints (`SIRegisterInfo`)

2. **Traverse dominator tree**:
   - Maintain active set of currently-live SSA values (lane-aware)
   - Allocate physical register for each new def when it becomes live
   - Retire/free values when proven dead along traversal

3. **When no register available**:
   - Choose eviction/spill candidate using next-use (Belady-like) heuristics
   - Materialize spill/reload using SSA-aware machinery

4. **Continue** until all defs are assigned.

## Spilling Model

Reuses the [SSA_Spiller](SSA_Spiller.md) model:
- Store at definition (correctness under EXEC)
- Virtual spill point (where RP relief is intended)
- Reload placement + SSA repair via [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md)

**Key difference**: Spilling is no longer a separate pre-pass; it becomes an on-demand action triggered by register unavailability during allocation.

## AMDGPU-Specific Concerns

| Concern | Handling |
|---------|----------|
| VGPR vs SGPR | Separate allocation passes |
| Lane masks / subregisters | Allocate at (VReg, LaneMask) granularity |
| Register tuples | N contiguous registers or fixed tuple shapes |
| Implicit uses/defs | EXEC, VCC, SCC, M0 affect pressure |

## Data Structures

- **Active set**: lane-aware set of currently-live assigned values
- **Assignment map**: vreg (or vreg+mask) → physreg/tuple
- **Free lists**: per reg class, track available registers
- **Next-use interface**: query "distance" for candidate selection

## Theory

- [Chordal Graphs](../03-Concepts/Chordal_Graphs.md)
- `Perfect Elimination Order (PEO)`

## Papers

- *Register Allocation for Programs in SSA Form* (`06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`)
- `06-Research/Papers/ssara.pdf`

## Implemented Details (2026-06-11)

- **`classifyVRegs()`**: populates `ColoringOrder` (width-descending `std::set`).
- **`colorByWidth(Width)`**: MDT pre-order; `seedOccupiedAtBBEntry` seeds physreg live-ins; kills-before-defs ordering; `pickFreePhysReg` via `RegClassInfo::getOrder(RC)`. Updates `MaxVGPRIdx` / `MaxSGPRIdx` high-water marks.
- **`destroySSAAndRewrite()`**: `lowerPHIs` → `resolvePermutation` (three-tier cycle-breaking: scratch / V_SWAP_B32 / XOR) → `rewriteOperands` → `leaveSSA` → `invalidateLiveness`.
- **Tests**: 25 passing (12 coloring + 9 destruction + 2 physreg + 2 wide-swap). No open failures in SSARA/ suite.

## Pending

- Pipeline wiring: `-amdgpu-ssa-regalloc` flag in `addRegAssignAndRewriteOptimized()`, ordering: SSA Spiller → SSA RA → `SILowerSGPRSpills`.
- PHI coalescer (paper §4.3).
- Reg-unit vs pressure-unit mismatch fix (VGPR_32 has 2 reg units, 1 pressure unit).
