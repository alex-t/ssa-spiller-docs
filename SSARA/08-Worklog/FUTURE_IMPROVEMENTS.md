# Future improvements — SSARA / Spiller / pipeline

Ideas captured from design discussion, `NOTES.md`, and `SHARED_CONTEXT.md` (**Future Optimizations**). Not committed backlog — nice-to-have or later-phase optimizations.

---

## Spiller / lowering

- **Threshold-guarded SGPR→VGPR lowering**  
  Cap lane allocation so `VGPRLimit - SpillVGPRs >= Threshold`; excess SGPR spills go to memory instead of starving VGPR budget. (`SHARED_CONTEXT.md`)

- **Per-program-point SGPR routing**  
  Use local VGPR pressure from Pass 1 forward walk to choose VGPR lane vs memory per spill site (hybrid lowering). (`SHARED_CONTEXT.md`)

- **Narrow spill-VGPR liveness in `LivePhysRP`**  
  Spill VGPRs live only in `[first_writelane, last_readlane]`, not whole function — fold into Pass 2 pressure (“Phase 2” of `lowerSGPRSpills`). (`SHARED_CONTEXT.md`, `AGENTS.md`)

- **`handleReachableUse()` cost model**  
  Uncomment / restore split-before-reload path only when profitability says non-dominated-use split beats alternatives. (`NOTES.md` / older worklog notes on reachable uses)

- **Reload optimizer** (already landed commits per git log — keep extending)  
  Further profitability for reload placement vs SSA repair cost.

- **Spill/reload combiner (wide-subreg merging)**  
  After partial-subreg spilling, a wide virtual register whose individual 32-bit
  sub-slots are all spilled appears as N separate `SI_SPILL_S32_SAVE` / `SI_SPILL_V32_SAVE`
  instructions, and N matching restores — one per sub-slot:

  ```
  %x:vreg_1024 = ...            ; def

  SI_SPILL_V32_SAVE %x.sub0,  lane=0
  SI_SPILL_V32_SAVE %x.sub1,  lane=1
  ...
  SI_SPILL_V32_SAVE %x.sub31, lane=31

  ... high-pressure region ...

  SI_RESTORE_S32_FROM_VGPR %x.sub31, lane=31
  SI_RESTORE_S32_FROM_VGPR %x.sub30, lane=30
  ...
  SI_RESTORE_S32_FROM_VGPR %x.sub0,  lane=0
  ```

  A post-spill combiner pass could detect N consecutive sub-slot spills of the same base
  register and merge them into a single wider spill pseudo (e.g. 32 × S32 → S1024), and
  the corresponding restores. This eliminates pseudo-instruction count and simplifies
  downstream lowering.

  Constraints to respect:
  - Sub-slot indices must be consecutive and cover the full target width.
  - The wider spill opcode must exist (`SI_SPILL_S64_SAVE`, `SI_SPILL_V128_SAVE`, etc.).
  - Intervening instructions must not kill or redefine any of the sub-slots.
  - Ordering: all spills before the pressure region; all restores after.

  Natural insertion point: between the spiller (`AMDGPUSSARegisterSpiller`) and
  `SILowerSGPRSpills`, operating on the still-virtual-SGPR pseudo instructions.
  For VGPRs the combiner would run before PEI.

## SSA RA / coloring

- **PHI coalescer**  
  Recolor PHI operands to reduce copies post-coloring (paper §4.3). Listed as future optimization relative to “21 tests passing, not optimized” era. (`NOTES.md` 2026-06-08)

- **End-to-end occupancy-aware tuning**  
  Use `getMaxNumVGPRs(MF)` / occupancy APIs consistently in spiller + RA when tightening budgets for real kernels.

## RebuildSSA

- **Refactor RebuildSSA to use `MachineLaneSSAUpdater`** (long-planned parallel task)
  The current `AMDGPURebuildSSA` (ported from PR #156049, `ssara` worktree) reconstructs
  SSA with a hand-rolled inline approach: enumerate LiveIntervals value numbers, then
  `buildRealPHI` / `splitNonPhiValue` / `rewriteUses` with a `reachedByThisVNI` reaching
  test. This is fragile — the original `DefIdx<UseIdx` / dominance heuristics mis-attributed
  post-redefinition uses to earlier values (fixed 2026-06-15 by querying
  `LI.getVNInfoBefore(UseSlot)`, but the whole approach remains a re-derivation of
  reaching-def info that LiveIntervals/the updater already compute).
  The intended design (`02-Components/SSA_Rebuilder.md` dependency stub; biweekly
  `2026-05-02`, status `2026-05-15`) is a **def-first renaming walk delegating to
  `MachineLaneSSAUpdater::repairSSAForNewDef`** — the same battle-tested engine the
  spiller uses. This removes the `reachedByThisVNI` heuristic entirely (correct by
  construction) and unifies SSA repair across spiller and rebuilder.
  Worktree `ssa-rebuilder` was created for this but still holds the un-refactored inline
  version. RebuildSSA is a temporary bridge pass, so weigh effort vs. its expected lifetime.

## Tooling / workflow

- **Bisect helper script**  
  Always `ninja -C build/user-debug bin/llc` (or touched `.o` + link) then `llvm-lit` single test — avoids false first-bad on dead-code commits. (`NOTES.md` 2026-06-10)

- **Full-suite gate**  
  Cursor rule `test-after-change.mdc` already mandates full `SSASpiller/` + `SSARA/` after spiller/RA edits — extend to CI when upstream allows.

## Docs / education

- **md2pdf / Mermaid**  
  Keep design PDFs in sync when `SSA_RA_Coloring.md` or destruction docs change (`AGENTS.md` tools).

- **Chordality / PEO narrative**  
  Optional deeper links (Gavril 1974, dominance-tree PEO) in concept docs — already partially in `NOTES.md` 2026-05-26.

---

## Distinction vs `BACKLOG.md`

| `BACKLOG.md` | This file |
|--------------|-----------|
| Failing tests, correctness bugs, missing MUST-have features | Optimizations, hybrid heuristics, CI polish |
| Ordered for implementation | Parking lot for prioritization |

When an item becomes blocking, move it to `BACKLOG.md` and `NOTES.md`.
