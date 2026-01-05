# §4.2 SSA-Destruction

Source:
Register Allocation for Programs in SSA-Form  
Hack, Grund, Goos  
Section 4.2

PDF:
[[06-Research/Papers/ssara.pdf|Register Allocation for Programs in SSA-Form ]]

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
## References

Paper citation:
Hack, Grund, Goos — "Register Allocation for Programs in SSA-Form", 2006  
Section 4.2 

---

## Backlinks target
[[SSA_Spiller/02-Components/SSA Destruction]]
[[SSA_Spiller/01-Pipeline/SSA Destruction]]
