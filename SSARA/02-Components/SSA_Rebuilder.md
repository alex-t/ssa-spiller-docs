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

## Current implementation (`AMDGPURebuildSSALegacy`, `ssara` worktree)

Reconstruction is delegated entirely to [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md); the pass no
longer contains its own reaching-definition logic. `runOnMachineFunction`:

1. Early-exits when `MRI->isSSA()` is already true (nothing to rebuild).
2. Computes a dominator-tree pre-order numbering of all blocks.
3. For each vreg whose `LiveInterval` has more than one value number:
   - Find the **establishing** (`Root`) non-PHI value — the earliest in
     dom-preorder (slot-ordered within a block for read-modify-write chains).
   - Build a worklist of the remaining non-PHI re-def `VNInfo`s in dom-preorder,
     with `Root` placed **last**.
   - Call `Updater.repairSSAForNewDef(*DefMI, VReg, PHIDefs)` for each entry,
     renaming the re-def to a fresh single-def vreg and inserting lane-aware
     PHIs. `Root` is only re-processed when it is a partial (subregister) def
     (a full-register `Root` is already the unique SSA def for its lanes).
4. `flattenRegSequences` — collapse the nested `REG_SEQUENCE` towers produced by
   lane-by-lane reconstruction into flat `REG_SEQUENCE`s, so wide values rebuilt
   from many narrow defs do not carry growing-width live intermediates (which
   would inflate register pressure) into allocation.
5. Set the `IsSSA` property; reset `NoPHIs` (PHIs were inserted) and
   `TiedOpsRewritten` (re-SSA-ifying turns rewritten two-address tied operands
   back into distinct SSA values, so the function is no longer in two-address
   form).

### Reaching-definition correctness (critical)

Attributing each use to the value **live immediately before that use** — not
merely to a value whose def precedes the use in block order or dominates the
use's block — is essential. A vreg redefined within a block (e.g. a loop
induction variable: `PHI -> S_ADD redef -> S_CMP use`) has multiple value
numbers live at different points in the same block; a position-only test
(`DefIdx < UseIdx`, or block dominance) wrongly attributes a post-redefinition
use to the earlier value.

This is now handled inside `MachineLaneSSAUpdater`, which resolves each use by
the reaching `VNInfo` read from a frozen copy of the original vreg's live
interval (PHI operands read at the end of the predecessor edge). See
[MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md).

> Bug history: an earlier inline heuristic (`DefIdx < UseIdx` same-block /
> `dominates()` cross-block) mis-attributed post-redefinition uses, producing
> spurious back-edge copies in scalar loops. Superseded by the reaching-VNI
> repair in `MachineLaneSSAUpdater` (see `08-Worklog/NOTES.md`).

## Lifetime

This pass disappears when:
- All passes before RA are SSA-clean
- SSA survives naturally until register allocation

## Dependencies

- LiveIntervals, MachineDominatorTree
- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) — **done**: SSA repair (def renaming + lane-aware PHI
  insertion + reaching-VNI use rewriting) is delegated entirely to the updater;
  the pass holds no inline reaching-def logic. (`MachineLoopInfo` is no longer a
  dependency.)

## Related

- [SSA_Spiller](SSA_Spiller.md) — consumer of SSA form
- [PHI T-Transform](../03-Concepts/PHI_T-Transform.md) — transformation used during SSA repair



