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
Store-at-definition eliminates `EXEC drift` and removes the need for WWM.
[Old Spill Placement Design](SSA_Spiller/06-Research/Archive/Old_Spill_Placement_Design.md)

## Related
- [SSA Spiller](SSA_Spiller/02-Components/SSA_Spiller.md)
- `MIN Algorithm (Belady)`
- [PHI T-Transform](SSA_Spiller/03-Concepts/PHI_T-Transform.md)
