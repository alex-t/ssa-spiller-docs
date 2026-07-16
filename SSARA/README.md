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
see [[10-Backlog/Open_problems|Open Problems]].

---

## Pipeline

- [[01-Pipeline/Current_Pipeline|Current Pipeline]] — with SSA Rebuilder (temporary)
- [[01-Pipeline/Future_Pipeline|Future Pipeline]] — target architecture

---

## Components

- [[02-Components/SSA_Spiller|SSA Spiller]] — store-at-definition spilling
- [[02-Components/Next_Use_Analysis|Next Use Analysis]] — Belady-style distance computation
- [[02-Components/MachineLaneSSAUpdater|MachineLaneSSAUpdater]] — lane-aware SSA repair (reaching-VNI oracle)
- [[02-Components/SSA_Rebuilder|SSA Rebuilder]] ⚠️ — temporary SSA reconstruction bridge
- [[02-Components/SSA_Register_Allocator_Impl|SSA Register Allocator]] ✅ — coloring + SSA destruction + operand rewrite
- [[02-Components/SSA_Destruction|SSA Destruction]] ✅ — PHI lowering + operand rewrite (part of the allocator)

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
