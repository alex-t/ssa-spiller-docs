# SSA Spiller Test Approach

Spiller tests live under `llvm/test/CodeGen/AMDGPU/SSASpiller/` (MIR
`-run-pass` tests) with end-to-end pipeline `.ll` tests under
`llvm/test/CodeGen/AMDGPU/SSARA/`.

- **Invocation:** `-run-pass=amdgpu-ssa-register-spiller` (chained with
  `amdgpu-ssa-register-allocator` / `si-lower-sgpr-spills` when a test checks
  past-coloring or SGPR-lowering output). End-to-end `.ll` tests use the hidden
  `-amdgpu-ssa-regalloc` option.
- **Forcing spills:** `-mcpu=gfx1200` plus an `"amdgpu-num-vgpr"="N"` function
  attribute (newer reconstruction tests use `N=3`).
- **Test-only flags:** `-amdgpu-ssa-spill-markers` emits `SI_VIRTUAL_SPILL_MARKER`
  at the virtual spill point (default OFF); `-amdgpu-ssa-spill-no-reload-opt`
  disables reload-placement optimization for deterministic checks.
- **What is exercised:** store-at-definition, dominance-ordered on-demand
  reloads against a frozen pruned interval, per-edge availability, and inline
  reaching-VNI SSA reconstruction (`repairSSAForNewDef`) that leaves the
  spiller output in SSA form.
- **Design discipline:** author one test at a time — sketch the CFG + liveness,
  get approval, create the file, then run.

## Dominance-grouping design artifacts

- `dom_group_test.md`
- [How to model dom groups.md](How_to_model_dom_groups.md)
- [Drawing 2025-12-21 12.05.25.excalidraw](Drawing_2025-12-21_12.05.25.excalidraw.md)
- `overlap dom group.png`
- `ssa repair bug negative.png`
- [test_dom_group_spill](test_dom_group_spill.md)
- [test_dom_group_spill.pdf](test_dom_group_spill.pdf)