# SSA Register Allocation on SSA Form (AMDGPU)

Central documentation vault for SSA-based register allocation design,
implementation and research.

---

## 📦 Overview
- [[00-Overview/Project Summary]]
- [[00-Overview/Scope and Goals]]
- [[00-Overview/Status]]

---

## 🚦 Pipeline
- [[01-Pipeline/SSA Rebuilder]]
- [[01-Pipeline/Early SSA Spiller]]
- [[01-Pipeline/SSA Register Allocator]]
- [[SSA_Spiller/01-Pipeline/SSA Destruction]]

---

## 🔩 Components
- [[02-Components/Next Use Analysis]]
- [[02-Components/SSA Spiller]]
- [[02-Components/MachineLaneSSAUpdater]]
- [[02-Components/SSA Rebuilder Pass]]
- [[02-Components/SSA Register Allocator Impl]]
- [[02-Components/SSA Decomposer]]

---

## 🧠 Concepts
- [[03-Concepts/Next Use Distance]]
- [[03-Concepts/MIN Algorithm (Belady)]]
- [[03-Concepts/PHI T-Transform]]
- [[03-Concepts/Perfect Elimination Order (PEO)]]
- [[03-Concepts/PHI Copies and Permutations]]
- [[03-Concepts/SSA Deconstruction Theory]]

---

## 🎯 Design
- [[04-Design/Architecture]]
- [[04-Design/Data Flow]]
- [[04-Design/Control Flow and Dominance]]
- [[04-Design/Invariants and Guarantees]]
- [[04-Design/Design Decisions]]

---

## 🧪 Testing
- [[05-Testing/Next Use Analysis Tests]]
- [[05-Testing/SSA Spiller Tests]]
- [[05-Testing/Validation Strategy]]

---

## 📚 Research
- [[06-Research/Papers]]
- [[06-Research/Notes]]

---

## 🗺 Diagrams
- [[07-Diagrams/Current]]
- [[07-Diagrams/Historical]]

---

## 📝 Worklog
- [[08-Worklog/History]]

---

## 🔌 Integration
- [[09-Integration/LLVM Pipeline]]

---

## 🚧 Backlog
- [[10-Backlog/Open Problems]]
- [[10-Backlog/TODO]]
- [[10-Backlog/Ideas]]
