# SSA Register Allocation on SSA Form (AMDGPU)

Central documentation vault for SSA-based register allocation design,
implementation and research.

---

## 🚦 Pipeline

- [[SSA_Rebuilder|SSA Rebuilder]]
- [[Early_SSA_Spiller|Early SSA Spiller]]
- [[SSA_Register_Allocator|SSA Register Allocator]]
- [[SSA_Destruction|SSA Destruction]]

---

## 🔩 Components

- [[Next_Use_Analysis|Next Use Analysis]]
- [[SSA_Spiller|SSA Spiller]]
- [[MachineLaneSSAUpdater]]
- [[SSA_Register_Allocator_Impl|SSA Register Allocator Impl]]

---

## 🧠 Concepts

- [[MIN_Algorithm|MIN Algorithm (Belady)]]
- [[PHI_T-Transform|PHI T-Transform]]
- [[Perfect_Elimination_Order_(PEO)|Perfect Elimination Order (PEO)]]
- [[Chordal_Graphs|Chordal Graphs]]

---

## 🎯 Design

- [[Architecture]]
- [[Decisions|Design Decisions]]
- [[SSA_SPILLER_DESIGN|SSA Spiller Design]]
- [[Persistent_Map_for_NUA|Persistent Map for NUA]]

---

## 🧪 Testing

- [[NUA_TEST_PATTERNS|Next Use Analysis Tests]]
- [[SSA_SPILLER_TEST_PATTERNS|SSA Spiller Tests]]
- [[MachineLaneSSAUpdater_TestFramework_Summary|MachineLaneSSAUpdater Tests]]

---

## 📚 Research

- [[Old_Spill_Placement_Design|Old Spill Placement Design]] (historical)

---

## 📝 Worklog

- [[NOTES|Development Notes]]
- [[TODO]]
- [[Status|Issue Status]]

---

## 🚧 Backlog

- [[Open_problems|Open Problems]]

---

## 🛠 Tools

- [[TOOLS_USAGE|Tools Usage Guide]]
