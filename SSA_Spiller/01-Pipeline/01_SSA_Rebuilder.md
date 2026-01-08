# Pipeline Stage 1: SSA Rebuilder

⚠️ *Temporary stage — will be removed when upstream passes preserve SSA*

---

## Input

**Non-SSA Machine IR**
- PHI nodes eliminated
- Multiple definitions per virtual register possible
- Result of PHI Elimination pass

## Function

**Reconstruct SSA form**
- Identify violated SSA invariants (multiple defs)
- Insert PHI nodes at iterated dominance frontier
- Rewrite uses to correct reaching definitions
- Lane-aware: handles subregisters correctly

## Output

**SSA-form Machine IR**
- Single definition per virtual register (per lane)
- All uses dominated by their definitions
- PHI nodes at control flow merge points
- LiveIntervals valid

---

## Component

→ [[../02-Components/SSA_Rebuilder|SSA Rebuilder]]



