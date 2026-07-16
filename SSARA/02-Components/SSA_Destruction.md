# SSA Destruction

**Final lowering of SSA to non-SSA Machine IR**

## Status

✅ **Implemented** — performed inside the [SSA Register Allocator](SSA_Register_Allocator_Impl.md) as `destroySSAAndRewrite` (`lowerPHIs` → `rewriteOperands` → `eliminateRegSequences` → `addPhysRegLiveIns` → `finalizeProperties`). PHIs are lowered to predecessor-edge copies with parallel-copy cycle breaking (`resolvePermutation`), critical edges split on demand.

> **Known gap**: destruction is **skipped** for functions that still contain SI control-flow pseudos (`SI_IF`/`SI_ELSE`/`SI_IF_BREAK`/`SI_LOOP`/`SI_END_CF`) — see `hasCFPseudos`. **Optimal** (minimal-copy) PHI elimination remains a research topic; the current implementation is correct but not copy-minimal (no full coalescer yet).

---

## Input MIR

**SSA-form Machine IR with physical registers**
- All registers assigned to physical registers
- PHI nodes present at merge points
- SSA invariants hold

## Output MIR

**Non-SSA Machine IR**
- No PHI nodes
- Explicit copy instructions where needed
- Ready for final code emission
- Traditional register assignment complete

---

## Goal

Eliminate PHI nodes with:
- No copies (ideal)
- Minimal interference
- Preserved correctness

## Complexity

Correct PHI elimination is straightforward (insert copies on predecessor edges,
break parallel-copy cycles) and **is implemented**. Doing it *optimally*
(minimal copies, no unnecessary register pressure) is NP-hard in general and
remains an open improvement — the current `resolvePermutation`-based lowering is
correct but not copy-minimal.

## Challenges

| Challenge | Description |
|-----------|-------------|
| Lost copies | PHI semantics require parallel assignment |
| Permutation cycles | May need swap/temp registers |
| Critical edges | May require edge splitting |
| Lane masks | AMDGPU subregisters complicate copy insertion |

## Theory

- [SSA Destruction (Concept)](SSA_Destruction.md)
- `PHI Copies & Permutations`

## Related

- [SSA_Rebuilder](SSA_Rebuilder.md) — inverse operation (SSA reconstruction)
- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) — lane-aware PHI handling



