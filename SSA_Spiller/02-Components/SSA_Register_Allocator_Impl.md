# SSA Register Allocator

**SSA-based register allocation for AMDGPU Machine IR**

## Status

📋 **Draft** — documentation-only, not yet implemented.

---

## Input MIR

**SSA-form Machine IR**
- Register pressure within limits (post-spilling)
- Virtual registers only
- Valid LiveIntervals

## Output MIR

**SSA-form Machine IR with physical registers**
- All virtual registers assigned to physical registers
- SSA form still preserved
- PHI nodes use physical registers
- Ready for SSA destruction

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

### Skeleton

1. **Build analyses**:
   - Dominator tree (`MachineDomTree`)
   - Per-instruction next-use info ([[Next_Use_Analysis]])
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

Reuses the [[SSA_Spiller]] model:
- Store at definition (correctness under EXEC)
- Virtual spill point (where RP relief is intended)
- Reload placement + SSA repair via [[MachineLaneSSAUpdater]]

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

- [[../03-Concepts/Chordal_Graphs|Chordal Graphs]]
- [[../03-Concepts/Perfect_Elimination_Order|Perfect Elimination Order (PEO)]]

## Papers

- *Register Allocation for Programs in SSA Form* (`06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`)
- `06-Research/Papers/ssara.pdf`

## Open Questions

- Exact PEO / traversal order in practice
- Active-set retirement rule at dom-tree boundaries
- Next-use query semantics across dom-tree traversal
- LiveIntervals vs SSA-native liveness representation
