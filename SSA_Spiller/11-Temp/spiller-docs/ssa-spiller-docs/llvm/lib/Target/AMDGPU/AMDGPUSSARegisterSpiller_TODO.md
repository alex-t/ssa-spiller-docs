# AMDGPUSSARegisterSpiller - Implementation Plan

## Overview

This is a clean-room SSA-aware register spiller implementation for AMDGPU, based on the Braun & Hack paper approach. It uses `MachineLaneSSAUpdater` to maintain SSA form during spilling/reloading.

## Files

- **AMDGPUSSARegisterSpiller.h**: Header with class definition and method declarations
- **AMDGPUSSARegisterSpiller.cpp**: Implementation with skeleton framework
- **AMDGPUEarlyRegisterSpilling.{h,cpp}.bak**: Reference implementation (renamed to avoid CMake conflicts)
- **VRegMaskPair.h**: Data structures for tracking registers with lane masks (already exists)
- **AMDGPUNextUseAnalysis.{h,cpp}**: Next-use distance analysis (already exists)

## Current State

### ✅ Completed
1. **Basic Structure**: Pass skeleton with proper LLVM pass infrastructure
2. **RPO Traversal**: Reverse post-order traversal of basic blocks
3. **Bottom-up Walk**: Reverse instruction iteration per block
4. **Spill Method**: Core `spill()` method based on `limit()` from reference implementation
   - Dead register removal
   - Register pressure calculation using 32-bit granularity
   - Next-use distance sorting
   - Greedy candidate selection
   - Subregister splitting logic (placeholder)
5. **Helper Methods**: Stack slot management, debug output, size calculation
6. **CMake Integration**: Added to CMakeLists.txt

### 🚧 TODOs - Ordered by Priority

#### 1. Register Pressure Tracking Integration
**Location**: `runOnMachineFunction()` - main loop

**Tasks**:
- [ ] Initialize `GCNDownwardRPTracker` for each block
- [ ] Advance tracker per instruction: `RPTracker.advance(MI)`
- [ ] Get live registers: `VRegMaskPairSet LiveRegs = RPTracker.getLiveRegs()`
- [ ] Calculate VGPR/SGPR pressure from LiveRegs
- [ ] Filter LiveRegs by register class (VGPR vs SGPR)
- [ ] Pass correct `ActiveSet` to `spill()` method

**Reference**: See `GCNRegPressure.cpp` and `GCNDownwardRPTracker` usage patterns

#### 2. Next-Use Analysis Integration
**Location**: `sortRegSetByNextUse()` and `isDead()`

**Tasks**:
- [ ] Initialize NUA: `NUA.analyze(MF)` in `runOnMachineFunction()`
- [ ] Implement `isDead()`: call `NUA.isDead(MBB, I, VMP)`
- [ ] Implement `sortRegSetByNextUse()`: use `NUA.getNextUseDistance(I, VMP)` for sorting
- [ ] Handle special cases: loop-carried distances, infinity for dead registers

**Reference**: See `AMDGPUNextUseAnalysis.h` for API

#### 3. Subregister Splitting in spill()
**Location**: `spill()` method - "too large candidate" branch

**Tasks**:
- [ ] Query NUA for sorted subregister uses: `NUA.getSortedSubregUses(I, Candidate)`
- [ ] Select subregisters with longest next-use distance
- [ ] Create `VRegMaskPair` for each selected subregister
- [ ] Update `RemainingToSpill` and `Active` set accordingly
- [ ] Insert partial spills into `ToSpill` set

**Reference**: See `limit()` method in `AMDGPUEarlyRegisterSpilling.cpp.bak` (lines ~400-450)

#### 4. Spill Instruction Emission
**Location**: `spillBefore()` method

**Tasks**:
- [ ] Get stack slot: `int FI = assignVirt2StackSlot(VMP)`
- [ ] Get register class: `const TargetRegisterClass *RC = VMP.getRegClass(MRI, TRI)`
- [ ] Determine appropriate `SI_SPILL_*` opcode based on RC size
- [ ] Build spill instruction: `TII->storeRegToStackSlot(MBB, I, VMP.getVReg(), true, FI, RC, TRI, VMP.getSubReg(MRI, TRI))`
- [ ] Update `SlotIndexes`: `Indexes->insertMachineInstrInMaps(*SpillMI)`
- [ ] Update `LiveIntervals`: handle def/use updates
- [ ] Increment `NumSpills` statistic
- [ ] Track spilled register for reload phase

**Reference**: See spill emission in reference implementation

#### 5. Reload Instruction Emission and SSA Repair
**Location**: `reloadBefore()` method

**Tasks**:
- [ ] Get stack slot: `int FI = assignVirt2StackSlot(VMP)`
- [ ] Create new virtual register: `Register NewVReg = MRI->createVirtualRegister(RC)`
- [ ] Emit reload instruction: `TII->loadRegFromStackSlot(MBB, I, NewVReg, FI, RC, TRI, SubReg)`
- [ ] Update `SlotIndexes` and `LiveIntervals`
- [ ] **SSA Repair using MachineLaneSSAUpdater**:
  ```cpp
  MachineLaneSSAUpdater SSAUpdater(*MF, DT, LIS);
  SSAUpdater.repairSSAForNewDef(OrigVReg, NewVReg, ReloadMI, 
                                VMP.getLaneMask(), *MRI, *TRI);
  ```
- [ ] Increment `NumReloads` statistic

**Reference**: See `MachineLaneSSAUpdater::repairSSAForNewDef()` in `MachineLaneSSAUpdater.h`

#### 6. Reload Insertion Logic
**Location**: New method to be added or integrated into `runOnMachineFunction()`

**Tasks**:
- [ ] Track which registers were spilled and where
- [ ] For each spilled register, find all dominated uses
- [ ] Determine optimal reload insertion points
- [ ] Insert reloads and repair SSA (call `reloadBefore()`)
- [ ] Handle PHI nodes in merge blocks if needed

**Reference**: See `emitRestores()` in `AMDGPUEarlyRegisterSpilling.cpp.bak`

#### 7. Register Pressure Limits
**Location**: `runOnMachineFunction()` - initialization

**Tasks**:
- [ ] Query target-specific VGPR limit from subtarget or function attributes
- [ ] Query target-specific SGPR limit from subtarget or function attributes
- [ ] Support command-line overrides for testing
- [ ] Account for reserved registers

**Reference**: See `MaxVGPRs` and `MaxSGPRs` calculation in reference implementation

#### 8. Loop Handling
**Location**: To be determined - may need additional methods

**Tasks**:
- [ ] Use `MachineLoopInfo` to detect loop headers and exits
- [ ] Apply different spill strategies for loop-carried values
- [ ] Consider loop depth in spill candidate selection
- [ ] Handle loop live-ins specially

**Reference**: See `getLoopMaxRP()` in reference implementation

#### 9. Verification and Testing
**Location**: Unit tests and integration tests

**Tasks**:
- [ ] Add unit tests similar to `MachineLaneSSAUpdaterTest.cpp`
- [ ] Test simple linear spill/reload
- [ ] Test diamond CFG with spills
- [ ] Test loop scenarios
- [ ] Test subregister spilling
- [ ] Verify SSA form maintained after each test
- [ ] Run on real AMDGPU code and verify correctness

#### 10. Performance and Optimization
**Location**: Various

**Tasks**:
- [ ] Profile spiller performance on large functions
- [ ] Optimize VRegMaskPairSet operations
- [ ] Cache next-use distances if needed
- [ ] Implement spill code placement optimizations
- [ ] Add statistics for spill analysis

## Key Concepts from Reference Implementation

### 1. Spill Size Calculation (32-bit granularity)
```cpp
unsigned VRegMaskPair::getSizeInRegs(const SIRegisterInfo *TRI) const {
  return TRI->getNumCoveredRegs(LaneMask);
}
```
- VGPR_32: 1 unit
- VReg_64: 2 units
- VReg_128: 4 units
- Allows fine-grained pressure management

### 2. VRegMaskPairSet Usage
- Efficiently tracks sets of (VReg, LaneMask) pairs
- Supports set operations with lane coverage logic
- Linear storage maintains insertion order for sorting
- Set storage enables fast lookup

### 3. limit() Algorithm (adapted as spill())
```
1. Remove dead registers from Active
2. If pressure <= limit, return
3. Sort Active by next-use distance (longest last)
4. While pressure > limit:
   a. Pop candidate from back
   b. If candidate too large, split by subregisters
   c. Otherwise, add to spill set
5. Emit spills for selected registers
```

## Integration with MachineLaneSSAUpdater

The key innovation in this spiller is the use of `MachineLaneSSAUpdater` for SSA repair:

```cpp
// After inserting a reload:
MachineLaneSSAUpdater SSAUpdater(*MF, DT, LIS);
SSAUpdater.repairSSAForNewDef(
  OrigVReg,           // Original spilled register
  ReloadVReg,         // New register from reload
  ReloadMI,           // Reload instruction
  LaneMask,           // Lanes being reloaded
  *MRI, *TRI
);
```

This automatically:
- Rewrites dominated uses to the new register
- Inserts PHI nodes at merge points
- Handles subregister remapping
- Maintains LiveIntervals

## Development Workflow

1. **Phase 1**: Register Pressure Integration (TODO #1)
   - Get actual live registers and pressure values
   - Verify spill candidates are correctly identified

2. **Phase 2**: Next-Use Analysis (TODO #2)
   - Get accurate next-use distances
   - Verify correct candidate selection

3. **Phase 3**: Basic Spill/Reload (TODOs #4, #5)
   - Emit actual spill/reload instructions
   - Test on simple linear code

4. **Phase 4**: SSA Repair (TODO #5 continued)
   - Integrate MachineLaneSSAUpdater
   - Test on diamond and loop CFGs

5. **Phase 5**: Optimization (TODOs #3, #6-10)
   - Subregister splitting
   - Loop handling
   - Performance tuning

## Notes

- The reference implementation is preserved as `.bak` files for consultation
- All debug output uses `LLVM_DEBUG(dbgs() << ...)` for conditional compilation
- Statistics track spills/reloads for performance analysis
- The spiller maintains MachineFunction properties (IsSSA, NoPHIs reset after PHI insertion)

