1. ### Rename VRegMaskPair::getRegClas method

llvm/lib/Target/AMDGPU/VRegMaskPair.h#line:68
arsenm](https://github.com/arsenm)**[on Dec 9, 2025](https://github.com/llvm/llvm-project/pull/156079/commits/3ff766e0d85fed5c4dd9e70640cff58a5f6a3ee4#r2600152412)

getRegClass is already an extremely overused and overloaded name.  
Returning something other than the direct class for VReg is confusing

2. ### TRI method change

**[  
arsenm](https://github.com/arsenm)**[on Dec 9, 2025](https://github.com/llvm/llvm-project/pull/156079/commits/3ff766e0d85fed5c4dd9e70640cff58a5f6a3ee4#r2600154501)

This assumes regs so don't need to use TRI::getRegClassForReg