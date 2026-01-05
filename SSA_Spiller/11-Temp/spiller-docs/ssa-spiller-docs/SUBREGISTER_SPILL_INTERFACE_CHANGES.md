# Subregister Spilling Interface Changes

## Overview
Added support for spilling subregisters by extending the `TargetInstrInfo::storeRegToStackSlot` interface with an optional `SubRegIdx` parameter.

## Changes Made

### 1. Base Interface (TargetInstrInfo.h)
```cpp
virtual void storeRegToStackSlot(
    MachineBasicBlock &MBB, MachineBasicBlock::iterator MI, Register SrcReg,
    bool isKill, int FrameIndex, const TargetRegisterClass *RC,
    const TargetRegisterInfo *TRI, Register VReg,
    MachineInstr::MIFlag Flags = MachineInstr::NoFlags,
    unsigned SubRegIdx = 0) const;  // <-- Added parameter with default value
```

### 2. AMDGPU Implementation

#### SIInstrInfo.h
```cpp
void storeRegToStackSlot(..., unsigned SubRegIdx = 0) const override;
```

#### SIInstrInfo.cpp
- Updated function signature to accept `SubRegIdx`
- Modified VGPR spill instruction building to use the subregister:
```cpp
BuildMI(MBB, MI, DL, get(Opcode))
  .addReg(SrcReg, getKillRegState(isKill), SubRegIdx) // <-- Uses SubRegIdx
  .addFrameIndex(FrameIndex)
  .addReg(MFI->getStackPtrOffsetReg())
  .addImm(0)
  .addMemOperand(MMO);
```

### 3. X86 Implementation

#### X86InstrInfo.h
```cpp
void storeRegToStackSlot(..., unsigned SubRegIdx = 0) const override;
```

#### X86InstrInfo.cpp
- Updated function signature to accept `SubRegIdx`
- Parameter added for interface compatibility (X86 implementation may use it in the future)

## Usage Example

When spilling a subregister (e.g., `sub0` of a 128-bit register):

```cpp
// Get the subregister index from the lane mask
unsigned SubRegIdx = getSubRegIndexForLaneMask(VMP.getLaneMask(), TRI);

// Spill only that subregister
TII->storeRegToStackSlot(MBB, MI, VMP.getVReg(), /*isKill=*/false, 
                         FrameIndex, RC, TRI, VReg, 
                         MachineInstr::NoFlags, SubRegIdx);
```

## Benefits

1. **Fine-grained Spilling**: Can now spill individual lanes/subregisters instead of entire registers
2. **Reduced Memory Traffic**: Spilling only what's needed reduces memory bandwidth
3. **Better Register Pressure Management**: Enables more granular control in register allocation
4. **Lane-Aware Spilling**: Works seamlessly with `MachineLaneSSAUpdater` for subregister SSA repair

## Compatibility

- The default parameter value of `0` ensures backward compatibility
- Targets that don't override the method will continue to work unchanged
- Targets can adopt subregister spilling incrementally


