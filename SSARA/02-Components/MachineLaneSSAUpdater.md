# MachineLaneSSAUpdater

**Lane-aware SSA repair utility for LLVM Machine IR**

## Source

- **Header**: [`llvm/include/llvm/CodeGen/MachineLaneSSAUpdater.h`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/include/llvm/CodeGen/MachineLaneSSAUpdater.h)
- **Implementation**: [`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp)
- **Upstream PR**: [#163421](https://github.com/llvm/llvm-project/pull/163421)

## Purpose

Repairs SSA form when a transformation (e.g., reload insertion) creates an illegal redefinition of an existing virtual register. Unlike `MachineSSAUpdater`, this utility is **lane-aware**—it correctly handles subregisters and partial definitions common in AMDGPU.

## Key Capabilities

| Feature | Description |
|---------|-------------|
| **Lane-aware PHI insertion** | Inserts PHIs only for affected lanes using pruned IDF |
| **Subregister handling** | Works with `(VReg, LaneBitmask)` pairs, not just whole registers |
| **LiveIntervals integration** | Updates live ranges and subranges precisely |
| **Use rewriting** | Handles exact, subset, and superset lane matches |

## Primary API

```cpp
// Repair SSA after inserting a new definition of OrigVReg
Register repairSSAForNewDef(MachineInstr &NewDefMI,
                            Register OrigVReg,
                            SmallVectorImpl<MachineOperand*> &PHIRegDefOps);

// Check if a use is reachable from a definition (via pruned IDF)
bool isUseReachableFromDef(MachineInstr *DefMI, MachineInstr *UseMI,
                           Register OrigVReg, LaneBitmask DefMask);
```

## Primary Client

**AMDGPU SSA Spiller** — calls `repairSSAForNewDef` after emitting reload instructions to restore SSA form.

## Detailed Design

See [MachineLaneSSAUpdater Design](../04-Design/MachineLaneSSAUpdater.md) for:
- Core algorithm walkthrough
- PHI placement and IDF caching
- LiveInterval handling details
- Integration with SSA Spiller
