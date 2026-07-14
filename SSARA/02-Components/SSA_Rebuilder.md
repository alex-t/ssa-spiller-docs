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
- Insert PHI nodes at merge points
- Rewrite uses to correct reaching definitions
- Lane-aware: handles subregisters correctly

## Current implementation (inline, `ssara` worktree)

Ported from PR #156049. Reconstructs SSA without `MachineLaneSSAUpdater`, using
LiveIntervals value numbers directly:

1. For each vreg with >1 value number, build a worklist of its `VNInfo`s,
   sorted by dominance pre-order of the defining block.
2. `buildRealPHI` — materialize a real PHI for each PHI-def value number.
3. `splitNonPhiValue` — clone each non-PHI redefinition into a fresh single-def vreg.
4. `rewriteUses` — rewrite each use to the value number that actually reaches it.

### Reaching-definition correctness (critical)

`rewriteUses` must attribute each use to the value number **live immediately before
that use**, not merely to a value whose def precedes the use in block order or
dominates the use's block. A vreg redefined within a block (e.g. a loop induction
variable: `PHI -> S_ADD redef -> S_CMP use`) has multiple value numbers live at
different points in the same block; a position-only test (`DefIdx < UseIdx`, or
block dominance) wrongly attributes a post-redefinition use to the earlier value.

The correct, exact test queries the live interval:

```cpp
SlotIndex UseIdx = LIS->getInstructionIndex(*UseMI).getRegSlot();
return LI.getVNInfoBefore(UseIdx) == VNI;   // value reaching this use
```

PHI operands are the exception — they read at the end of the predecessor edge
(`getVNInfoBefore(getMBBEndIdx(Pred))`).

> Bug history: the original heuristic (`DefIdx < UseIdx` same-block / `dominates()`
> cross-block) mis-attributed post-redefinition uses, producing spurious back-edge
> copies in scalar loops. Fixed 2026-06-15 (see `08-Worklog/NOTES.md`).

## Lifetime

This pass disappears when:
- All passes before RA are SSA-clean
- SSA survives naturally until register allocation

## Dependencies

- LiveIntervals, MachineDominatorTree, MachineLoopInfo (current inline implementation)
- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) — **planned**: the intended refactor delegates SSA repair
  to the updater (def-first renaming), removing the inline reaching-def logic.
  Not yet implemented — see `08-Worklog/FUTURE_IMPROVEMENTS.md`.

## Related

- [SSA_Spiller](SSA_Spiller.md) — consumer of SSA form
- [PHI T-Transform](../03-Concepts/PHI_T-Transform.md) — transformation used during SSA repair



