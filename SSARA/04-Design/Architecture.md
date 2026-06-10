# Architecture

High-level architecture for SSA-based register allocation on AMDGPU.

---

## Overview

The SSA Register Allocation pipeline maintains SSA form throughout register allocation and spilling, only destroying SSA at the final stage before code emission.

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLVM Machine IR (SSA Form)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSA Rebuilder (temporary)                                      │
│  - Restores SSA after PHI elimination pass destroys it          │
│  - Will be removed once all pre-RA passes work on SSA-form MIR  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSA Spiller  (AMDGPUSSARegisterSpiller)                        │
│  - Pass 1 (SGPR): Belady spill selection; store-at-definition   │
│    countSGPRSpillVGPRs() → VGPRLimit -= N (accounting only;     │
│    SGPR spill pseudos left in place for SILowerSGPRSpills)      │
│  - Pass 2 (VGPR): Belady spill selection with reduced budget    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSA Register Allocator  (AMDGPUSSARegisterAllocator)           │
│  - Width-descending PEO coloring (MDT pre-order, bottom-up)     │
│  - kills-before-defs: def can reuse dying source's physreg      │
│  - SSA Destruction: lowerPHIs → resolvePermutation →            │
│    rewriteOperands → leaveSSA → invalidateLiveness              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SILowerSGPRSpills  (existing LLVM pass, unmodified)            │
│  - SuperReg now physical (post-RA) → SGPRSpillBuilder valid     │
│  - SI_SPILL_S*_SAVE/RESTORE → V_WRITELANE/V_READLANE            │
│  - IMPLICIT_DEF for lane VGPRs; sets WWM_REG flag               │
│  - findUnusedRegister(SearchFromTop=true): picks free VGPRs     │
│    above MaxVGPRIdx; no pre-reservation needed in allocator      │
│  - LIS optional (getAnalysisIfAvailable); works post-leaveSSA   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Machine IR (Non-SSA, physical regs)            │
└─────────────────────────────────────────────────────────────────┘
```

**CLI verification** (gfx1200, 2026-06-11):
```bash
llc -run-pass=amdgpu-ssa-register-spiller,\
              amdgpu-ssa-register-allocator,\
              si-lower-sgpr-spills -o - input.mir
```
SGPR spill pseudo (virtual `%s_far`) → physical `$sgpr0` after RA → `SI_SPILL_S32_TO_VGPR $sgpr0, lane=0` + `IMPLICIT_DEF %8:vgpr_32` after `SILowerSGPRSpills`. No crash; no pre-reservation; top-of-file VGPR picked naturally.

---

## Component Design Documents

### Core Components

| Component | Design Document | Status |
|-----------|-----------------|--------|
| **SSA Spiller** | [SSA_SPILLER_DESIGN](SSA_SPILLER_DESIGN.md) | Active |
| **SSA Register Allocator** | [SSA_Register_Allocator_Impl](../02-Components/SSA_Register_Allocator_Impl.md) | Active |
| **MachineLaneSSAUpdater** | [MachineLaneSSAUpdater](MachineLaneSSAUpdater.md) | Active |
| **Next Use Analysis** | [Persistent_Map_for_NUA](Persistent_Map_for_NUA.md) | Active |

### Design Decisions

- [Decisions](Decisions.md) — Key design decisions and their rationale

---

## Key Design Principles

### 1. Store at Definition
Spill stores are emitted immediately after the value is defined (when EXEC mask is guaranteed full), not at the high-pressure point. This avoids EXEC drift correctness issues in divergent control flow.

### 2. Separate Storage from Pressure Relief
- **Physical store location**: Right after definition
- **Virtual spill point**: Where register pressure is actually reduced (marked by `SI_VIRTUAL_SPILL_MARKER` in tests)

### 3. SGPR Spill Accounting vs Materialization Split
- **Spiller** counts lane VGPRs needed (`ceil(Σ objectSize(FI)/4 / WaveSize)`) and reduces VGPR budget.
- **Materialization** (writelane/readlane) happens in `SILowerSGPRSpills` after SSA RA, once SGPRs are physical.
- No pre-reservation in the allocator — coloring colors bottom-up, leaving top-of-file VGPRs free.

### 4. Lane-Aware Operations
All spilling and SSA repair operations are lane-aware, tracking `(VReg, LaneBitmask)` pairs for correct subregister handling.

### 5. SSA Preservation Until Rewrite
The spiller maintains SSA form by using `MachineLaneSSAUpdater` to repair SSA after inserting reloads. SSA is destroyed only at the end of the RA pass (`destroySSAAndRewrite`).

---

## Temporary Components

### SSA Rebuilder ⚠️

> **Note:** This is a temporary workaround component.

The SSA Rebuilder restores SSA form after the existing greedy register allocator has destroyed it. This allows the SSA Spiller to operate on SSA-form IR.

**Why temporary:**
- The greedy allocator will eventually be replaced with a native SSA-based allocator
- Once that happens, SSA form will be preserved throughout, eliminating the need for rebuilding

See: [Pipeline: SSA Rebuilder](../02-Components/SSA_Rebuilder.md)

---

## Future Work

| Feature | Description | Priority |
|---------|-------------|----------|
| Pipeline wiring | `-amdgpu-ssa-regalloc` flag in `addRegAssignAndRewriteOptimized()` | High |
| PHI coalescer | Recolor PHI operands to reduce copies (paper §4.3) | Medium |
| Loop-aware spilling | Fallback when loop filter empties candidate set | Medium |
| Tied-operand RP | Correct RP for tied operand pressure in spiller | Medium |

---

## Historical Designs (Rejected)

- [Old_Spill_Placement_Design](../06-Research/Archive/Old_Spill_Placement_Design.md) — Earlier approach before store-at-definition strategy
