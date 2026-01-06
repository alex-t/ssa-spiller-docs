# Pipeline Stage 3: SSA Register Allocator

📋 *Planned — not yet implemented*

---

## Input

**SSA-form Machine IR**
- Register pressure within limits (post-spilling)
- Virtual registers only
- Valid LiveIntervals

## Function

**Assign physical registers**
- Traverse dominator tree
- Assign physical registers to virtual registers
- Exploit SSA properties (chordal interference → PEO coloring)
- On-demand spilling if constraints not met
- AMDGPU-specific: separate VGPR/SGPR allocation

## Output

**SSA-form Machine IR with physical registers**
- All virtual registers assigned to physical registers
- SSA form still preserved
- PHI nodes use physical registers
- Ready for SSA destruction

---

## Component

→ [[../02-Components/SSA_Register_Allocator_Impl|SSA Register Allocator]]

