# SSA Register Allocation on SSA Form (AMDGPU)

Central documentation vault for SSA-based register allocation design,
implementation and research.

---

## 📦 Overview
- [00-Overview/Project Summary](00-Overview/Project_Summary.md) <!-- TODO: file not found -->
- [00-Overview/Scope and Goals](00-Overview/Scope_and_Goals.md) <!-- TODO: file not found -->
- [00-Overview/Status](00-Overview/Status.md) <!-- TODO: file not found -->

---

## 🚦 Pipeline
- [01-Pipeline/SSA Rebuilder](01-Pipeline/SSA_Rebuilder.md) <!-- TODO: file not found -->
- [01-Pipeline/Early SSA Spiller](01-Pipeline/Early_SSA_Spiller.md) <!-- TODO: file not found -->
- [01-Pipeline/SSA Register Allocator](01-Pipeline/SSA_Register_Allocator.md) <!-- TODO: file not found -->
- [SSA_Spiller/01-Pipeline/SSA Destruction](SSA_Spiller/01-Pipeline/SSA_Destruction.md) <!-- TODO: file not found -->

---

## 🔩 Components
- [02-Components/Next Use Analysis](02-Components/Next_Use_Analysis.md) <!-- TODO: file not found -->
- [02-Components/SSA Spiller](02-Components/SSA_Spiller.md) <!-- TODO: file not found -->
- [02-Components/MachineLaneSSAUpdater](02-Components/MachineLaneSSAUpdater.md) <!-- TODO: file not found -->
- [02-Components/SSA Rebuilder Pass](02-Components/SSA_Rebuilder_Pass.md) <!-- TODO: file not found -->
- [02-Components/SSA Register Allocator Impl](02-Components/SSA_Register_Allocator_Impl.md) <!-- TODO: file not found -->
- [02-Components/SSA Decomposer](02-Components/SSA_Decomposer.md) <!-- TODO: file not found -->

---

## 🧠 Concepts
- [03-Concepts/Next Use Distance](03-Concepts/Next_Use_Distance.md) <!-- TODO: file not found -->
- [03-Concepts/MIN Algorithm (Belady)](03-Concepts/MIN_Algorithm_(Belady).md) <!-- TODO: file not found -->
- [03-Concepts/PHI T-Transform](03-Concepts/PHI_T-Transform.md) <!-- TODO: file not found -->
- [03-Concepts/Perfect Elimination Order (PEO)](03-Concepts/Perfect_Elimination_Order_(PEO).md) <!-- TODO: file not found -->
- [03-Concepts/PHI Copies and Permutations](03-Concepts/PHI_Copies_and_Permutations.md) <!-- TODO: file not found -->
- [03-Concepts/SSA Deconstruction Theory](03-Concepts/SSA_Deconstruction_Theory.md) <!-- TODO: file not found -->

---

## 🎯 Design
- [04-Design/Architecture](04-Design/Architecture.md) <!-- TODO: file not found -->
- [04-Design/Data Flow](04-Design/Data_Flow.md) <!-- TODO: file not found -->
- [04-Design/Control Flow and Dominance](04-Design/Control_Flow_and_Dominance.md) <!-- TODO: file not found -->
- [04-Design/Invariants and Guarantees](04-Design/Invariants_and_Guarantees.md) <!-- TODO: file not found -->
- [04-Design/Design Decisions](04-Design/Design_Decisions.md) <!-- TODO: file not found -->

---

## 🧪 Testing
- [05-Testing/Next Use Analysis Tests](05-Testing/Next_Use_Analysis_Tests.md) <!-- TODO: file not found -->
- [05-Testing/SSA Spiller Tests](05-Testing/SSA_Spiller_Tests.md) <!-- TODO: file not found -->
- [05-Testing/Validation Strategy](05-Testing/Validation_Strategy.md) <!-- TODO: file not found -->

---

## 📚 Research
- [06-Research/Papers](06-Research/Papers.md) <!-- TODO: file not found -->
- [06-Research/Notes](06-Research/Notes.md) <!-- TODO: file not found -->

---

## 🗺 Diagrams
- [07-Diagrams/Current](07-Diagrams/Current.md) <!-- TODO: file not found -->
- [07-Diagrams/Historical](07-Diagrams/Historical.md) <!-- TODO: file not found -->

---

## 📝 Worklog
- [08-Worklog/History](08-Worklog/History.md) <!-- TODO: file not found -->

---

## 🔌 Integration
- [09-Integration/LLVM Pipeline](09-Integration/LLVM_Pipeline.md) <!-- TODO: file not found -->

---

## 🚧 Backlog
- [10-Backlog/Open Problems](10-Backlog/Open_Problems.md) <!-- TODO: file not found -->
- [10-Backlog/TODO](10-Backlog/TODO.md) <!-- TODO: file not found -->
- [10-Backlog/Ideas](10-Backlog/Ideas.md) <!-- TODO: file not found -->
