# SSA Register Allocator

**SSA-based register allocation for AMDGPU Machine IR**

## Status

✅ **Implemented and wired** — coloring, SSA destruction, operand rewrite, physreg tracking. Enabled behind the hidden flag `-amdgpu-ssa-regalloc` (default OFF, legacy PM only): `GCNPassConfig::addRegAssignAndRewriteOptimized()` runs RebuildSSA → SimplifyUndefPHI → SSA Spiller → **SSA Register Allocator**.

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
- **Chordal/PEO-based**: greedy coloring is optimal on chordal graphs when processed in [[../03-Concepts/Perfect_Elimination_Order|Perfect Elimination Order (PEO)]]

## Why SSA Changes RegAlloc

SSA provides two key properties:
1. **Single definition** per value
2. **Dominance-shaped liveness**: all uses are dominated by the def

This implies the interference graph is **chordal** (or close enough), enabling efficient greedy coloring with PEO rather than general graph coloring.

## High-Level Workflow

`runOnMachineFunction` = `classifyVRegs()` → `color()` → `destroySSAAndRewrite()`.

### Skeleton

1. **Build analyses**:
   - Dominator tree (`MachineDominatorTree`)
   - LiveIntervals / SlotIndexes
   - MachineLoopInfo (for phi-affinity hint weighting)
   - Register class constraints (`SIRegisterInfo`, via `RegClassInfo`)

2. **`classifyVRegs()`**: collect the set of register widths present, coloring
   order width-descending.

3. **`color()`** — width-descending PEO:
   - For each width, walk blocks in dominator-tree pre-order.
   - Per block, `seedOccupiedAtBBEntry` marks physregs of colored live-ins;
     kills are freed before defs are colored (a def can reuse a dying source's
     physreg, except across an early-clobber def).
   - `pickFreePhysReg` scans `RegClassInfo::getOrder(RC)` for a register free at
     the def, avoiding wider overlapping assignments and any register clobbered
     by a call/instruction the value is live across (`CallSites`).
   - Phi-affinity hints (`collectPhiHints`, weighted by $2^{\text{loopdepth}}$)
     bias the color **choice** only; they never change legality.

4. **`destroySSAAndRewrite()`**: SSA destruction + operand rewrite (see below).

> The allocator does **not** spill: it assumes pressure is already within limits
> (the [[SSA_Spiller]] runs as a separate pass beforehand). If coloring cannot
> find a free physreg it asserts `Failed to find free physreg` rather than
> spilling on demand.

## Spilling Model

Spilling is handled by a **separate pre-pass**, the [[SSA_Spiller]], which runs
before this allocator and reduces register pressure to within the allocatable
file size. The allocator itself performs **no** spilling — by the time it runs,
coloring is expected to always find a free register. The spiller's model
(store-at-definition, on-demand reload placement, SSA repair via
[[MachineLaneSSAUpdater]]) is documented under [[SSA_Spiller]].

## AMDGPU-Specific Concerns

| Concern | Handling |
|---------|----------|
| VGPR vs SGPR vs AGPR | Processed together per width pass (their reg units don't overlap); the chosen physreg's file drives the high-water mark |
| Lane masks / subregisters | Allocate at (VReg, LaneMask) granularity |
| Register tuples | N contiguous registers or fixed tuple shapes |
| Implicit uses/defs | EXEC, VCC, SCC, M0 affect pressure |

## Data Structures

- **Active set**: lane-aware set of currently-live assigned values
- **Assignment map**: vreg (or vreg+mask) → physreg/tuple
- **Free lists**: per reg class, track available registers
- **Next-use interface**: query "distance" for candidate selection

## Theory

- [[../03-Concepts/Chordal_Graphs|Chordal Graphs]]
- [[../03-Concepts/Perfect_Elimination_Order|Perfect Elimination Order (PEO)]]

## Papers

- *Register Allocation for Programs in SSA Form* (`06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`)
- `06-Research/Papers/ssara.pdf`

## Implemented Details

- **`classifyVRegs()`**: populates `ColoringOrder` (width-descending `std::set`).
- **`color()`**: function-wide width-descending, MDT pre-order per width;
  `seedOccupiedAtBBEntry` seeds physreg live-ins; kills-before-defs ordering
  (deferred past early-clobber defs); `pickFreePhysReg` via
  `RegClassInfo::getOrder(RC)` with call/clobber avoidance (`CallSites`) and
  phi-affinity `Hints` from `collectPhiHints`. Updates `MaxVGPRIdx` /
  `MaxSGPRIdx` / `MaxAGPRIdx` high-water marks. Tied defs inherit the tied use's
  color.
- **`destroySSAAndRewrite()`**: `lowerPHIs` → `rewriteOperands` →
  `eliminateRegSequences` → `addPhysRegLiveIns` → `finalizeProperties`.
  - `resolvePermutation` (parallel-copy cycle breaking: scratch register /
    `emitSwap` via `V_SWAP_B32` / `V_SWAP_B16` / SGPR `S_XOR` triplet / AGPR
    scratch fallback) is called from both `lowerPHIs` and `eliminateRegSequences`.
  - `finalizeProperties` runs `leaveSSA` + `clearVirtRegs` and sets `NoPHIs`,
    `NoVRegs`, `TiedOpsRewritten` (mirroring `VirtRegRewriter`);
    `TracksLiveness` is deliberately preserved.
- **PHI-copy metrics**: `lowerPHIs` counts copy-vs-fixed-point PHI operands
  (`-debug-only=amdgpu-phi-metric`) — pure instrumentation, no MIR change.

## Known Gap

- **CF-pseudo functions**: `destroySSAAndRewrite` is **skipped entirely** when the
  function still contains SI control-flow pseudos (`SI_IF` / `SI_ELSE` /
  `SI_IF_BREAK` / `SI_LOOP` / `SI_END_CF`), via `hasCFPseudos`. Coloring still
  runs, but PHIs and virtual registers remain in such functions.

## Pending

- Full PHI coalescer (paper §4.3). Only partial pieces exist today:
  `AMDGPUSimplifyUndefPHI` (a wired standalone pass), `collectPhiHints`
  (affinity hints), and the PHI-copy metrics — a general coalescer is **not**
  implemented.
- Reg-unit vs pressure-unit mismatch (VGPR_32 has 2 reg units, 1 pressure unit).
