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
Store-at-definition eliminates [EXEC drift](Spilling_issue_divergent_CFG.canvas.md) <!-- TODO: file not found --> and removes the need for WWM.
[Old Spill Placement Design](../06-Research/Archive/Old_Spill_Placement_Design.md)

## Related
- [02-Components/SSA Spiller](02-Components/SSA_Spiller.md) <!-- TODO: file not found -->
- [03-Concepts/MIN Algorithm (Belady)](03-Concepts/MIN_Algorithm_(Belady).md) <!-- TODO: file not found -->
- [03-Concepts/PHI T-Transform](03-Concepts/PHI_T-Transform.md) <!-- TODO: file not found -->
