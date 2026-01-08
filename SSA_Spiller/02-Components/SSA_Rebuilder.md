# SSA Rebuilder

**Temporary SSA reconstruction pass for AMDGPU Machine IR**

## Status

⚠️ **Temporary component** — will be removed when all MIR passes before RA are SSA-clean.

---

## Input MIR

**Non-SSA Machine IR**
- PHI nodes eliminated
- Multiple definitions per virtual register possible
- Result of PHI Elimination pass

## Output MIR

**SSA-form Machine IR**
- Single definition per virtual register (per lane)
- All uses dominated by their definitions
- PHI nodes at control flow merge points
- LiveIntervals valid

---

## Purpose

Restores SSA form after PHI Elimination pass destroys it. Required during the transition period when:
- Some passes are still non-SSA aware
- PHI Elimination runs before register allocation

## Function

- Identify violated SSA invariants (multiple defs)
- Insert PHI nodes at iterated dominance frontier
- Rewrite uses to correct reaching definitions
- Lane-aware: handles subregisters correctly

## Lifetime

This pass disappears when:
- All passes before RA are SSA-clean
- SSA survives naturally until register allocation

## Dependencies

- [MachineLaneSSAUpdater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md) — used for SSA repair

## Related

- [SSA_Spiller](SSA_Spiller/02-Components/SSA_Spiller.md) — consumer of SSA form
- [PHI T-Transform](SSA_Spiller/03-Concepts/PHI_T-Transform.md) — transformation used during SSA repair



