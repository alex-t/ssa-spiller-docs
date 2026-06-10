# SSA-Based Register Allocation (AMDGPU)

Documentation for SSA-based register allocation: design, implementation, and research.

---

## Status

| Component | Status |
|-----------|--------|
| **SSA Spiller** | ✅ Implemented |
| **NextUseAnalysis** | ✅ Implemented |
| **MachineLaneSSAUpdater** | ✅ Implemented |
| SSA Rebuilder | ⚠️ Temporary |
| SSA Register Allocator | ⚠️ Coloring implemented |
| SSA Destruction | 📋 Not yet implemented |

---

## Pipeline

- [[01-Pipeline/Current_Pipeline|Current Pipeline]] — with SSA Rebuilder (temporary)
- [[01-Pipeline/Future_Pipeline|Future Pipeline]] — target architecture

---

## Components

- [[02-Components/SSA_Spiller|SSA Spiller]] — store-at-definition spilling
- [[02-Components/Next_Use_Analysis|Next Use Analysis]] — Belady-style distance computation
- [[02-Components/MachineLaneSSAUpdater|MachineLaneSSAUpdater]] — lane-aware SSA repair
- [[02-Components/SSA_Rebuilder|SSA Rebuilder]] ⚠️ — temporary SSA reconstruction
- [[02-Components/SSA_Register_Allocator_Impl|SSA Register Allocator]] 📋
- [[02-Components/SSA_Destruction|SSA Destruction]] 📋

---

## Design

- [[04-Design/Architecture|Architecture]] — high-level overview
- [[04-Design/SSA_SPILLER_DESIGN|SSA Spiller Design]] — detailed spiller design
- [[04-Design/NextUseAnalysis|Next Use Analysis Design]] — NUA internals
- [[04-Design/MachineLaneSSAUpdater|MachineLaneSSAUpdater Design]] — lane-aware SSA repair
- [[04-Design/SSA_RA_Coloring|SSA RA Coloring Design]] — width-descending PEO coloring
- [[04-Design/Decisions|Design Decisions]] — key design choices and rationale

---

## Concepts

- [[03-Concepts/MIN_Algorithm|MIN Algorithm (Belady)]] — optimal spill selection
- [[03-Concepts/EXEC_Drift|EXEC Drift]] — divergent control flow correctness
- [[03-Concepts/PHI_T-Transform|PHI T-Transform]]
- [[03-Concepts/Perfect_Elimination_Order_(PEO)|Perfect Elimination Order]]
- [[03-Concepts/Chordal_Graphs|Chordal Graphs]]

---

## Testing

- [[05-Testing/SSA_Spiller/SSA_SPILLER_TEST_PATTERNS|SSA Spiller Tests]] — 10 MIR test patterns
- [[05-Testing/Next_Use_Analysis/NUA_TEST_PATTERNS|Next Use Analysis Tests]] — 17 MIR test patterns

---

## Research

- [[06-Research/Papers/|Papers]] — academic references
- [[06-Research/Archive/|Archive]] — historical designs

---

## Quick Links

**Source Code** (GitHub):
- [`AMDGPUSSARegisterSpiller.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp)
- [`AMDGPUNextUseAnalysis.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp)
- [`MachineLaneSSAUpdater.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp)
