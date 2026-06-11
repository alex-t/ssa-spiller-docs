# SSA Register Spiller (AMDGPU) — Design (Current)

This document describes the **current** SSA-aware register spilling pass for AMDGPU, as implemented in LLVM Machine IR.

## Source Mapping
- **Component**: SSA Register Spiller
- **LLVM Target**: AMDGPU
- **File (symbolic)**: `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`
- **GitHub (canonical)**: [`AMDGPUSSARegisterSpiller.cpp`](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp)

### Related components
- **Component**: MachineLaneSSAUpdater (SSA repair + IDF reachability)
  - **File (symbolic)**: [`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp)
  - **Upstream PR**: [#163421](https://github.com/llvm/llvm-project/pull/163421)
- **Component**: AMDGPU Next Use Analysis (next-use distances + lane/subreg ordering)
  - **File (symbolic)**: [`llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h`](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h)
  - **Upstream PR**: [#156079](https://github.com/llvm/llvm-project/pull/156079)

## Overview
The SSA spiller is a MachineFunction pass that:
- Tracks register pressure (RP) while scanning instructions.
- When RP exceeds a limit, selects one or more **spill candidates** using a [Belady-style next-use heuristic](../03-Concepts/MIN_Algorithm.md).
- Stores spilled values [**at definition**](Decisions.md#store-at-definition) to avoid EXEC drift issues.
- Computes a [**virtual spill point**](#virtual-spill-point-and-si_virtual_spill_marker) (where the value is considered "logically dead" for RP relief).
- Inserts PHIs at **Pruned IDF (PIDF) blocks** first, then places reloads that automatically rewrite PHI operands.
- Uses [`MachineLaneSSAUpdater`](../02-Components/MachineLaneSSAUpdater.md) for SSA repair.
- Shrinks live intervals after repairs to reflect the new SSA use graph.


## Static Next-Use Analysis limitation (reload/PHI-created vregs)

### The issue
NextUseAnalysis (NUA) currently runs **before** spilling. During spilling we insert:
- reloads before uses of a spilled value, and
- PHIs during SSA repair (via [`MachineLaneSSAUpdater`](../02-Components/MachineLaneSSAUpdater.md)).

Each reload/PHI creates a **new SSA variable** (new virtual register / new live interval).
We run Next Use Analysis before the spiller when these new register don't yet exist. As a result, they have no entries in the NUA map and analysis consider these new vregs **dead**, which can immediately select them for spilling again — yielding **no RP relief** and eventually an RP validation failure. See [Static NUA limitation issue](../08-Worklog/issues/Next_Use_Analysis/Static_NUA_limitation.md).

```mermaid
flowchart TD
  A["NUA runs (builds next-use map)"] --> B["Spiller inserts reload: creates NewVReg"]
  B --> C["SSA repair inserts PHIs: creates PhiVRegs"]
  C --> D["NUA has no entries for {NewVReg,PhiVRegs}"]
  D --> E["Heuristic may pick freshly-created regs for spill"]
  E --> F["RP does not decrease -> validation error"]
```

### Longer-term directions (proposed)
- Return a special value from NUA meaning "no distance computed for this vreg".
- Add an on-demand API to compute next-use distance for new vregs created during spilling.

See [Static NUA limitation - Proposed solution](../08-Worklog/issues/Next_Use_Analysis/Static_NUA_limitation.md#proposed-solution).

### Temporary workaround (implemented now)
Maintain a [`VRegMaskPairSet`](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/VRegMaskPair.h) of vregs created by reload SSA repair and exclude them from the spiller's Active set selection.

See [Static NUA limitation - Temporary workaround](../08-Worklog/issues/Next_Use_Analysis/Static_NUA_limitation.md#temporary-workaround).

## Terminology
- [**VMP (VRegMaskPair)**](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/VRegMaskPair.h): `(VReg, LaneMask)` pair representing "a virtual register, possibly partial lanes".
- **Physical store location**: the place where a stack store is emitted (current design: right after definition).
- **Virtual spill point**: the location where RP relief is intended (computed as a `KillIdx`).
- **KillBB**: The basic block containing the virtual spill point (`KillMI`).
- **PIDF (Pruned IDF)**: Iterated Dominance Frontier of KillBB, pruned to blocks where the spilled register is live-in.
- **Kill-dominated use**: A use where `DT->dominates(KillMI, UseMI)` is true.
- **PIDF-dominated use**: A use dominated by a block in PIDF but not by KillMI.

## Two-Pass Architecture

The spiller processes the function twice:

1. **Pass 1 (SGPR)**: Process scalar registers. When pressure exceeds the SGPR limit, spill candidates are stored to the stack as `SI_SPILL_S*_SAVE` / `SI_SPILL_S*_RESTORE` pseudos. After Pass 1, `countSGPRSpillVGPRs()` computes how many VGPR lanes the SGPR spills will consume: $\lceil \sum_{FI} \text{objectSize}(FI)/4 \div \text{WaveSize} \rceil$ over distinct `SGPRSpill` frame indices. The VGPR budget is reduced: `VGPRLimit -= N`.
2. **Pass 2 (VGPR)**: Process vector registers with the reduced budget. VGPR spills go to memory as `SI_SPILL_V*_SAVE` / `V*_RESTORE`.

**SGPR spill materialization** (writelane/readlane) is **not done in the spiller**. SGPR spill pseudos stay in place until `SILowerSGPRSpills` runs after the SSA Register Allocator, when `SuperReg` is physical. This avoids the `SGPRSpillBuilder::getPhysRegBaseClass(virtual_reg)` crash that would occur if materialization were attempted pre-coloring.

> **Note:** AGPRs (accumulator GPRs) allocation has not been addressed yet.

This ordering ensures SGPR spills account for VGPR pressure correctly without double-counting.

## Dominance Grouping ([`DomGroup` class](https://github.com/alex-t/llvm-project/blob/early-ssa-spiller/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.h#L42-L60))

To minimize reload count, uses are grouped by dominance chains.

### Group Head Definition

A **group head** is the first (dominating) use instruction in a DomGroup. All other uses in the group are dominated by the head. A single reload placed before the head will satisfy all uses in the group.

```mermaid
flowchart TD
  subgraph domgroup["DomGroup"]
    head["Head: use1 (dominates all below)"]
    use2["use2 (dominated by head)"]
    use3["use3 (dominated by head)"]
  end
  
  reload["ONE reload before head"] --> head
  head --> use2
  head --> use3
```

### DomGroup class

```cpp
class DomGroup {
  MachineInstr *Head;                    // First use - dominates all others
  SmallVector<MachineInstr *, 4> DominatedUses;
public:
  MachineInstr *getHead() const;         // Get the dominating use
  void addDominatedUse(MachineInstr *MI);
  void promoteHead(MachineInstr *NewHead); // When new use dominates current head
  size_t size() const;
};
```

### Algorithm in `buildDomGroupsForSpill()`

1. Collect all uses of spilled register (reachable from KillMI)
2. Sort uses by dominance order (dominating uses first)
3. For each use:
   - If an existing group's head dominates this use → add to that group
   - If this use dominates an existing group's head → promote this use as new head
   - Otherwise → create new group with this use as head
4. Result: minimal set of groups; one reload per group head covers all uses in group

## Block Reload Cache

### Purpose

The `BlockReloadCache` prevents duplicate reloads when multiple uses in the same block or multiple PHI operands from the same predecessor need the reloaded value.

### Data Structure

```cpp
DenseMap<std::pair<MachineBasicBlock *, Register>, Register> BlockReloadCache;
// Key: (Block, SpilledReg) → Value: ReloadedReg
```

### Lifecycle

```mermaid
flowchart TD
  subgraph perSpill["Per-Spill Processing"]
    clear["BlockReloadCache.clear()"] --> process["Process PIDF blocks and uses"]
    process --> query{"getOrCreateReloadInBlock(BB)?"}
    query -->|"Cache miss"| create["Create reload instruction<br/>Cache: (BB, Reg) → NewReg<br/>Return {NewReg, ReloadMI}"]
    query -->|"Cache hit"| reuse["Return {CachedReg, nullptr}"]
    create --> more{"More uses?"}
    reuse --> more
    more -->|Yes| query
    more -->|No| done["Cache discarded at next spill"]
  end
```

### When Cached vs Not Cached

| Scenario | Cached? | Reason |
|----------|---------|--------|
| Reload at block end (before terminator) | Yes | May be reused by multiple PHI operands |
| Reload before specific use instruction | No | Position-specific, can't be reused |

### Cache Invalidation

The cache is **cleared at the start of each spill** (`emitReloadsAndRepairSSA()`). This ensures:
- Reloads from previous spill iterations don't interfere
- Fresh state for each register being spilled

### Return Value Semantics

`getOrCreateReloadInBlock()` returns `std::pair<Register, MachineInstr*>`:

| Return Value | Meaning | Caller Action |
|--------------|---------|---------------|
| `{Reg, ReloadMI}` | New reload created | Call `repairSSAForReload()` for IDF processing |
| `{Reg, nullptr}` | Cached reload reused | Call `rewriteDominatedUses()` only |

## Final RP Validation

After all spilling, `validateFinalRegisterPressure()` traverses the function to verify RP is within limits:

- Skips spill/reload instructions during validation
- If RP exceeds limit at any instruction, reports a fatal error
- This is a safety check until split-before-use optimization is implemented

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
  marker --> buildGroups["buildDomGroupsForSpill"]
  buildGroups --> reloads["emitReloadsAndRepairSSA<br/>(PHI-first PIDF strategy)"]
  reloads --> shrink["finalizeLiveIntervals"]
  shrink --> procFn
```

## Spill selection (Belady + lane splitting)

When a candidate register is larger than the remaining "spill budget", the spiller
selects only the minimum number of 32-bit sub-slots needed.

### Step 1 — NUA-based subreg ordering

`NU->getSortedSubregUses(...)` asks NextUseAnalysis for the per-lane use distances
of the candidate. This returns only lanes that appear as **distinct-mask uses** in the NUA
table (sorted furthest-first). If all uses reference the whole register (e.g.
`S_AND_B64 %w, %w` → mask `0x0F`), the result is a single entry covering all lanes.

### Step 2 — Fit-or-split loop

For each entry returned by NUA:

- If entry size ≤ `RemainingToSpill` → insert into `ToSpill`, decrement remaining.
- If entry size > `RemainingToSpill` (**"too large" branch**):  
  Decompose the entry into 32-bit parts using `TRI->getRegSplitParts(SubRC, 4)` and
  take only as many consecutive parts as `RemainingToSpill` requires. This guarantees
  exactly the needed number of slots are freed without over-spilling.

### Why NUA alone is insufficient for the "too large" case

NUA records use-site lane masks, not physical sub-register decompositions.
For a wide register used as a whole (e.g. `%w:sreg_64` always read/written as 64 bits),
`getSortedSubregUses` returns `[{%w, fullMask}]` — one entry of size 2.
If only 1 slot is needed, NUA cannot split further.
`getRegSplitParts` provides the sub-register boundary decomposition independently of NUA,
ensuring the minimum spill granularity is always 32 bits.

### Sub-register aware emission

When a partial lane mask is selected (e.g. sub0 of `sreg_64`):

- `spillAtDefinition` derives `SubRegIdx` from the lane mask via `VMP.getSubReg(MRI, TRI)`.
- `SIInstrInfo::storeRegToStackSlot` is called with `SubRegIdx`; it now emits
  `addReg(SrcReg, kill, SubRegIdx)` so the store pseudo is e.g.
  `SI_SPILL_S32_SAVE %w.sub0` rather than `SI_SPILL_S64_SAVE %w`.
- `constrainRegClass` is guarded by `SubRegIdx == 0` (the parent 64-bit vreg must not
  be constrained to a 32-bit register class).
- `loadRegFromStackSlot` already handled `SubRegIdx` correctly (unchanged).
- At the restore site, `MachineLaneSSAUpdater` inserts a `REG_SEQUENCE` to reconstruct
  the full wide value from the reloaded sub-slot plus the surviving remaining lanes.

### Example: `%w:sreg_64`, `RemainingToSpill = 1`

```
Before fix:  SI_SPILL_S64_SAVE %w       (2 lanes spilled, 1 VGPR lane wasted)
After fix:   SI_SPILL_S32_SAVE %w.sub0  (1 lane spilled, sub1 stays live)
             REG_SEQUENCE at restore: { reload_sub0, %w.sub1 } → full sreg_64
```

## Virtual spill point and SI_VIRTUAL_SPILL_MARKER

### What "virtual spill point" means
The spiller separates:
- **Where we store**: after definition (`spillAtDefinition`).
- **Where RP relief is intended**: the computed `KillIdx` for the high-pressure point.

### Marker pseudo-instruction (for tests)
- Option: `--amdgpu-ssa-spill-markers=1`
- Pseudo MI: `SI_VIRTUAL_SPILL_MARKER <vreg_index>, <lane_mask>`

---

# PHI-First PIDF Strategy

This section describes the core algorithm for reload placement and SSA repair.

## Key Design Insight: Why PHI-First Works

### The Invariant

By SSA construction, any block `B` in `IDF(KillBB)` where the spilled register is live-in **must** have a PHI to merge:
- The **reloaded value** from spill-path predecessors
- The **original value** from clean-path predecessors

This is not a choice—it's a requirement for SSA form correctness.

### The Strategy

Since PHIs are inevitable at PIDF blocks, we insert them **first** with all incoming operands set to `SpilledReg`:

```cpp
// All operands initially reference SpilledReg
PHI = insertPHIAtBlock(PIdfBB, SpilledReg, /*IncomingValues=*/{}, SpilledMask);
// Result: %phi = PHI [%x, bb.2], [%x, bb.3]  -- all operands = %x
```

### How Reloads Fix PHI Operands

When we insert a reload and call `rewriteDominatedUses(SpilledReg, ReloadReg, Mask)`, the SSA updater rewrites uses **dominated by the reload**. 

**Critical insight**: For PHI operands, the "use location" is the **end of the predecessor block**, not the PHI instruction itself. So if a reload dominates that predecessor's end, the PHI operand gets rewritten.

```mermaid
flowchart TD
  subgraph bb0["bb.0 (def)"]
    def["def %x"]
  end
  
  subgraph bb1["bb.1 (branch)"]
    branch{"cond?"}
  end
  
  subgraph bb2["bb.2 (KillBB - spill path)"]
    spill["virtual spill point"]
    reload["reload → %y"]
    note2["← reload dominates bb.2's end"]
  end
  
  subgraph bb3["bb.3 (clean path)"]
    clean["... (%x still live)"]
    note3["← no reload, %x unchanged"]
  end
  
  subgraph bb4["bb.4 (PIDF - join)"]
    phi["PHI: incoming from bb.2 = 'use at bb.2 end'<br/>incoming from bb.3 = 'use at bb.3 end'"]
    result["Result: %z = PHI [%y, bb.2], [%x, bb.3]"]
  end
  
  bb0 --> bb1
  bb1 -->|"spill path"| bb2
  bb1 -->|"clean path"| bb3
  bb2 --> bb4
  bb3 --> bb4
```

### Step-by-Step Execution

| Step | Action | PHI State |
|------|--------|-----------|
| 1 | Insert PHI at bb.4 (PIDF) | `%z = PHI [%x, bb.2], [%x, bb.3]` |
| 2 | Insert reload at bb.2 end: `%y = reload` | (unchanged) |
| 3 | `rewriteDominatedUses(%x, %y, mask)` | — |
| 3a | PHI operand from bb.2: "use at bb.2's end" → **dominated by reload** → **rewrite** | `%z = PHI [%y, bb.2], [%x, bb.3]` |
| 3b | PHI operand from bb.3: "use at bb.3's end" → **not dominated** → keep | (no change) |
| 4 | Final result | `%z = PHI [%y, bb.2], [%x, bb.3]` ✓ |

### Why This Is Elegant

We don't explicitly track "spill-path vs clean-path" for each PHI operand. Instead:

1. **All PIDF blocks get PHIs** (because SSA requires it)
2. **All operands start as SpilledReg** (the reaching definition before any reload)
3. **Reloads naturally fix the right operands** via dominance-based use rewriting
4. **Clean-path operands stay unchanged** (no reload dominates them)

This leverages the existing SSA repair machinery rather than building special-case logic.

## Algorithm: `emitReloadsAndRepairSSA()`

```mermaid
flowchart TD
  start["emitReloadsAndRepairSSA(SpillInfo)"] --> getPIDF["PIDF = getPrunedIDF(SpilledReg, KillBB)"]
  getPIDF --> empty{"PIDF empty?"}
  empty -->|Yes| allDom["All uses dominated by KillMI<br/>→ processKillDominatedGroups()"]
  empty -->|No| classify["Classify DomGroups into:<br/>• KillDominated (dominated by KillMI)<br/>• PIdfDominated (dominated by PIDF block)"]
  classify --> phase1["Phase 1: For each PIDF block<br/>processPIdfBlock()"]
  phase1 --> phase2["Phase 2: processKillDominatedGroups()<br/>(reloads auto-rewrite PHI operands)"]
  phase2 --> phase3["Phase 3: finalizeLiveIntervals()"]
  allDom --> phase3
  phase3 --> done["Done"]
```

### Phase 1: `processPIdfBlock()`

For each PIDF block, we process the **group heads** (dominating uses) associated with it.

**Recall**: A group head is the first instruction in a DomGroup that dominates all other uses in the group. One reload before the head covers all uses in the group.

```mermaid
flowchart TD
  start["processPIdfBlock(PIdfBB, Groups)"] --> collectHeads["Collect group heads from Groups"]
  collectHeads --> rpWalk["Walk paths from PIdfBB to each head<br/>Check RP on path to each head"]
  rpWalk --> split["Split groups:<br/>• PhiOK: RP ≤ limit on path to head<br/>• ReloadAtUse: RP > limit on path to head"]
  split --> predCheck{"All spill-path<br/>predecessors<br/>RP ≤ limit?"}
  predCheck -->|No| fallback["Fall back: insertReloadForUse()<br/>for ALL group heads"]
  predCheck -->|Yes| insertPHI["Insert PHI (all operands = SpilledReg)<br/>rewriteDominatedUses(PHIReg)"]
  insertPHI --> reloadBad["insertReloadForUse() for<br/>ReloadAtUse group heads only"]
  fallback --> done["Return nullptr (no PHI)"]
  reloadBad --> returnPHI["Return PHI instruction"]
```

**Predecessor RP check rationale**: A PHI at a PIDF block requires spill-path predecessors to provide the reloaded value. This means a reload must be inserted at each spill-path predecessor's end, adding +1 to live-out RP. If the predecessor is already at the RP limit, we must fall back to reload-at-use.

### Phase 2: `processKillDominatedGroupsWithList()`

```mermaid
flowchart TD
  start["processKillDominatedGroupsWithList(Groups)"] --> collectHeads["Collect group heads from Groups"]
  collectHeads --> optCheck{"Reload optimizer<br/>enabled AND<br/>>1 group head?"}
  optCheck -->|Yes| optimize["optimizeReloadPlacing()<br/>→ clique-based NCD hoisting"]
  optCheck -->|No| individual["Individual reloads per head<br/>+ fixPathologicalPHIs()"]
  optimize --> forEachClique["For each reload point:<br/>getOrCreateReloadInBlock()<br/>repairSSAForReload()"]
  individual --> forEachHead["For each group head:<br/>insertReloadForUse()"]
  forEachClique --> done["Done"]
  forEachHead --> fixPHIs["fixPathologicalPHIs()"]
  fixPHIs --> done
```

## SSA Repair: Two Methods

### `repairSSAForReload()` — For reload IDF PHI insertion

When a new reload is inserted, we call `SSAUpdater->repairSSAForReload(ReloadReg, SpilledReg, Mask, ReloadBB)`:

- Computes IDF of the reload block
- Inserts PHIs at IDF blocks where needed
- Rewrites dominated uses of SpilledReg to ReloadReg
- **Key**: Checks for existing PHIs to avoid duplicates (when reload IDF overlaps with PIDF)

### `rewriteDominatedUses()` — For cached reloads

When reusing a cached reload (already in `BlockReloadCache`), we only call `rewriteDominatedUses()`:

- No new PHIs needed (IDF already processed)
- Just rewrites any remaining uses dominated by the reload

## `fixPathologicalPHIs()` — Handling Asymmetric Use Patterns

### The Problem

The PHI-first strategy relies on `rewriteDominatedUses()` to fix PHI operands from spill-path predecessors. This works when there's a reload that dominates the predecessor's end.

**But what happens when there's a use on the spill path but NO use on the clean path?**

```mermaid
flowchart TD
  subgraph bb0["bb.0"]
    def["def %x"]
  end
  
  subgraph bb1["bb.1 (branch)"]
    branch{"cond?"}
  end
  
  subgraph bb2["bb.2 (KillBB)"]
    use_spill["use %x ← reload inserted here"]
  end
  
  subgraph bb3["bb.3 (clean path)"]
    no_use["NO use of %x"]
    note["← no reload needed!"]
  end
  
  subgraph bb4["bb.4 (PIDF)"]
    phi["PHI [%reload, bb.2], [%x, bb.3]"]
    problem["❌ bb.3 operand still = %x<br/>but %x is dead after KillBB!"]
  end
  
  bb0 --> bb1
  bb1 -->|"spill path"| bb2
  bb1 -->|"clean path"| bb3
  bb2 --> bb4
  bb3 --> bb4
```

### Why This Happens

1. The spill path (bb.2) has a use → reload inserted → `rewriteDominatedUses()` fixes the PHI operand from bb.2
2. The clean path (bb.3) has **no use** → no reload inserted → no `rewriteDominatedUses()` call for bb.3
3. The PHI operand from bb.3 still references the original `%x`, but `%x` is supposed to be dead after KillBB

### The Solution: `fixPathologicalPHIs()`

After individual reloads are placed (when reload optimizer is disabled), we scan for PHIs that:
1. Are dominated by `KillMI` (spill point)
2. Still have operands referencing `SpilledReg`

These are "pathological PHIs" that need direct replacement with a reload:

```cpp
void fixPathologicalPHIs(SpilledVMP, FrameIndex, KillMI) {
  for each PHI using SpilledReg:
    if (DT->dominates(KillMI, PHI)):
      // Replace entire PHI with reload into PHI destination
      Insert: PHIDest = reload(FrameIndex)
      Remove: PHI
}
```

### When Is This Needed?

| Reload Optimizer | Asymmetric Uses | `fixPathologicalPHIs()` Needed? |
|------------------|-----------------|----------------------------------|
| Enabled | Any | No (IDF PHIs handle it) |
| Disabled | Symmetric | No (all paths get reloads) |
| Disabled | Asymmetric (use on spill, none on clean) | Yes |

---

## Reload Optimizer

When enabled (default), the reload optimizer minimizes reload count by hoisting multiple group heads to their Nearest Common Dominator (NCD).

### The Goal

Instead of N reloads (one per group head), place fewer reloads at NCDs that dominate multiple heads.

```mermaid
flowchart TD
  subgraph before["Before Optimization"]
    ncd1["NCD"]
    h1["head1 ← reload"]
    h2["head2 ← reload"]
    h3["head3 ← reload"]
    ncd1 --> h1
    ncd1 --> h2
    ncd1 --> h3
  end
  
  subgraph after["After Optimization"]
    ncd2["NCD ← ONE reload"]
    h1a["head1"]
    h2a["head2"]
    h3a["head3"]
    ncd2 --> h1a
    ncd2 --> h2a
    ncd2 --> h3a
  end
```

### Constraint: RP Must Not Exceed Limit

Hoisting a reload to NCD makes the reloaded value live across ALL paths from NCD to the heads. If any block on these paths has high RP, hoisting would exceed the limit.

### Good Path vs Bad Path

```mermaid
flowchart TD
  subgraph good["Good Path: Can Hoist"]
    ncd_g["NCD (RP=5)"]
    mid_g["intermediate (RP=6)"]
    head_g["head (RP=7)"]
    ncd_g -->|"RP ≤ limit"| mid_g
    mid_g -->|"RP ≤ limit"| head_g
    note_g["✅ All blocks ≤ limit<br/>Safe to hoist reload to NCD"]
  end
  
  subgraph bad["Bad Path: Cannot Hoist"]
    ncd_b["NCD (RP=5)"]
    mid_b["intermediate (RP=12)"]
    head_b["head (RP=7)"]
    ncd_b --> mid_b
    mid_b --> head_b
    note_b["❌ RP=12 > limit=10<br/>Hoisting would make<br/>reloaded value live here"]
  end
```

### Algorithm: `canHoistReloadTo()`

```mermaid
flowchart TD
  start["canHoistReloadTo(NCD, InsertPoint, RPLimit)"] --> checkNCD{"InsertPoint<br/>in NCD?"}
  checkNCD -->|Yes| checkNCDRP["Check RP at InsertPoint"]
  checkNCD -->|No| skipNCD["Skip NCD check"]
  checkNCDRP --> ncdOK{"RP ≤ limit?"}
  ncdOK -->|No| reject["Return false"]
  ncdOK -->|Yes| walkPaths
  skipNCD --> walkPaths["BFS: walk all paths from NCD"]
  walkPaths --> forEachBlock["For each block on path"]
  forEachBlock --> checkRP{"Block RP > limit?"}
  checkRP -->|Yes| reject
  checkRP -->|No| isHead{"Is group head?"}
  isHead -->|Yes| stopPath["Stop this path (use found)"]
  isHead -->|No| continue["Continue to successors"]
  stopPath --> morePaths{"More paths?"}
  continue --> morePaths
  morePaths -->|Yes| forEachBlock
  morePaths -->|No| accept["Return true (all paths OK)"]
```

### Algorithm: `optimizeReloadPlacing()`

Greedy clique-based NCD algorithm:

```mermaid
flowchart TD
  start["optimizeReloadPlacing(GroupHeads)"] --> single{"Single head?"}
  single -->|Yes| trivial["Return [(head.BB, head)]"]
  single -->|No| buildMatrix["Build NCD matrix for all pairs"]
  buildMatrix --> buildAdj["Build adjacency:<br/>edge(i,j) = canHoistReloadTo(NCD(i,j))"]
  buildAdj --> greedy["Greedy clique extraction"]
  
  subgraph clique["Clique Extraction Loop"]
    findSeed["Find unassigned node<br/>with most edges"]
    findSeed --> extend["Try to extend clique:<br/>add nodes connected to ALL members"]
    extend --> computeNCD["Compute NCD for clique"]
    computeNCD --> addResult["Add (CliqueNCD, InsertPoint) to result"]
    addResult --> moreNodes{"Unassigned<br/>nodes remain?"}
    moreNodes -->|Yes| findSeed
  end
  
  greedy --> clique
  moreNodes -->|No| done["Return result"]
```

### Worked Example

Given 4 group heads with this CFG:

```
        bb.0 (NCD of all)
       /    \
    bb.1    bb.2
   /    \      \
 bb.3   bb.4   bb.5
 [h1]   [h2]   [h3,h4]
```

RP analysis:
- Path bb.0 → bb.1 → bb.3: RP OK
- Path bb.0 → bb.1 → bb.4: RP OK  
- Path bb.0 → bb.2 → bb.5: RP **exceeds limit** at bb.2

Result:
- Clique 1: {h1, h2} → reload at bb.1 (their NCD)
- Clique 2: {h3, h4} → reload at bb.5 (can't hoist past bb.2)

## Loop-Aware Spilling

### `adjustReloadForLoop()`

If a reload is inside a loop but the spill point is outside:
- Check if hoisting to loop preheader would exceed RP
- If safe, hoist reload to preheader (one reload vs N iterations)
- If unsafe, keep reload inside loop

### Loop Filtering in `getVMPsToSpill()`

Skip spill candidates that have:
- Definition inside any loop (would require store inside loop)
- Uses inside the same loop as the high-RP point (reload would still be in loop)

## Worked Example: Diamond CFG

### Before spill

```mermaid
flowchart TD
  subgraph b_bb0[bb0]
    b_def["def %x"]
  end

  subgraph b_bb1[bb1]
    b_branch{"cond?"}
  end

  subgraph b_bb2[bb2]
    b_highRP["RP exceeds limit"]
  end

  subgraph b_bb3[bb3]
    b_clean["... (clean path)"]
  end

  subgraph b_bb4[bb4]
    b_join["use %x"]
  end

  b_bb0 --> b_bb1
  b_bb1 -->|"spill path"| b_bb2
  b_bb1 -->|"clean path"| b_bb3
  b_bb2 --> b_bb4
  b_bb3 --> b_bb4
```

### After spill (PHI-first strategy)

```mermaid
flowchart TD
  subgraph a_bb0[bb0]
    a_def["def %x"]
    a_store["store %x → stack"]
  end

  subgraph a_bb1[bb1]
    a_branch{"cond?"}
  end

  subgraph a_bb2[bb2 - KillBB]
    a_kill["virtual spill point"]
    a_reload["%y = reload"]
  end

  subgraph a_bb3[bb3 - clean]
    a_clean["... (%x unchanged)"]
  end

  subgraph a_bb4[bb4 - PIDF]
    a_phi["%z = PHI [%y, bb2], [%x, bb3]"]
    a_use["use %z"]
  end

  a_bb0 --> a_bb1
  a_bb1 -->|"spill path"| a_bb2
  a_bb1 -->|"clean path"| a_bb3
  a_bb2 --> a_bb4
  a_bb3 --> a_bb4
```

## Mapping to tests
See [`SSA_SPILLER_TEST_PATTERNS.md`](../05-Testing/SSA_Spiller/SSA_SPILLER_TEST_PATTERNS.md) for per-test diagrams and marker notes.

Key tests for PHI-first strategy:
- `spill-diamond-phi-merge.mir` - Diamond CFG with PHI merge
- `spill-triangle-phi.mir` - Triangle CFG with pathological PHI (asymmetric uses)
- `spill-reload-opt-basic.mir` - Reload optimizer NCD hoisting

## Appendix A: Historical notes (brief)
- Older materials in [`06-Research/Archive/`](../06-Research/Archive/) may illustrate earlier variants.
- The previous "dominated vs reachable" classification was replaced by "kill-dominated vs PIDF-dominated" in January 2026.

## Appendix B: Source files involved in spill emission

| File | Role |
|------|------|
| `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp` | `getVMPsToSpill`, `spillAtDefinition`, `emitReload`, `countSGPRSpillVGPRs` |
| `llvm/lib/Target/AMDGPU/SIInstrInfo.cpp` | `storeRegToStackSlot` / `loadRegFromStackSlot` — emit `SI_SPILL_*_SAVE/RESTORE` pseudos; SubRegIdx support added 2026-06-11 |
| `llvm/lib/Target/AMDGPU/SIRegisterInfo.cpp` | `eliminateFrameIndex` — lowers VGPR spill pseudos via PEI; `eliminateSGPRToVGPRSpillFrameIndex` — lowers SGPR pseudos (called by `SILowerSGPRSpills`) |
| `llvm/lib/Target/AMDGPU/SILowerSGPRSpills.cpp` | Materialises SGPR spill pseudos to writelane/readlane after SSA RA; runs post-coloring when `SuperReg` is physical |
