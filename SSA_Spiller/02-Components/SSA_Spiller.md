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

**Store-at-definition** spill placement:
- Physical store emitted immediately after value definition (EXEC guaranteed full)
- Virtual spill point (KillIdx) marks where register pressure is relieved
- Single physical store per spilled register
- Reloads inserted on-demand, SSA-aware

## Core Flow

```
1. spillAtDefinition()      — emit store after def
2. compute KillIdx          — virtual spill point
3. assignVirt2StackSlot()   — allocate stack slot
4. emitReloadsAndRepairSSA() — insert reloads, repair SSA
5. shrinkToUses()           — update LiveIntervals
```

## Entry Points

| Function | Purpose |
|----------|---------|
| `spillAndReload()` | Main entry: atomic spill+reload+SSA repair |
| `spillAtDefinition()` | Emit store at definition point |
| `emitReloadsAndRepairSSA()` | Insert reloads with dominance grouping |

## Working Features

✅ Dominated use grouping (DomGroup class)  
✅ Store-at-definition  
✅ LiveInterval kept valid through reload placement  
✅ Single-store design  
✅ Subregister handling via VRegMaskPair  
✅ Reachability filtering via `isUseReachableFromDef`  
✅ SSA repair via [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md)

## Pending

⚠️ Cost model for split vs balanced spill decisions

## Rationale

Store-at-definition eliminates EXEC drift issues in divergent control flow. See [Design Decisions](../04-Design/Decisions.md) for details.

## Related

- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md) — SSA repair utility
- [Next_Use_Analysis](Next_Use_Analysis.md) — spill candidate selection
- [MIN Algorithm](../03-Concepts/MIN_Algorithm.md) — theoretical basis
- [Detailed Design](../04-Design/SSA_SPILLER_DESIGN.md)
