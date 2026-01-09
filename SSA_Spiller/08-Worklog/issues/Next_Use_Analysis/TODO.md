# Next Use Analysis - Review Feedback TODOs

From PR [#156079](https://github.com/llvm/llvm-project/pull/156079) review by [@arsenm](https://github.com/arsenm) on Dec 9, 2025.

---

## 1. Rename `VRegMaskPair::getRegClass` method

**Source:** [`VRegMaskPair.h` L75-84](https://github.com/alex-t/llvm-project/blob/3d16512cb05156259f07f8b3d051b72fae6591c8/llvm/lib/Target/AMDGPU/VRegMaskPair.h#L75-L84)

**Review comment:** [#r2600152412](https://github.com/llvm/llvm-project/pull/156079/commits/3ff766e0d85fed5c4dd9e70640cff58a5f6a3ee4#r2600152412)

> `getRegClass` is already an extremely overused and overloaded name.  
> Returning something other than the direct class for VReg is confusing.

**Status:** ⬜ Pending

---

## 2. TRI method change

**Review comment:** [#r2600154501](https://github.com/llvm/llvm-project/pull/156079/commits/3ff766e0d85fed5c4dd9e70640cff58a5f6a3ee4#r2600154501)

> This assumes regs so don't need to use `TRI::getRegClassForReg`

**Status:** ⬜ Pending
