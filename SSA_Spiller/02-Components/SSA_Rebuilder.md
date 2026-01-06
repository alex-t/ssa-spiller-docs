# SSA Rebuilder

**Temporary SSA reconstruction pass for AMDGPU Machine IR**

## Status

⚠️ **Temporary component** — will be removed when all MIR passes before RA are SSA-clean.

## Purpose

Restores SSA form after PHI Elimination pass destroys it. Required during the transition period when:
- Some passes are still non-SSA aware
- PHI Elimination runs before register allocation

## Lifetime

This pass disappears when:
- All passes before RA are SSA-clean
- SSA survives naturally until register allocation

## Dependencies

- [[MachineLaneSSAUpdater]] — used for SSA repair

## Related

- [[SSA_Spiller]] — consumer of SSA form
- [[../03-Concepts/PHI_T-Transform|PHI T-Transform]] — transformation used during SSA repair

