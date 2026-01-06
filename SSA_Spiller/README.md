# SSA Register Allocation on SSA Form (AMDGPU)

Central documentation vault for SSA-based register allocation design,
implementation and research.

---

## 📦 Overview
- `Project Summary`
- `Scope and Goals`
- [Status](SSA_Spiller/08-Worklog/issues/Status.md)

---

## 🚦 Pipeline
- [SSA Rebuilder](SSA_Spiller/01-Pipeline/SSA_Rebuilder.md)
- [Early SSA Spiller](SSA_Spiller/01-Pipeline/Early_SSA_Spiller.md)
- [SSA Register Allocator](SSA_Spiller/01-Pipeline/SSA_Register_Allocator.md)
- [SSA Destruction](SSA_Spiller/01-Pipeline/SSA_Destruction.md)

---

## 🔩 Components
- [Next Use Analysis](SSA_Spiller/02-Components/Next_Use_Analysis.md)
- [SSA Spiller](SSA_Spiller/02-Components/SSA_Spiller.md)
- [MachineLaneSSAUpdater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md)
- `SSA Rebuilder Pass`
- [SSA Register Allocator Impl](SSA_Spiller/02-Components/SSA_Register_Allocator_Impl.md)
- `SSA Decomposer`

---

## 🧠 Concepts
- `Next Use Distance`
- `MIN Algorithm (Belady)`
- [PHI T-Transform](SSA_Spiller/03-Concepts/PHI_T-Transform.md)
- [Perfect Elimination Order (PEO)](SSA_Spiller/03-Concepts/Perfect_Elimination_Order_%28PEO%29.md)
- `PHI Copies and Permutations`
- `SSA Deconstruction Theory`

---

## 🎯 Design
- [Architecture](SSA_Spiller/04-Design/Architecture.md)
- `Data Flow`
- `Control Flow and Dominance`
- `Invariants and Guarantees`
- `Design Decisions`

---

## 🧪 Testing
- `Next Use Analysis Tests`
- `SSA Spiller Tests`
- `Validation Strategy`

---

## 📚 Research
- `Papers`
- [Notes](SSA_Spiller/08-Worklog/NOTES.md)

---

## 🗺 Diagrams
- `Current`
- `Historical`

---

## 📝 Worklog
- `History`

---

## 🔌 Integration
- `LLVM Pipeline`

---

## 🚧 Backlog
- [Open Problems](SSA_Spiller/10-Backlog/Open_problems.md)
- [TODO](SSA_Spiller/08-Worklog/TODO.md)
- `Ideas`
