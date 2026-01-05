# Early SSA Spiller

Core SSA-aware spilling stage before register allocation.

## Current Strategy
- Store-at-definition spill placement
- Virtual spill point via KillIdx
- Single physical store per register
- Reloads inserted later, SSA-aware

## Flow (current)
1. spillAtDefinition()
2. compute KillIdx
3. assignVirt2StackSlot()
4. emitReloadsAndRepairSSA()
5. shrinkToUses()

## Rationale
Store-at-definition eliminates [[Spilling issue divergent CFG.canvas|EXEC drift]] and removes the need for WWM.
[[Old Spill Placement Design]]

## Related
- [[02-Components/SSA Spiller]]
- [[03-Concepts/MIN Algorithm (Belady)]]
- [[03-Concepts/PHI T-Transform]]
