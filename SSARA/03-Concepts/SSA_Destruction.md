# §4.2 SSA-Destruction

Source:
Register Allocation for Programs in SSA-Form  
Hack, Grund, Goos  
Section 4.2

PDF:
[Register Allocation for Programs in SSA-Form](../06-Research/Papers/ssara.pdf)

---

## Summary

This section explains why φ-elimination by inserting naive copies is incorrect and may increase register pressure.

Key idea:
> φ-functions are NOT copies. They represent **register permutations** at block boundaries.

A φ-block behaves as:
- a *simultaneous assignment*
- equivalent to a register permutation (possibly a swap)
- not sequential copy insertion

---

## The core problem

If φ is lowered as sequential copies, you may introduce new interferences that did not exist in SSA.

Example from the paper:
Naively inserting:


i3 ← i2
j3 ← j2

creates a new interference edge that forces:
clique size = 3

instead of 2 → **register pressure increases artificially**.

---

## Correct lowering strategy

Interpret φ as permutations:

If registers are:

R1 holds i1
R2 holds j1

Then φ:

i3 = φ(i1, i2)
j3 = φ(j1, j2)

means:

On some edge:
R1 ↔ R2

i.e. **swap registers**, not copy values.

---

## Implementation options

If ISA supports swap:
✅ emit swap instructions

Otherwise:
✅ lower permutations via temporary or XOR-based swap

---

## Important consequence

SSA destruction is *not*:
- move insertion
- explicit copying

SSA destruction is:
✅ register permutation synthesis

---

## Implementation status

SSA destruction **is implemented** and runs inside the SSA register allocator —
`AMDGPUSSARegisterAllocator::destroySSAAndRewrite()`
(`llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp`). After coloring, it
performs, in order:

1. `lowerPHIs()` — lowers φ-blocks as parallel register assignments.
2. `resolvePermutation()` — realizes each block boundary as a permutation, not
   sequential copies, breaking cycles with the three-tier strategy below.
3. `eliminateRegSequences()` — lowers `REG_SEQUENCE` pseudos (also routed
   through `resolvePermutation`, since a `REG_SEQUENCE` is itself a parallel
   assignment).
4. `addPhysRegLiveIns()` — records physreg live-ins.
5. `MRI->leaveSSA()` — drops the SSA property.

The whole step is **skipped** when the function still contains SI control-flow
pseudos (`hasCFPseudos()` returns true).

Cycle breaking in `resolvePermutation` matches the paper's permutation view with
three tiers: (1) a scratch register when occupancy is preserved, (2) per-subreg
`V_SWAP_B32` on GFX9+, and (3) an XOR triplet as the last resort.

---
## References

Paper citation:
Hack, Grund, Goos — "Register Allocation for Programs in SSA-Form", 2006  
Section 4.2 

---

## Backlinks target
[SSA Destruction](../02-Components/SSA_Destruction.md)
[SSA Destruction](../02-Components/SSA_Destruction.md)
