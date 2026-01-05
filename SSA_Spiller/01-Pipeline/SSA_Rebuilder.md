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
Relies on [[Components/MachineLaneSSAUpdater]]

## Related
- [[Pipeline/Early SSA Spiller]]
- [[Concepts/PHI T-Transform]]
