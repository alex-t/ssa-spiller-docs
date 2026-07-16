# SSA-Based Register Allocation (AMDGPU)

Documentation for SSA-based register allocation: design, implementation, and research.

---

## Status

The whole pipeline is gated behind the hidden `-amdgpu-ssa-regalloc` option
(default **OFF**), and is wired only into the legacy pass manager.

| Component | Status |
|-----------|--------|
| **SSA Spiller** (with inline reaching-VNI reconstruction) | ✅ Implemented |
| **NextUseAnalysis** | ✅ Implemented |
| **MachineLaneSSAUpdater** | ✅ Implemented |
| **SSA Register Allocator** — coloring (width-descending PEO) | ✅ Implemented |
| **SSA Destruction + operand rewrite** | ✅ Implemented |
| **SimplifyUndefPHI** (undef-flag + single-real-operand fold) | ✅ Implemented |
| SSA Rebuilder | ⚠️ Temporary bridge (to be removed) |
| Full PHI coalescer | 📋 Not implemented (affinity hints + metrics only) |
| New pass manager support | 📋 Not wired |

SSA destruction is **skipped** for functions that still contain SI
control-flow pseudos (`SI_IF`/`SI_ELSE`/`SI_IF_BREAK`/`SI_LOOP`/`SI_END_CF`) —
see [Open Problems](10-Backlog/Open_problems.md).

---

## Pipeline

- [Current Pipeline](01-Pipeline/Current_Pipeline.md) — with SSA Rebuilder (temporary)
- [Future Pipeline](01-Pipeline/Future_Pipeline.md) — target architecture

---

## Components

- [SSA Spiller](02-Components/SSA_Spiller.md) — store-at-definition spilling
- [Next Use Analysis](02-Components/Next_Use_Analysis.md) — Belady-style distance computation
- [MachineLaneSSAUpdater](04-Design/MachineLaneSSAUpdater.md) — lane-aware SSA repair (reaching-VNI oracle)
- [SSA Rebuilder](02-Components/SSA_Rebuilder.md) ⚠️ — temporary SSA reconstruction bridge
- [SSA Register Allocator](02-Components/SSA_Register_Allocator_Impl.md) ✅ — coloring + SSA destruction + operand rewrite
- [SSA Destruction](02-Components/SSA_Destruction.md) ✅ — PHI lowering + operand rewrite (part of the allocator)

---

## Design

- [Architecture](04-Design/Architecture.md) — high-level overview
- [SSA Spiller Design](04-Design/SSA_SPILLER_DESIGN.md) — detailed spiller design
- [Next Use Analysis Design](04-Design/NextUseAnalysis.md) — NUA internals
- [MachineLaneSSAUpdater Design](04-Design/MachineLaneSSAUpdater.md) — lane-aware SSA repair
- [SSA RA Coloring Design](04-Design/SSA_RA_Coloring.md) — width-descending PEO coloring
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
