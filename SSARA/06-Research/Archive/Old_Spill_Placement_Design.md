# Old Spill Placement Strategy (ARCHIVED)

Status: Deprecated  
Scope: SSA Spiller  
Decision: Rejected in favor of "spill-at-definition + virtual spill point"

---

## Purpose (Historical)

This document captures an **older design attempt** to solve SSA spilling
using:

- balanced spill vs split-before-use logic
- path analysis between spill, join, and use
- reload placement heuristics
- loop-aware candidate evaluation
- complex CFG rewrites

The design was discussed with the team and ultimately rejected
in favor of a simpler and more correct model.

---

## Core Idea (Rejected)

Perform *decision-heavy CFG surgery* during SSA spilling:

Two competing transformations were evaluated:

---

### 1. Split-Before-Use

- Spill happens on spill path only
- Reload is conditional
- CFG split introduced
- WWM required for divergent paths

Drawbacks:
- irreversible transformations per use
- complex SSA repair
- CFG explosion
- fragile correctness

---

### 2. Balanced Spill

- Spill on both clean and spill paths
- Single reload after JoinBB
- Reduce RP in common CFG
- Heavy analysis

Drawbacks:
- intricate path graph analysis
- reload location ambiguity
- loop placement dangers
- complex cost model

---

## Why It Was Rejected

During review, this approach was rejected because:

### ❌ Conceptual Explosion
The design introduces:
- multi-phase analysis
- synthetic CFG surgery
- fine-grained heuristics
- delayed decisions
- speculative transformations

### ❌ Error-Prone
Once CFG is modified:
- wrong decisions are irreversible
- SSA is difficult to repair
- interactions explode in complexity

### ❌ Overengineering
The approach tried to *predict* the future instead of enforcing
hard invariants (RP ≤ limit).

---

## Final Decision (Current Architecture)

The team decided in favor of:

---

### ✅ Physical Spill at Definition

When RP exceeds limit:

✅ emit spill exactly once  
✅ at the defining instruction  
✅ no conditional CFG  
✅ no split blocks  
✅ no reload speculation  
✅ no WWM  
✅ no balanced spill  

---

### ✅ Virtual Spill Point

Instead of modifying CFG:

- Insert a logical "spill point"
- Rewrite all dominated and reachable uses
- SSA updated structurally
- Rooted at dominance, not heuristics

---

### ✅ Reload Placement

All reloads become:

- SSA-driven
- dominated-use grouped
- optionally hoisted if profitable
- never conditional
- never speculative

---

## Architectural Gain

Compared to old approach:

| Category | Old | New |
|----------|-----|-----|
| CFG edits | heavy | none |
| SSA repair | complex | structural |
| Correctness | heuristic | enforced |
| RP handling | reactive | guaranteed |
| Rollback | impossible | irrelevant |
| Complexity | very high | low |
| Extensibility | poor | high |

---

## Value of This Document

This file is kept because:

✅ it records rejected complexity  
✅ avoids regressions  
✅ explains prior thinking  
✅ documents team decision  
✅ prevents future rediscovery of bad paths  

---

## Status

This design is **NOT** to be revived.

For current strategy, see:

- [[01-Pipeline/Early SSA Spiller]]
- [[04-Design/Architecture]]
- [[02-Components/SSA Spiller]]

---

## Source

Original file:
`SPILL_PLACEMENT_DESIGN.md`

Archived faithfully.
## Related (Historical)

- [[Old Spill Placement Implementation Plan]]

