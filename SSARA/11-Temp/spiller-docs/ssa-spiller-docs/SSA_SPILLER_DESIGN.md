# SSA Register Spiller (AMDGPU) — Design (Current)

This document describes the **current** SSA-aware register spilling pass for AMDGPU, as implemented in LLVM Machine IR.

## Source Mapping
- **Component**: SSA Register Spiller
- **LLVM Target**: AMDGPU
- **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`
- **GitHub (canonical)**: `https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`

### Related components
- **Component**: MachineLaneSSAUpdater (SSA repair + IDF reachability)
  - **File (symbolic)**: `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`
  - **Upstream PR**: `https://github.com/llvm/llvm-project/pull/163421`
- **Component**: AMDGPU Next Use Analysis (next-use distances + lane/subreg ordering)
  - **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h`
  - **Upstream PR**: `https://github.com/llvm/llvm-project/pull/156079`

## Overview
The SSA spiller is a MachineFunction pass that:
- Tracks register pressure (RP) while scanning instructions.
- When RP exceeds a limit, selects one or more **spill candidates** using a Belady-style next-use heuristic.
- Stores spilled values **at definition** to avoid EXEC drift issues.
- Computes a **virtual spill point** (where the value is considered “logically dead” for RP relief).
- Inserts reloads and repairs SSA form using `MachineLaneSSAUpdater`.
- Shrinks live intervals after repairs to reflect the new SSA use graph.

## Terminology
- **VMP (VRegMaskPair)**: `(VReg, LaneMask)` pair representing “a virtual register, possibly partial lanes”.
- **Physical store location**: the place where a stack store is emitted (current design: right after definition).
- **Virtual spill point**: the location where RP relief is intended (computed as a `KillIdx`).
- **Dominated use**: a use that is on all paths after the virtual spill point.
- **Reachable (non-dominated) use**: a use that may be reached from the spill path, but not dominated by the spill point; requires SSA merging logic (PHIs).

## High-level workflow

```mermaid
flowchart TD
  entry["runOnMachineFunction"] --> procFn["processFunction (scan blocks + track RP)"]
  procFn --> highRP["RP exceeds limit at instruction I"]
  highRP --> liveSet["compute Active live set at I"]
  liveSet --> pick["getVMPsToSpill (Belady + lane splitting)"]
  pick --> perVmp["spillAndReload (one VMP at a time)"]
  perVmp --> storeDef["spillAtDefinition (store after def)"]
  storeDef --> killIdx["compute KillIdx (virtual spill point)"]
  killIdx --> marker["optional SI_VIRTUAL_SPILL_MARKER"]
  marker --> reloads["emitReloadsAndRepairSSA"]
  reloads --> shrink["shrinkToUses (after SSA repair)"]
  shrink --> procFn
```

### Key orchestration points
- `AMDGPUSSARegisterSpiller::spillAndReload`  
  - **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`  
  - **GitHub**: `https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp#L615-L717`
- `AMDGPUSSARegisterSpiller::emitReloadsAndRepairSSA`  
  - **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`  
  - **GitHub**: `https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp#L719-L929`
- `AMDGPUSSARegisterSpiller::spillAtDefinition`  
  - **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`  
  - **GitHub**: `https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp#L935-L1016`

## Spill selection (Belady + lane splitting)
When a candidate register is larger than the remaining “spill budget”, the spiller asks NextUseAnalysis for a subreg/lane ordering:
- API usage: `NU->getSortedSubregUses(...)` in `AMDGPUSSARegisterSpiller::getVMPsToSpill`
- Intent: choose the **furthest-used subregister lanes first**, so we spill only as many 32-bit units as needed.

This is the mechanism behind the “large register but only need 32-bit” artificial pattern used by `spill-vreg-many-lanes.mir`.

## Virtual spill point and SI_VIRTUAL_SPILL_MARKER

### What “virtual spill point” means
The spiller separates:
- **Where we store**: after definition (`spillAtDefinition`).
- **Where RP relief is intended**: the computed `KillIdx` for the high-pressure point.

### Marker pseudo-instruction (for tests)
- Option: `--amdgpu-ssa-spill-markers=1`
- Pseudo MI: `SI_VIRTUAL_SPILL_MARKER <vreg_index>, <lane_mask>`

Insertion rule (simplified): if the marker would be placed **immediately adjacent** to the actual store for the same `(VReg,LaneMask)`, insertion is omitted.

## Dominated vs reachable uses

### Classification (spiller-side)
In `AMDGPUSSARegisterSpiller::emitReloadsAndRepairSSA`, for each non-PHI use of the spilled VReg and overlapping lane mask:
- **Dominated** if `DT->dominates(KillMI, UseMI)`
- Else **Reachable** if `SSAUpdater->isUseReachableFromDef(KillMI, UseMI, OrigVReg, DefMask)`
- Else unreachable (ignored)

## Reach/IDF definition (verbatim + code-equivalent)

### (A) Verbatim (as provided)
Reach(Spill(x) = $\forall use(x)$ such that $Parent(use(x)) \in IDF(Parent(Spill(x)))) \land \forall (use(x)$ such that $\exists B\in IDF(Spill(x))$ such that $B\in Dom(Parent(use(x))$

Your diagram (mermaid-safe formatting):

```mermaid
flowchart TD
  A["x = def(x)"] --> B["use(x)"] --> C{"Cond?"}
  C -->|Yes| D["..."]
  C -->|No| E["Spill(x)"]
  E --> F["use(x)"]
  D --> F
  F --> G["use(x)"]
  F --> B
```

### (B) Code-equivalent definition (matches MachineLaneSSAUpdater)
`MachineLaneSSAUpdater::isUseReachableFromDef(DefMI, UseMI, OrigVReg, DefMask)` does:
1. If `DefMI` dominates the use, returns true immediately.
2. Otherwise, compute a **pruned IDF** for `(OrigVReg, DefMask, DefBlock)` (DefBlock = `DefMI->Parent`).
3. Define `PredBlock`:
   - if `UseMI` is a PHI use, `PredBlock` is the PHI predecessor block for that operand
   - else `PredBlock` is `UseMI->Parent`
4. Return reachable iff there exists `IDFBlock` such that:
   - `PredBlock == IDFBlock`, or
   - `IDFBlock` dominates `PredBlock`

Source:
- **File (symbolic)**: `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`, function `MachineLaneSSAUpdater::isUseReachableFromDef(MachineInstr*, ...)`
- **Upstream PR**: `https://github.com/llvm/llvm-project/pull/163421`

## SSA repair: what gets rewritten and where PHIs come from
The spiller emits reload instructions and then calls:
- `MachineLaneSSAUpdater::repairSSAForNewDef(...)`

That updater:
- Creates lane-aware PHIs in IDF blocks for non-dominated joins.
- Rewrites dominated uses to the new SSA value.
- Keeps lane masks correct via operand/subreg masks.

## Worked “patterns” (concept-level)

### Dominated linear case (single path)
```mermaid
flowchart TD
  subgraph d_bb0[bb0]
    direction TB
    d_bb0_i1["def x"]
    d_bb0_i2["idx0 = spill_slot(x)"]
    d_bb0_i3["store x -> idx0"]
    d_bb0_i1 -.-> d_bb0_i2
    d_bb0_i2 -.-> d_bb0_i3
  end

  subgraph d_bb1[bb1]
    direction TB
    d_bb1_i1["use x (before virtual spill point)"]
  end

  subgraph d_bb2[bb2]
    direction TB
    d_bb2_i1["virtual_spill_point (KillIdx)"]
  end

  subgraph d_bb3[bb3]
    direction TB
    d_bb3_i1["y = reload(idx0)"]
  end

  subgraph d_bb4[bb4]
    direction TB
    d_bb4_i1["use y"]
  end

  d_bb0_i3 --> d_bb1_i1
  d_bb1_i1 --> d_bb2_i1
  d_bb2_i1 --> d_bb3_i1
  d_bb3_i1 --> d_bb4_i1
```

### Reachable (non-dominated) case (join)
<div style="display:flex; gap:24px; align-items:flex-start;">
<div style="flex:1;">

**Before spill**

```mermaid
flowchart TD
  subgraph b_bb0[bb0]
    direction TB
    b_bb0_i1["def x"]
  end

  subgraph b_bb1[bb1]
    direction TB
    b_bb1_t{"branch"}
  end

  subgraph b_bb2[bb2]
    direction TB
    b_bb2_i1["RP exceeds limit here"]
  end

  subgraph b_bb3[bb3]
    direction TB
    b_bb3_i1["..."]
  end

  subgraph b_bb4[bb4]
    direction TB
    b_bb4_i1["join"]
  end

  subgraph b_bb5[bb5]
    direction TB
    b_bb5_i1["use x"]
  end

  b_bb0_i1 --> b_bb1_t
  b_bb1_t -->|"spill_path"| b_bb2_i1
  b_bb1_t -->|"clean_path"| b_bb3_i1
  b_bb2_i1 --> b_bb4_i1
  b_bb3_i1 --> b_bb4_i1
  b_bb4_i1 --> b_bb5_i1
```

</div>
<div style="flex:1;">

**After spill**

```mermaid
flowchart TD
  subgraph a_bb0[bb0]
    direction TB
    a_bb0_i1["def x"]
    a_bb0_i2["idx0 = spill_slot(x)"]
    a_bb0_i3["store x -> idx0"]
    a_bb0_i1 -.-> a_bb0_i2
    a_bb0_i2 -.-> a_bb0_i3
  end

  subgraph a_bb1[bb1]
    direction TB
    a_bb1_t{"branch"}
  end

  subgraph a_bb2[bb2]
    direction TB
    a_bb2_i1["virtual_spill_point (KillIdx)"]
    a_bb2_i2["marker optional"]
    a_bb2_i1 -.-> a_bb2_i2
  end

  subgraph a_bb3[bb3]
    direction TB
    a_bb3_i1["..."]
  end

  subgraph a_bb6[bb6]
    direction TB
    a_bb6_i1["y = reload(idx0)"]
  end

  subgraph a_bb4[bb4]
    direction TB
    a_bb4_i1["join"]
    a_bb4_i2["z = PHI(y, bb6, x, bb3)"]
    a_bb4_i1 -.-> a_bb4_i2
  end

  subgraph a_bb5[bb5]
    direction TB
    a_bb5_i1["use z"]
  end

  a_bb0_i3 --> a_bb1_t
  a_bb1_t -->|"spill_path"| a_bb2_i1
  a_bb1_t -->|"clean_path"| a_bb3_i1
  a_bb2_i2 --> a_bb6_i1
  a_bb6_i1 --> a_bb4_i1
  a_bb3_i1 --> a_bb4_i1
  a_bb4_i2 --> a_bb5_i1
```

</div>
</div>

## Mapping to tests
See `SSA_SPILLER_TEST_PATTERNS.md` for per-test diagrams and marker notes.

## Appendix A: historical notes (brief)
- Older materials in `Misc/` may illustrate earlier variants of SSA spilling concepts; reuse is encouraged if the diagram is updated to match current workflow.


