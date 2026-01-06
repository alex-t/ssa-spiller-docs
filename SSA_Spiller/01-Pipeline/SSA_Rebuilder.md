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
Relies on [Components/MachineLaneSSAUpdater](Components/MachineLaneSSAUpdater.md) <!-- TODO: file not found -->

## Related
- [Pipeline/Early SSA Spiller](Pipeline/Early_SSA_Spiller.md) <!-- TODO: file not found -->
- [Concepts/PHI T-Transform](Concepts/PHI_T-Transform.md) <!-- TODO: file not found -->
