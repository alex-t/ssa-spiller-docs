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

## SSA RA / coloring

- **PHI coalescer**  
  Recolor PHI operands to reduce copies post-coloring (paper §4.3). Listed as future optimization relative to “21 tests passing, not optimized” era. (`NOTES.md` 2026-06-08)

- **End-to-end occupancy-aware tuning**  
  Use `getMaxNumVGPRs(MF)` / occupancy APIs consistently in spiller + RA when tightening budgets for real kernels.

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
