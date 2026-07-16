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
| **Lane-aware PHI insertion** | Places PHIs exactly at the PHI-def `VNInfo`s already present in the frozen interval (the pruned IDF that `LiveIntervalCalc` materialized) — no IDF is recomputed |
| **Reaching-VNI resolution** | PHI operands and uses are resolved by the reaching `VNInfo` read from a frozen deep copy of the original interval, not by dominance/order |
| **Subregister handling** | Works with `(VReg, LaneBitmask)` pairs, not just whole registers |
| **LiveIntervals integration** | Updates live ranges and subranges precisely |
| **Use rewriting** | Handles exact, subset, and superset lane matches; shares one `REG_SEQUENCE` across duplicate super-use operands of the same instruction |

## Primary API

```cpp
// Repair SSA after inserting a new definition of OrigVReg
Register repairSSAForNewDef(MachineInstr &NewDefMI,
                            Register OrigVReg,
                            SmallVectorImpl<MachineOperand*> &PHIRegDefOps);

// Reset the per-OrigVReg session so the next repair re-freezes the interval
// (needed when defs are added incrementally between repair calls).
void resetSession();

// Check if a use is reachable from a definition in the CFG. Because OrigVReg
// is SSA the value is live along every def->use path, so plain CFG
// reachability is exact — no dominance-frontier needed.
bool isUseReachableFromDef(MachineInstr *DefMI, MachineInstr *UseMI,
                           Register OrigVReg);
```

## Primary Client

**AMDGPU SSA Spiller** — calls `repairSSAForNewDef` (once per reload redef) after
emitting reload instructions to restore SSA form inline, and `isUseReachableFromDef`
to decide which uses a spill affects. The [[SSA_Rebuilder]] also uses
`repairSSAForNewDef` to split multi-def vregs during SSA reconstruction.

## Detailed Design

See [MachineLaneSSAUpdater Design](../04-Design/MachineLaneSSAUpdater.md) for:
- Core algorithm walkthrough
- Reaching-VNI PHI placement (from the frozen interval; no IDF recompute)
- LiveInterval handling details
- Integration with SSA Spiller

> Note: no iterated-dominance-frontier (IDF) code remains in the updater. Some
> stale in-code comments still say "pruned IDF computation"; the VNInfo-based
> placement described above is the truth.
