# AMDGPUSSARegisterSpiller Redesign

## Critical Issues Identified

### 1. Invalid MIR State Between Spill and Reload
**Problem**: If we spill all registers first and then reload later:
- Trimmed LiveIntervals make uses invalid
- Register pressure tracking becomes impossible
- MachineVerifier will fail

**Solution**: Atomic spill+reload+SSA repair per register (like colleague's code at line 813 of AMDGPUEarlyRegisterSpilling.cpp.bak)

### 2. MachineLaneSSAUpdater Interface Mismatch
**Problem**: Our reload implementation was creating a new VReg, but MachineLaneSSAUpdater expects:
```cpp
Register repairSSAForNewDef(MachineInstr &NewDefMI, Register OrigVReg);
```

**How it works**:
1. Emit reload instruction that defines OrigVReg (violating SSA)
2. Call `repairSSAForNewDef(ReloadMI, OrigVReg)`
3. Updater creates new VReg internally
4. Updater replaces def operand
5. Updater inserts PHIs and rewrites uses
6. Updater trims/recomputes LiveIntervals (MachineLaneSSAUpdater.cpp:179-184)

**Solution**: 
- `spillBefore()` should NOT trim LiveIntervals
- `reloadBefore()` should emit reload defining OrigVReg
- Let MachineLaneSSAUpdater handle everything

### 3. Optimal Spill/Reload Placement
**Problem**: We need sophisticated placement logic considering:
- Loop structures (spill in loop exit/preheader)
- Dominance relationships (group reloads by dominance)
- Control flow (IDF for PHI insertion)

**Solution**: Adapt colleague's placement logic from AMDGPUEarlyRegisterSpilling.cpp.bak

## New Workflow Design

### High-Level Algorithm (processFunction)
```
for each basic block in RPO:
    Initialize GCNUpwardRPTracker
    for each instruction (backward traversal):
        RPTracker.recede(MI)
        if CurRP > RPLimit:
            spillAndReload(MI, RPTracker, CurRP, RPLimit, IsVGPR)
            // After each spill+reload, reset tracker
            RPTracker.reset(MI)
```

### Per-Register Atomic Workflow (spillAndReload)
```
1. Select registers to spill using getVMPsToSpill():
   - Uses Belady's algorithm (longest next-use distance first)
   - Splits by subregisters if needed
   - Returns VRegMaskPairSet of selected VMPs

2. For each selected VMP:
   a. Emit spill instruction:
      spillBefore(MBB, I, VMP)
      - Uses SubRegIdx for partial spills
      - Updates SlotIndexes
      - Does NOT trim LiveIntervals

   b. Call emitReloadsAndRepairSSA():
      - Find uses dominated by spill
      - Group dominated uses by dominance chains (DomGroup)
      - Emit ONE reload per group (at group head)
      - Call MachineLaneSSAUpdater::repairSSAForNewDef()
        → Automatically handles:
          * Non-dominated uses
          * PHI insertion (using IDF internally)
          * Use rewriting
          * LiveInterval updates

3. Return to processFunction
```

**Key Simplification:** We only optimize placement for dominated uses.
MachineLaneSSAUpdater automatically handles all SSA repair including PHI
insertion, so we don't need to manually compute IDF or classify reachable uses.

### Key Data Structures
```cpp
// Per basic block during backward traversal:
VRegMaskPairSet Spilled;  // Track what's been spilled in this block

// Per spilled register:
int FrameIndex;  // Stack slot (from Virt2StackSlotMap)
MachineInstr *SpillMI;  // The spill instruction
SmallVector<MachineInstr*> DominatedUses;
SmallVector<MachineInstr*> ReachableUses;
SmallVector<DomGroup> Groups;  // Dominance-based grouping
```

### Dominance Grouping (from colleague's code)
```cpp
class DomGroup {
    SmallVector<MachineInstr*> Uses;
    bool Deleted = false;
public:
    MachineInstr *getHead() const { return Uses.front(); }
    void merge(DomGroup &Other) {
        for (auto *MI : Other.Uses) Uses.push_back(MI);
        Other.Deleted = true;
    }
};

// Algorithm:
for each Use1:
    Create Group(Use1)
    for each Use2:
        if DT->dominates(Use1, Use2):
            Group(Use1).merge(Group(Use2))

// Result: One reload per group at the head
```

## Implementation Status

### ✅ Completed
- [x] `spillBefore()` - emits spill without trimming LI
- [x] `reloadBefore()` - emits reload + calls MachineLaneSSAUpdater
- [x] Helper methods: `spillAtEnd()`, `reloadAtEnd()`
- [x] `VRegMaskPair` infrastructure
- [x] Lane-aware pressure tracking conversion

### 🚧 In Progress
- [ ] `spillAndReload()` - main atomic spill+reload method
- [ ] Optimal spill placement logic (loop-aware)
- [ ] `emitReloadsAndRepairSSA()` - dominance grouping + IDF
- [ ] Integration with `MachineLaneSSAUpdater`

### ❌ TODO
- [ ] `DomGroup` helper class
- [ ] Reachability analysis integration
- [ ] RPTracker reset after modifications
- [ ] Register pressure limit calculation
- [ ] MIR tests

## References
- Colleague's implementation: `llvm/lib/Target/AMDGPU/AMDGPUEarlyRegisterSpilling.cpp.bak`
  - Lines 708-819: `spill()` method with optimal placement
  - Lines 524-707: `emitRestores()` method with dominance grouping + IDF
  - Lines 289-431: `emitRestoreInstrsForDominatedUses()`
- MachineLaneSSAUpdater: `llvm/include/llvm/CodeGen/MachineLaneSSAUpdater.h`
  - Line 65: `repairSSAForNewDef()` interface
  - `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp:179-184`: LiveInterval cleanup

## Next Steps
1. Implement `spillAndReload()` with optimal placement
2. Implement `emitReloadsAndRepairSSA()` with dominance grouping
3. Test on simple MIR examples
4. Verify with MachineVerifier
5. Run full test suite

