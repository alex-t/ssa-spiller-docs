# SSA Destruction

**Final lowering of SSA to non-SSA Machine IR**

## Status

📋 **Not implemented** — research topic with high complexity.

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

**Very high** — this is an unresolved research topic.

PHI elimination is trivial in theory (insert copies on predecessor edges), but doing it *optimally* (minimal copies, no unnecessary register pressure) is NP-hard in general.

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



