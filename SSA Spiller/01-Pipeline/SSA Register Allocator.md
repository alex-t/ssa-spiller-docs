# SSA Register Allocator

SSA-based register allocation stage for AMDGPU Machine IR.

This page is a **pipeline-level** description. Implementation mapping lives in:
[[02-Components/SSA Register Allocator Impl]].

## Strategy
- Graph-free register assignment (avoid explicit interference graph construction)
- Dominator-based allocation (operate over the dominator tree, not program order)
- Chordal/PEO-based reasoning: greedy coloring is optimal on chordal graphs when processed in a
  [[03-Concepts/Perfect Elimination Order (PEO)|Perfect Elimination Order (PEO)]]

## Theory
- [[03-Concepts/Chordal Graphs]]
- [[03-Concepts/Perfect Elimination Order (PEO)]]
- Papers in `06-Research/Papers/`:
  - *Register Allocation for Programs in SSA Form* (`register-allocation-for-programs-in-ssa-form.pdf`)
  - `ssara.pdf`

## Planned
- **Traversal**: dominator tree traversal (initially DFS preorder; alternatives: BFS / RPO variants)
- **Ordering**:
  - block ordering: dominator-tree driven
  - local ordering: per-block MI order for “next use” queries
- **SSA-driven allocation**:
  - each vreg has a single def; liveness is dominated by its def
  - “join” effects are explicit (PHIs / phi-like operands in MachineIR SSA)
- **Spill/evict decisions**:
  - integrate with [[02-Components/Next Use Analysis]] to approximate Belady/MIN decisions
  - reuse the “store-at-definition + virtual spill point + SSA repair” model from the SSA spiller

## Status
Draft (documentation-only).

## Inputs / outputs
- **Input**: MachineFunction in SSA form (or repaired SSA), with lane/subreg semantics preserved.
- **Output**: physical register assignment (VGPR/SGPR) + stack spills where needed, while keeping SSA
  consistent until the final SSA destruction stage.

## Why SSA changes regalloc
SSA gives two properties that are useful for regalloc:
- **Single definition** per value.
- **Dominance-shaped liveness**: all uses are dominated by the def; the live range is a dominance
  subtree with “holes” possible only via masks/subregisters and target-specific constraints.

This structure implies the (value) interference graph is often **chordal** (or close enough to
exploit chordal algorithms), enabling efficient greedy coloring with a PEO rather than general graph
coloring.

## High-level workflow (targeted to AMDGPU)
At a high level, the allocator operates like a dominator-tree “linear scan”, with explicit handling
for:
- **Lane masks / subregisters** (AMDGPU heavy)
- **Register classes and tuples**
- **Fixed / reserved registers**
- **Spilling while remaining in SSA**

### Skeleton
1. Build/obtain analyses:
   - Dominator tree (MachineDomTree)
   - Per-instruction next-use info (via [[02-Components/Next Use Analysis]])
   - Register class constraints (TargetRegisterInfo / SIRegisterInfo)
2. Traverse the dominator tree:
   - maintain an **active set** of currently-live SSA values (possibly lane-sliced)
   - allocate a physical register for each new def when it becomes live
   - retire/free values when they are proven dead along the traversal
3. When no register is available:
   - choose an eviction/spill candidate using next-use (Belady-like) heuristics
   - materialize spill/reload using SSA-aware machinery (see below)
4. Continue until all defs are assigned (and necessary spills inserted).

## Spilling model (reuse from SSA spiller)
We explicitly align with your existing AMDGPU SSA spill architecture:
- **Store at definition** (correctness under EXEC)
- **Virtual spill point** (where RP relief is intended)
- **Reload placement + SSA repair** via MachineLaneSSAUpdater

See:
- [[01-Pipeline/Early SSA Spiller]]
- [[02-Components/SSA Spiller]]
- `04-Design/Architecture.md` (“Separate where value stored from when register freed”)

### Key difference vs “pre-regalloc spilling”
In SSA regalloc, spilling is no longer a separate pre-pass; it becomes an **on-demand action**
triggered by register unavailability during allocation. The *mechanism* can still be the same:
store-at-def + virtual-kill + SSA repair.

## AMDGPU-specific constraints to document/encode
- **VGPR vs SGPR allocation** and class transitions.
- **Lane masks / subregister live parts**:
  - allocate/spill at (VReg, LaneMask) granularity where profitable/correct.
- **Tuples and multi-register values**:
  - values that require N contiguous registers or fixed tuple shapes.
- **Implicit uses/defs** that affect pressure (e.g. EXEC, VCC, SCC, M0).
- **Kill semantics**: avoid “synthetic kills” that break SSA repair; prefer virtual kill points.

## Open questions / TODOs (doc-tracked)
- Define the exact **PEO / traversal order** used in practice:
  - pure chordal-theory PEO vs pragmatic dom-tree scan order
- Specify the **active-set retirement rule**:
  - how we prove a value is dead at a dom-tree boundary (especially with PHIs and partial lanes)
- Define how **next-use** is queried across dom-tree traversal (not a simple linear instruction order).
- Decide whether to:
  - keep using LiveIntervals as a backing structure, or
  - switch to an SSA-native liveness representation (dom-subtree intervals + lane masks).

## Links
- Implementation mapping: [[02-Components/SSA Register Allocator Impl]]
- Concepts:
  - [[03-Concepts/Chordal Graphs]]
  - [[03-Concepts/Perfect Elimination Order (PEO)]]
