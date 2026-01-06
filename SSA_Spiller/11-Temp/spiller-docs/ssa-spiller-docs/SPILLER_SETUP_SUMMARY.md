# AMDGPUSSARegisterSpiller - Setup Summary

## ✅ Completed Setup

### 1. Reference Implementation Preserved
- `AMDGPUEarlyRegisterSpilling.h` → `AMDGPUEarlyRegisterSpilling.h.bak`
- `AMDGPUEarlyRegisterSpilling.cpp` → `AMDGPUEarlyRegisterSpilling.cpp.bak`
- Files renamed to avoid CMake conflicts while keeping them as reference

### 2. New Spiller Skeleton Created
**Files created:**
- `AMDGPUSSARegisterSpiller.h` (136 lines)
- `AMDGPUSSARegisterSpiller.cpp` (332 lines)
- `AMDGPUSSARegisterSpiller_TODO.md` (239 lines - detailed implementation plan)

**Build integration:**
- Added to `CMakeLists.txt`
- Added pass initialization declaration in `AMDGPU.h`
- ✅ Compiles successfully

### 3. Core Structure Implemented

#### Pass Infrastructure
```cpp
class AMDGPUSSARegisterSpiller : public MachineFunctionPass {
  // Dependencies: TRI, TII, MRI, LIS, DT, MLI, etc.
  // Stack slot management: Virt2StackSlotMap
};
```

#### Main Algorithm Flow
```
runOnMachineFunction():
  ├─ Initialize pass dependencies
  ├─ Traverse blocks in RPO
  │   └─ For each block:
  │       ├─ TODO: Initialize GCNDownwardRPTracker
  │       └─ For each instruction:
  │           ├─ TODO: Track register pressure
  │           ├─ If VGPR pressure >= limit:
  │           │   └─ Call spill() method
  │           └─ If SGPR pressure >= limit:
  │               └─ Call spill() method
  └─ TODO: Insert reloads and repair SSA
```

#### Spill Method (based on limit() from reference)
```cpp
unsigned spill(MBB, I, Active, Spilled, SizeToSpill) {
  1. Remove dead registers from Active
  2. Calculate current RP (32-bit granularity)
  3. Return early if RP <= limit
  4. Sort Active by next-use distance
  5. Greedily select candidates:
     - If candidate too large: TODO split by subregs
     - Otherwise: add to spill set
  6. Emit spills via spillBefore()
}
```

#### Key Borrowed Concepts
1. **32-bit Spill Size Calculation**
   ```cpp
   VRegMaskPair::getSizeInRegs(TRI) {
     return TRI->getNumCoveredRegs(LaneMask);
   }
   ```
   - VGPR_32: 1 unit
   - VReg_64: 2 units  
   - VReg_128: 4 units

2. **VRegMaskPairSet Usage**
   - Efficient (VReg, LaneMask) pair tracking
   - Set operations with lane coverage logic
   - Sorting by next-use distance

3. **Next-Use Distance Sorting**
   - Longest distance → spill first
   - Integrated with AMDGPUNextUseAnalysis

### 4. Placeholder Methods with TODOs

All methods have clear TODO comments indicating what needs to be implemented:

| Method | Status | Priority |
|--------|--------|----------|
| `spill()` | ✅ Skeleton complete | Core logic done |
| `spillBefore()` | 📝 TODO | High - emit actual spills |
| `reloadBefore()` | 📝 TODO | High - emit reloads + SSA repair |
| `sortRegSetByNextUse()` | 📝 TODO | Medium - integrate NUA |
| `isDead()` | 📝 TODO | Medium - integrate NUA |
| `getRegSetSizeInRegs()` | ✅ Complete | Done |
| `assignVirt2StackSlot()` | ✅ Complete | Done |
| `createSpillSlot()` | ✅ Complete | Done |

## 📋 Next Steps (See AMDGPUSSARegisterSpiller_TODO.md)

### Immediate Priorities:
1. **Register Pressure Tracking** - Integrate GCNDownwardRPTracker
2. **Next-Use Analysis** - Integrate AMDGPUNextUseAnalysis  
3. **Spill Emission** - Implement spillBefore() with SI_SPILL_* opcodes
4. **Reload + SSA Repair** - Implement reloadBefore() with MachineLaneSSAUpdater

### MachineLaneSSAUpdater Integration
The key innovation is SSA repair after reloads:
```cpp
void reloadBefore(MBB, I, VMP) {
  // 1. Create new vreg and emit reload
  Register NewVReg = MRI->createVirtualRegister(RC);
  TII->loadRegFromStackSlot(...);
  
  // 2. Repair SSA using MachineLaneSSAUpdater
  MachineLaneSSAUpdater SSAUpdater(*MF, DT, LIS);
  SSAUpdater.repairSSAForNewDef(
    VMP.getVReg(),        // Original spilled register
    NewVReg,              // New reload register
    ReloadMI,             // Reload instruction
    VMP.getLaneMask(),    // Lanes being reloaded
    *MRI, *TRI
  );
  // This automatically:
  // - Rewrites dominated uses
  // - Inserts PHIs at merge points
  // - Handles subregister remapping
  // - Maintains LiveIntervals
}
```

## 📁 File Organization

```
llvm/lib/Target/AMDGPU/
├── AMDGPUSSARegisterSpiller.h           # New spiller header
├── AMDGPUSSARegisterSpiller.cpp         # New spiller implementation
├── AMDGPUSSARegisterSpiller_TODO.md     # Detailed implementation plan
├── AMDGPUEarlyRegisterSpilling.h.bak    # Reference implementation
├── AMDGPUEarlyRegisterSpilling.cpp.bak  # Reference implementation
├── VRegMaskPair.h                       # Data structures (existing)
├── AMDGPUNextUseAnalysis.{h,cpp}        # NUA (existing)
└── GCNRegPressure.{h,cpp}               # RPTracker (existing)

llvm/lib/CodeGen/
└── MachineLaneSSAUpdater.{h,cpp}        # SSA repair utility (existing)
```

## 🎯 Design Goals

1. **Clean-room implementation** based on Braun & Hack paper
2. **Lane-aware SSA repair** using MachineLaneSSAUpdater
3. **32-bit register granularity** for precise spill decisions
4. **Incremental development** with clear TODOs for each step
5. **Reference preservation** - .bak files available for consultation

## 🔧 Build Status

✅ All files compile successfully  
✅ Integrated into CMake build system  
✅ Pass infrastructure initialized  
✅ Ready for incremental implementation  

## 📖 Documentation

- **AMDGPUSSARegisterSpiller_TODO.md**: Comprehensive implementation plan with 10 prioritized TODOs
- **Code comments**: Extensive TODO comments throughout the skeleton
- **Reference implementation**: Available in .bak files for algorithm consultation

---

**Ready for incremental development!** Start with TODO #1 (Register Pressure Tracking) in the TODO.md file.

