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
│  - Will be removed when all MIR passes before RA are ready      | 
|          to work on SSA-form MIR.                               |
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Early SSA Spiller                                              │
│  - Reduces register pressure while preserving SSA               │
│  - Uses Belady/MIN algorithm for spill selection                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSA Register Allocator (future)                                │
│  - Assigns physical registers to virtual registers              │
│  - Exploits SSA properties (chordal interference graphs)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SSA Destruction                                                │
│  - Converts SSA form to conventional form                       │
│  - Resolves PHI nodes with copies                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Machine IR (Non-SSA)                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Design Documents

### Core Components

| Component | Design Document | Status |
|-----------|-----------------|--------|
| **SSA Spiller** | [[SSA_SPILLER_DESIGN]] | Active |
| **MachineLaneSSAUpdater** | [[MachineLaneSSAUpdater]] | Active |
| **Next Use Analysis** | [[Persistent_Map_for_NUA]] | Active |

### Design Decisions

- [[Decisions]] — Key design decisions and their rationale

---

## Key Design Principles

### 1. Store at Definition
Spill stores are emitted immediately after the value is defined (when EXEC mask is guaranteed full), not at the high-pressure point. This avoids EXEC drift correctness issues in divergent control flow.

### 2. Separate Storage from Pressure Relief
- **Physical store location**: Right after definition
- **Virtual spill point**: Where register pressure is actually reduced

### 3. Lane-Aware Operations
All spilling and SSA repair operations are lane-aware, tracking `(VReg, LaneBitmask)` pairs for correct subregister handling.

### 4. SSA Preservation
The spiller maintains SSA form by:
- Using [[MachineLaneSSAUpdater]] to repair SSA after inserting reloads
- Inserting PHIs at IDF blocks when needed
- Rewriting uses to correct SSA values

---

## Temporary Components

### SSA Rebuilder ⚠️

> **Note:** This is a temporary workaround component.

The SSA Rebuilder restores SSA form after the existing greedy register allocator has destroyed it. This allows the SSA Spiller to operate on SSA-form IR.

**Why temporary:**
- The greedy allocator will eventually be replaced with a native SSA-based allocator
- Once that happens, SSA form will be preserved throughout, eliminating the need for rebuilding

See: [[SSA_Rebuilder|Pipeline: SSA Rebuilder]]

---

## Future Work

| Feature | Description | Priority |
|---------|-------------|----------|
| SSA Register Allocator | Native SSA-based allocation using PEO | High |
| SSA Destruction | Final PHI resolution | Medium |
| Loop-aware spilling | Optimize spill placement around loops | Medium |
| Cost model | Balance strategies based on CFG analysis | Medium |

---

## Historical Designs (Rejected)

- [[Old_Spill_Placement_Design]] — Earlier approach before store-at-definition strategy
