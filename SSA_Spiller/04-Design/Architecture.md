# Architecture

End-to-end SSA Regalloc architecture for AMDGPU.

## Today
- SSA while spilling
- Store-at-definition
- No WWM
- Reload first, shrink intervals later

## Future
- SSA based register allocator
- Final SSA deconstructor

## Key Decision
Separate "where value stored" from "when register freed".

## Historical Designs (Rejected)

- [Old Spill Placement Design](SSA_Spiller/06-Research/Archive/Old_Spill_Placement_Design.md)

