# Old Spill Placement – Implementation Plan (ARCHIVED)

Status: Obsolete  
Decision: Rejected (replaced with spill-at-definition + virtual spill point)  
Scope: SSA Spiller  

---

## Overview

This document proposed an **incremental implementation plan** for the now-rejected design
based on:

- deferred reachable-use processing
- balanced vs split-before-use classification
- join-point analysis
- loop-aware decision heuristics
- CFG rewrite logic
- reload strategy selection

---

## Original Intent

Three-phase rollout:

1. Improve spill candidate election (avoid loop-body spills)
2. Defer reload decisions until CFG join points
3. Apply balanced vs split transformations

---

## Why This Plan Was Rejected

The architecture attempted to *refine correctness heuristically*
rather than enforcing it through invariants.

Major issues:

### ❌ Architecture embedded policy
Spill placement decisions were:
- speculative
- irreversible
- dependent on heuristics
- sensitive to incomplete information

### ❌ CFG surgery burden
Design depended on:
- block splitting
- conditional reloads
- path recomposition

### ❌ High conceptual complexity
Required:
- path metric aggregation
- deferred decision queues
- custom cost models
- repeated CFG analysis

### ❌ Wrong abstraction layer
Correctness was embedded in:
> local decisions  
instead of  
> global invariants

---

## Final Replacement Architecture

This plan was replaced with:

---

### ✅ Manifest Spill at Definition

- spill once
- at definition
- unconditionally
- exactly one memory write per spilled virtual register

---

### ✅ Virtual Spill Point

Instead of CFG surgery:

- mark logical spill point
- rewrite dominated and reachable uses
- apply uniform SSA transformation
- group reload placement by dominance

---

### ✅ Reload Strategy

Reloads become:

- SSA driven
- path independent
- dominance-based
- non-conditional
- safe by construction

---

## Status

This implementation plan is **historical only**.

It must **not** guide current changes.

---

## Historical Value

This file is kept because it records:

✅ evolution of thinking  
✅ rejected trade-offs  
✅ complexity traps avoided  
✅ design direction change  
✅ rational decision-making  

---

## Current Design

See:

- [Architecture](SSA_Spiller/04-Design/Architecture.md)
- `Early SSA Spiller`
- [SSA Spiller](SSA_Spiller/02-Components/SSA_Spiller.md)
## Related (Historical)

- [Old Spill Placement Implementation Plan](SSA_Spiller/06-Research/Archive/Old_Spill_Placement_Implementation_Plan.md)
