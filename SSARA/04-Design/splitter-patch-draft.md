# Split+Assign Patch Draft

Saved: 2026-05-14

> **Status: DRAFT — NOT IMPLEMENTED.** This live-range splitter does **not**
> exist in the shipped code. No `splitForOccupancy`, `planSplit`, `commitPlan`,
> `findFreeInRange`, `isPhysRegFreeForRange`, `SplitPlan`/`RecolorPlan`/
> `OccupancyPlan`, or related members are present in
> `AMDGPUSSARegisterAllocator.{h,cpp}`. The allocator performs width-descending
> PEO coloring and SSA destruction, but has no threshold-driven occupancy
> splitting. Everything below is a proposed patch, retained for reference.

## Status: Under Review

The patch implements threshold-driven LR splitting for occupancy improvement.
This is a draft — not yet applied to the codebase.

## Issues Addressed

1. **Sub-reg packing in freed space** — initial version tried to fit competitors into the exact same freed physreg tuple. Fixed: `findFreeInRange` iterates sub-tuples within the freed range (e.g., B→(4,5) and C→(6,7) from freed (4-7)).

2. **Allocation order scan too expensive** — initial competitor re-coloring iterated the full allocation order (up to 256 VGPRs), each calling `isPhysRegFreeForRange`. Fixed: `findFreeInRange` iterates only `[FreedStart, FreedEnd)` hw indices, constructs physregs directly via `AMDGPU::VGPR0 + Idx` + `getMatchingSuperReg`.

3. **Duplicate overlap check code** — the split validation and competitor re-coloring had identical overlap logic inlined. Fixed: factored out `isPhysRegFreeForRange(PhysReg, Start, End, Shadow)` used by both.

4. **B extending past E' end** — a competitor whose live range extends past the split fragment's end can't be re-colored into freed space as-is. Handled: `isPhysRegFreeForRange` checks the competitor's FULL range against the Shadow, correctly rejecting it. The competitor becomes a split candidate in a subsequent iteration (candidates sorted widest-first).

5. **Multiple splits per plan** — initial version did one split and stopped. Fixed: outer loop continues through candidates until target reached or no more viable splits.

6. **Metrics for split candidate selection** — initial version used only width. Fixed: candidates sorted widest-first (metric 1: width = slots freed per COPY), competitor count evaluated per candidate (metric 2: packable competitors in freed space).

## Patch

### Header additions (AMDGPUSSARegisterAllocator.h)

New includes:
- `llvm/ADT/SmallVector.h`

New forward declarations:
- `class GCNSubtarget`
- `class MachineLaneSSAUpdater`

New members:
- `SlotIndexes *Indexes`
- `const GCNSubtarget *ST`

New types:
- `SplitPlan` — records a vreg split (vreg, split point, new physreg)
- `RecolorPlan` — records a competitor re-coloring (vreg, old physreg, new physreg)
- `OccupancyPlan` — holds vectors of SplitPlan + RecolorPlan + new max index

New methods:
- `splitForOccupancy(MF)` — entry point, threshold-driven
- `planSplit(Plan, TargetMaxIndex)` — read-only simulation on ShadowColorMap
- `commitPlan(MF, Plan)` — inserts COPYs, rewrites uses, applies re-colorings
- `computeMaxPhysRegIndex(IsVGPR)` — max hw index from ColorMap
- `isPhysRegFreeForRange(PhysReg, Start, End, Shadow)` — pairwise LI overlap check
- `findFreeInRange(RC, VReg, FreedStart, FreedEnd, Shadow)` — find free physreg within hw index range

### Implementation (AMDGPUSSARegisterAllocator.cpp)

New includes:
- `MCTargetDesc/AMDGPUMCTargetDesc.h` (for AMDGPU::VGPR0, AMDGPU::sub0)
- `llvm/CodeGen/MachineLaneSSAUpdater.h`

Key algorithm:
1. `splitForOccupancy`: compute current VGPR footprint, check next occupancy threshold, call planSplit
2. `planSplit`: copy ColorMap to Shadow, iterate candidates widest-first, find epoch boundaries (where another vreg dies), simulate split + competitor re-coloring via `findFreeInRange`, check if target reached
3. `commitPlan`: insert COPY instructions, rewrite uses via MachineLaneSSAUpdater, recompute LiveIntervals, update ColorMap with re-colorings

`findFreeInRange` constructs physregs directly from hw indices:
```cpp
MCRegister BaseReg = AMDGPU::VGPR0 + Idx;
MCRegister PR = (CompWidth == 1) ? BaseReg
    : TRI->getMatchingSuperReg(BaseReg, AMDGPU::sub0, RC);
```
No allocation order iteration needed.
