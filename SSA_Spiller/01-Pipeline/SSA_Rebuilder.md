# SSA Rebuilder

Temporary SSA reconstruction pass.

## Purpose
Ensure Machine IR is in SSA form during transition period when:
- some passes are still non-SSA
- PHI Elimination still runs

## Lifetime
This pass disappears when:
- all passes are SSA-clean
- SSA survives until register allocation

## Dependency
Relies on [MachineLaneSSAUpdater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md)

## Related
- [Early SSA Spiller](SSA_Spiller/01-Pipeline/Early_SSA_Spiller.md)
- [PHI T-Transform](SSA_Spiller/03-Concepts/PHI_T-Transform.md)
