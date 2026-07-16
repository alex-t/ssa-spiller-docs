# SSA Spiller

**SSA-aware spiller operating on AMDGPU Machine IR**

## Source

- **Implementation**: [`AMDGPUSSARegisterSpiller.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp)

---

## Input MIR

**SSA-form Machine IR**
- Single definition per virtual register
- Valid LiveIntervals
- May exceed physical register limits

## Output MIR

**SSA-form Machine IR**
- Register pressure within physical limits
- Spill stores after definitions
- Reload instructions before uses
- SSA form preserved (new PHIs where needed)
- LiveIntervals updated

---

## Strategy

**Two passes** — SGPRs first, then VGPRs. The per-class budget is the
allocatable file size (`getAllocatableSet(...).count()` for `VGPR_32`/`SGPR_32`,
matching what the allocator's `getOrder` can hand out) minus a ~10% safety
margin (`floor(N/10)`). VGPRs consumed by SGPR-spill-to-lane are subtracted from
the VGPR budget between the two passes.

**Belady/MIN victim selection**: `getVMPsToSpill` picks victims by longest
next-use distance, via `sortRegSetByNextUse` querying
[Next_Use_Analysis](Next_Use_Analysis.md)`::getNextUseDistance`.

**Store-at-definition** spill placement:
- Physical store emitted immediately after value definition (EXEC guaranteed full)
- Virtual spill point (KillIdx) marks where register pressure is relieved
- Single physical store per spilled register
- Reloads inserted on-demand, SSA-aware

**Reload placement + inline SSA reconstruction**: reloads are placed in
dominance order on demand, decided against a **frozen deep copy** of the spilled
vreg's `LiveInterval` pruned at the kill point (`pruneValue` is applied to the
copy only — the live `LiveIntervals` is never pruned, so the RP tracker's input
stays intact). A per-edge availability query decides reload vs. merge. Because
each reload redefines the original vreg, SSA is repaired **inline** via
[MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md)`::repairSSAForNewDef` (one call per reload redef), so
the spiller **returns SSA** and no second RebuildSSA pass is needed.

## Core Flow

```
1. processFunction(SGPR) then processFunction(VGPR)  — two backward passes
2. getVMPsToSpill()          — Belady victim selection at the pressure point
3. spillAtDefinition()       — emit single store after def (EXEC full)
4. compute KillIdx           — virtual spill point (prune the frozen copy here)
5. assignVirt2StackSlot()    — allocate stack slot
6. emitReloadsAndRepairSSA() — on-demand reloads + inline SSA repair
```

## Entry Points

| Function | Purpose |
|----------|---------|
| `spillAndReload()` | Main entry: atomic spill+reload+SSA repair |
| `spillAtDefinition()` | Emit store at definition point |
| `emitReloadsAndRepairSSA()` | Insert reloads with dominance grouping |

## Working Features

✅ Two-pass (SGPR then VGPR) with allocatable-file-size budget  
✅ Belady/MIN victim selection via [Next_Use_Analysis](Next_Use_Analysis.md)  
✅ Dominated use grouping (DomGroup class)  
✅ Store-at-definition  
✅ Reload placement against a frozen, kill-pruned interval copy  
✅ LiveInterval kept valid through reload placement  
✅ Single-store design  
✅ Subregister handling via VRegMaskPair  
✅ Reachability filtering via `isUseReachableFromDef` (plain CFG BFS)  
✅ Inline SSA repair via [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) (spiller returns SSA)

## Pending

⚠️ Loop-aware spilling; spiller tied-operand RP fix

> Notes:
> - The old dominance-frontier **reload optimizer was removed**. A dead flag
>   `-amdgpu-ssa-spill-no-reload-opt` (`DisableReloadOptimizer`) remains declared
>   but is unreferenced.
> - `SI_VIRTUAL_SPILL_MARKER` still exists but is **test-only** (flag
>   `-amdgpu-ssa-spill-markers`, default off) with no logic consumer.

> Note: "split-before-use vs balanced spill" was part of the **old** spill-placement
> design, rejected in favor of store-at-definition + virtual spill point. Balanced
> spilling is obsolete and will not be implemented (see
> `06-Research/Archive/Old_Spill_Placement_Design.md`).

## Rationale

Store-at-definition eliminates EXEC drift issues in divergent control flow. See [Design Decisions](../04-Design/Decisions.md) for details.

## Related

- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) — SSA repair utility
- [Next_Use_Analysis](Next_Use_Analysis.md) — spill candidate selection
- [MIN Algorithm](../03-Concepts/MIN_Algorithm.md) — theoretical basis
- [Detailed Design](../04-Design/SSA_SPILLER_DESIGN.md)
