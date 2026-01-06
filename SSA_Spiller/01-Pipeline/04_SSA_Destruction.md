# Pipeline Stage 4: SSA Destruction

📋 *Planned — not yet implemented*

---

## Input

**SSA-form Machine IR with physical registers**
- All registers assigned to physical registers
- PHI nodes present at merge points
- SSA invariants hold

## Function

**Eliminate PHI nodes**
- Convert PHI semantics to explicit copies
- Handle permutation cycles (swap/temp registers)
- Split critical edges if needed
- Minimize inserted copies
- Lane-aware: handle subregister PHIs

## Output

**Non-SSA Machine IR**
- No PHI nodes
- Explicit copy instructions where needed
- Ready for final code emission
- Traditional register assignment complete

---

## Component

→ [[../02-Components/SSA_Destruction|SSA Destruction]]

