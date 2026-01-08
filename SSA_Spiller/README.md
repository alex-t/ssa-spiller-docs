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
| SSA Register Allocator | 📋 Not yet implemented |
| SSA Destruction | 📋 Not yet implemented |

---

## Pipeline

- [Current Pipeline](01-Pipeline/Current_Pipeline.md) — with SSA Rebuilder (temporary)
- [Future Pipeline](01-Pipeline/Future_Pipeline.md) — target architecture

---

## Components

- [SSA Spiller](02-Components/SSA_Spiller.md) — store-at-definition spilling
- [Next Use Analysis](02-Components/Next_Use_Analysis.md) — Belady-style distance computation
- [MachineLaneSSAUpdater](04-Design/MachineLaneSSAUpdater.md) — lane-aware SSA repair
- [SSA Rebuilder](02-Components/SSA_Rebuilder.md) ⚠️ — temporary SSA reconstruction
- [SSA Register Allocator](02-Components/SSA_Register_Allocator_Impl.md) 📋
- [SSA Destruction](02-Components/SSA_Destruction.md) 📋

---

## Design

- [Architecture](04-Design/Architecture.md) — high-level overview
- [SSA Spiller Design](04-Design/SSA_SPILLER_DESIGN.md) — detailed spiller design
- [Next Use Analysis Design](04-Design/NextUseAnalysis.md) — NUA internals
- [MachineLaneSSAUpdater Design](04-Design/MachineLaneSSAUpdater.md) — lane-aware SSA repair
- [Design Decisions](04-Design/Decisions.md) — key design choices and rationale

---

## Concepts

- [MIN Algorithm (Belady)](03-Concepts/MIN_Algorithm.md) — optimal spill selection
- [EXEC Drift](03-Concepts/EXEC_Drift.md) — divergent control flow correctness
- [PHI T-Transform](03-Concepts/PHI_T-Transform.md)
- [Perfect Elimination Order](03-Concepts/Perfect_Elimination_Order_%28PEO%29.md)
- [Chordal Graphs](03-Concepts/Chordal_Graphs.md)

---

## Testing

- [SSA Spiller Tests](05-Testing/SSA_Spiller/SSA_SPILLER_TEST_PATTERNS.md) — 10 MIR test patterns
- [Next Use Analysis Tests](05-Testing/Next_Use_Analysis/NUA_TEST_PATTERNS.md) — 17 MIR test patterns

---

## Research

- `Papers` — academic references
- `Archive` — historical designs

---

## Quick Links

**Source Code** (GitHub):
- [`AMDGPUSSARegisterSpiller.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp)
- [`AMDGPUNextUseAnalysis.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp)
- [`MachineLaneSSAUpdater.cpp`](https://github.com/alex-t/llvm-project/blob/45385c6f5f008cde206d5828a00a17d6bb7f7783/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp)
