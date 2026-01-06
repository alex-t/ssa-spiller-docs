---
marp: true
theme: default
paginate: true
header: 'AMDGPU SSA Register Spiller'
footer: 'November 2025'
style: |
  section {
    font-size: 20px;
  }
  h1 {
    color: #2c3e50;
  }
  h2 {
    color: #34495e;
  }
  code {
    background: #f4f4f4;
  }
  .mermaid {
    text-align: center;
  }
---

# AMDGPU SSA Register Spiller
## Spill/Reload Placement Design for Divergent Control Flow

**Implementation of SSA-aware register allocation with EXEC drift handling**

November 2025

---

## Agenda

1. **Problem Overview**: EXEC Drift & SSA Challenges
2. **Classification**: Spill→Use Situations
3. **Current Status**: What's Implemented
4. **Design Evolution**: Deferred Processing & Loop Awareness
5. **New Strategies**:
   - Balanced Spill vs Split-Before-Use
   - Hoisting Reloads to NCD
   - Loop-Aware Candidate Selection
6. **Implementation Plan**: Phased Approach
7. **Future Work**

---

## 1. The Core Challenge: EXEC Drift

![Title page](./Diagrams/Spilling issue.png)

### What is EXEC Drift?

- **EXEC register** controls which SIMD lanes are active
- **Divergent branches** (VCC-based) modify EXEC along different paths
- **Spill** writes only lanes active at spill site
- **Reload** may execute with different EXEC → reads invalid lanes!

### Consequences

❌ Correctness violation: reloaded values contain garbage in inactive lanes
❌ Belady's optimality broken: reloading immediately defeats next-use distance
❌ SSA form preservation: multiple definitions require PHI insertion

---

## Figure 1a: EXEC Drift Problem

**Divergent CFG: spill executed under masked EXEC, reload under full EXEC**

![Problem illustration](./Diagrams/Spilling issue divergent CFG.png)

⚠️ **Only lanes 0-31 are spilled, but reload expects all lanes!**

---

## 2. Classification of Spill→Use Situations

![Classification](./Diagrams/Spill's reachable use definition.png)

Placement strategy depends on **dominance** and **EXEC stability**:

### Case 1: **Dominated Use**
- All paths to use pass through spill
- Single reload at dominating point suffices
- **No PHIs needed**, **No EXEC handling** required

### Case 2: **Reachable but Not Dominated — Uniform Paths**
- Some paths bypass spill
- No EXEC writes on any path S→U
- **Split-on-reload**: separate spill/clean paths + PHI merges values

---

## Case 3: **Reachable but Not Dominated — Divergent Paths**

![Divergent paths](./Diagrams/Possible solution divergent CFG.png)

- Some paths bypass spill **AND** EXEC is modified on S→U
- **Both SPILL and RELOAD must preserve consistency**

### Two Solutions:

1. **WWM (Whole Wave Mode)**: Save/restore EXEC around spill & reload
   - ✅ Simple, correct
   - ❌ Uses 2 SGPRs per live spill (persistent mask)
   - ❌ Cost: `C_salu` instructions

2. **EWF (EXEC-Write Frontier)**: Reload at first EXEC-write point
   - ✅ No persistent SGPR usage
   - ❌ Reloads earlier → increases live range → suboptimal for Belady

---

## Figure 1b: Uniform Case (Split-on-Reload)

![Uniform split](./Diagrams/Spilling issue uniform CFG.png)

**Split join block before use; reload on spill path; PHI merges original and reloaded values.**

---

## Figure 2: Split-on-Reload CFG Transformation

![Split-on-Reload diagram](./Diagrams/Possible solution uniform CFG.png)

**Split MBB_1 into MBB_1_1 (pre) and MBB_1_2 (post); insert MBB_3 for reload; conditional branch selects path.**

---

## Figure 3: Divergent Paths Comparison

### WWM: Transient EXEC Save/Restore

![WWM diagram](./Diagrams/Possible solution divergent CFG.png)

Both spill and reload wrapped:
```asm
s_or_saveexec_b64 s_tmp, -1
slot0 = spill(x)
s_mov_b64 exec, s_tmp
```

---

## Figure 3 (continued): EWF Alternative

![EWF diagram](./Diagrams/WWM vs EWF.png)

**Reload at first EXEC-write frontier → no save/restore, but earlier reload**

---

## 3. Decision Table (Summary)

| **Case**                     | **EXEC Modified** | **Strategy**                                      | **SGPR Usage** | **Key Thresholds**                                  |
|------------------------------|-------------------|---------------------------------------------------|----------------|-----------------------------------------------------|
| Dominated use                | No                | Single dominating reload                          | 0              | —                                                   |
| Not dominated, Uniform       | No                | Split join before use (reload on spill path)      | 0              | Split if `len_join ≥100` or `d_use ≥50` or `avgRP_clean ≤0.5·RPLimit` |
|                              |                   | OR insert balancing spill on clean path          | 0              | Balance if `avgRP_clean ≥0.8·RPLimit` & `len_clean ≥50` |
| Not dominated, Divergent     | Yes               | **WWM** spill+reload (cost-balanced)              | 2 transient/0  | If no SGPR→EWF; else `f_ewf = d_ewf/NUD`: EWF if `≤0.25` else WWM |

**Tie-breaker:** Split-before-use avoids redundant memory operations.

---

## 4. Cost Model for WWM vs EWF

![Cost model](./Diagrams/WWM vs EWF.png)

### Metrics

- **avgRP_clean**, **len_clean**: average RP and instruction count on clean path segment
- **len_join**, **d_use**: length of join block and distance from entry to first use
- **NUD** (next-use distance): S→U instruction count
- **d_ewf**: distance from spill to EXEC-Write Frontier
- **f_ewf** = `d_ewf / NUD`: fraction of sink lost when reloading early at EWF

### Decision Logic (Divergent Case)

```text
if SGPR_budget_transient == 0:
    use EWF for all divergent spills
else:
    f_ewf = d_ewf / NUD
    if f_ewf ≤ 0.25:
        → EWF (minimal sink loss)
    else:
        → WWM spill+reload (pay C_salu but keep Belady optimality)
```

---

## 5. WWM Implementation Details

### Transient EXEC Save/Restore

**Wave32:**
```asm
s_or_saveexec_b32 s_tmp, -1       ; Save EXEC, set all lanes active
SI_SPILL_V64_SAVE %2.sub2_sub3, %stack.0, $sgpr32, 0
s_mov_b32 exec_lo, s_tmp           ; Restore original EXEC
```

**Wave64:**
```asm
s_or_saveexec_b64 s_tmp, -1
SI_SPILL_V64_SAVE ...
s_mov_b64 exec, s_tmp
```

**Cost:** 2-3 SALU instructions per spill/reload pair.

---

## Figure: WWM Decision Table

![Decision table](./Diagrams/Spill vs split.png)

**Table shows thresholds for uniform case (split vs balance) and divergent case (WWM vs EWF).**

---

## 6. Implementation Architecture

### Key Components

1. **NextUseAnalysis (NUA)**: Belady's algorithm for spill selection
   - Query at `std::next(I.getReverse())` to allow input reuse
   - Block early-clobber conflicting operands from spilling

2. **RPTracker**: GCNUpwardRPTracker for register pressure
   - Track occupancy limits
   - Trigger spilling when RP exceeds threshold

3. **Spill/Reload Emission**: `emitSpill()`, `emitReload()`
   - Insert spill/reload instructions via `TII->storeRegToStackSlot` / `loadRegFromStackSlot`
   - WWM wrapping for divergent paths

---

## 6. Implementation (continued)

4. **SSA Repair**: `MachineLaneSSAUpdater`
   - Automatic PHI insertion at merge points
   - Use rewriting for dominated regions
   - Handles subregister lanes correctly

5. **CFG Transformation**: `splitBlockBeforeReload()`
   - Split use block into Pre/Post
   - Insert ReloadBB with conditional branch
   - Create flag PHI at merge point
   - Create value PHI after ReloadBB

6. **LiveIntervals Updates**
   - Insert new instructions into LIS maps
   - `shrinkToUses()` after all SSA repairs complete
   - Ensures RPTracker sees reduced pressure

---

## 7. Split-Before-Use CFG Transformation

### Original CFG

<div class="mermaid">
graph TD
    DefBB["DefBB: x = def(x)"]
    SpillBB["SpillBB: slot = spill(x) Cond = true"]
    CleanBB["CleanBB: long path Cond = false"]
    UseBB["UseBB: use(x)"]
    
    DefBB --> SpillBB
    DefBB --> CleanBB
    SpillBB --> UseBB
    CleanBB --> UseBB
</div>

---

## 7. Split-Before-Use (continued)

### Transformed CFG

<div class="mermaid">
graph TD
    DefBB["DefBB: x = def(x)"]
    SpillBB["SpillBB: slot = spill(x) FlagS = 1"]
    CleanBB["CleanBB: long path FlagC = 0"]
    FlowBB["FlowBB: Flag = PHI(FlagS, FlagC)"]
    UseBB_Pre["UseBB_Pre: S_CMP Flag, 0 S_CBRANCH_SCC1 UseBB_Post"]
    ReloadBB["ReloadBB: y = reload(slot)"]
    UseBB_Post["UseBB_Post: z = PHI(y, x) use(z)"]
    
    DefBB --> SpillBB
    DefBB --> CleanBB
    SpillBB --> FlowBB
    CleanBB --> FlowBB
    FlowBB --> UseBB_Pre
    UseBB_Pre -->|"Cond==0"| UseBB_Post
    UseBB_Pre -->|"Cond==1"| ReloadBB
    ReloadBB --> UseBB_Post
</div>

---

## 8. Code Example: `emitReload` with WWM

```cpp
MachineInstr *AMDGPUSSARegisterSpiller::emitReload(
    MachineBasicBlock::iterator InsertBefore, VRegMaskPair VMP) {
  
  Register OrigVReg = VMP.getVReg();
  int FI = assignVirt2StackSlot(VMP);
  
  // WWM wrapping for divergent paths
  if (needsWWMWrapping(InsertBefore, VMP)) {
    Register ExecSave = MRI->createVirtualRegister(&AMDGPU::SReg_32_XM0_XEXECRegClass);
    BuildMI(*MBB, InsertBefore, DL, TII->get(AMDGPU::COPY), ExecSave)
      .addReg(AMDGPU::EXEC_LO);
    BuildMI(*MBB, InsertBefore, DL, TII->get(AMDGPU::S_MOV_B32), AMDGPU::EXEC_LO)
      .addImm(-1);
    
    TII->loadRegFromStackSlot(*MBB, InsertBefore, OrigVReg, FI, RC, TRI);
    
    BuildMI(*MBB, InsertBefore, DL, TII->get(AMDGPU::COPY), AMDGPU::EXEC_LO)
      .addReg(ExecSave);
  } else {
    TII->loadRegFromStackSlot(*MBB, InsertBefore, OrigVReg, FI, RC, TRI);
  }
  
  return &*std::prev(InsertBefore);
}
```

---

## 9. SSA Repair with MachineLaneSSAUpdater

```cpp
Register AMDGPUSSARegisterSpiller::repairSSAForReload(
    MachineInstr *ReloadMI, VRegMaskPair VMP) {
  
  Register OrigVReg = VMP.getVReg();
  Register NewVReg = MRI->createVirtualRegister(MRI->getRegClass(OrigVReg));
  
  MachineLaneSSAUpdater SSAUpdater(*MF, VMP.getLaneMask());
  SSAUpdater.Initialize(OrigVReg);
  SSAUpdater.AddAvailableValue(ReloadMI->getParent(), NewVReg);
  
  // Find dominated uses
  for (MachineInstr &MI : dominatedUses(ReloadMI, OrigVReg)) {
    SSAUpdater.RewriteUse(MI.getOperandNo(...));
  }
  
  // SSAUpdater automatically inserts PHIs at merge points
  return NewVReg;
}
```

---

## 10. Testing: LIT Test Structure

**Test file:** `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-vreg-subregister.mir`

### Test Case: Subregister Spill with Split-Before-Use

**Input:**
- `%2:vreg_128` is a 128-bit vector (4×32-bit)
- Spill `%2.sub2_sub3` (64-bit subregister) in high-pressure region
- Use in a reachable-but-not-dominated block

**Expected Output:**
1. ✅ WWM-wrapped spill: `SI_SPILL_V64_SAVE` with EXEC save/restore
2. ✅ Flag PHI at merge point
3. ✅ Conditional branch: `S_CMP_EQ_U32 Flag, 0` → `S_CBRANCH_SCC1`
4. ✅ ReloadBB with WWM-wrapped reload
5. ✅ Value PHI merging reloaded and original values

---

## 10. Testing (continued)

### FileCheck Pattern (excerpt)

```llvm
; CHECK: bb.1:
; CHECK:   [[EXEC_SAVE_SPILL:%[0-9]+]]:sreg_32_xm0_xexec = COPY $exec_lo
; CHECK-NEXT:   $exec_lo = S_MOV_B32 -1
; CHECK-NEXT:   SI_SPILL_V64_SAVE `SPILLREG`.sub2_sub3, %stack.{{[0-9]+}}, $sgpr32, 0
; CHECK-NEXT:   $exec_lo = COPY `EXEC_SAVE_SPILL`
; CHECK:   [[SPILLPATH:%[0-9]+]]:sreg_32 = S_MOV_B32 1

; CHECK: bb.2.Flow:
; CHECK:   [[FLAG:%[0-9]+]]:sreg_32 = PHI `SPILLPATH`, %bb.1, [[CLEANPATH:%[0-9]+]], %bb.6

; CHECK: bb.4.bb2:
; CHECK:   S_CMP_EQ_U32 `FLAG`, 0, implicit-def $scc
; CHECK-NEXT:   S_CBRANCH_SCC1 %bb.8, implicit $scc

; CHECK: bb.7.bb2:
; CHECK:   [[EXEC_SAVE_RELOAD:%[0-9]+]]:sreg_32_xm0_xexec = COPY $exec_lo
; CHECK-NEXT:   $exec_lo = S_MOV_B32 -1
; CHECK-NEXT:   [[RELOAD:%[0-9]+]]:vreg_64 = SI_SPILL_V64_RESTORE %stack.{{[0-9]+}}, $sgpr32, 0
; CHECK-NEXT:   $exec_lo = COPY `EXEC_SAVE_RELOAD`

; CHECK: bb.8.bb2:
; CHECK:   [[VALUEPHI:%[0-9]+]]:vreg_64 = PHI `RELOAD`, %bb.7, `SPILLREG`.sub2_sub3, %bb.4
```

**Result:** ✅ **Test passes!**

---

## 11. Key Bugs Fixed During Implementation

1. ❌ **Incorrect Wave32 opcode** → ✅ Use `TRI->isWave32()` for `S_MOV_B32` vs `S_MOV_B64`
2. ❌ **CFG edge issue** → ✅ Correct conditional branch: `S_CMP_EQ_U32 Flag, 0; S_CBRANCH_SCC1 Post`
3. ❌ **SSA dominance failure** → ✅ Refactor: `emitReload()` + CFG transform + `repairSSAForReload()`
4. ❌ **Invalid iterator** → ✅ Query NUA at `std::next(I.getReverse())`
5. ❌ **Infinite reload loop** → ✅ Skip PHI instructions when collecting uses
6. ❌ **Over-spilling** → ✅ Reset `RemainingToSpill = 0` after larger subreg selected
7. ❌ **Immediate reload after spill** → ✅ Pass `TriggeringMI` to skip it in use collection
8. ❌ **Stale LiveIntervals** → ✅ Move `shrinkToUses()` to end of `emitReloadsAndRepairSSA()`
9. ❌ **Manual PHI type mismatch** → ✅ Delete manual PHI creation, rely on `MachineLaneSSAUpdater`
10. ❌ **Pass modification tracking** → ✅ Return `bool Changed` from `processFunction()`

---

## 3. Current Implementation Status

### ✅ Implemented Features

- [x] SSA-aware register spilling with Belady's algorithm
- [x] Subregister spilling (lane-level granularity)
- [x] WWM wrapping for divergent control flow
- [x] Split-before-use CFG transformation
- [x] Automatic PHI insertion via `MachineLaneSSAUpdater`
- [x] NextUseAnalysis with early-clobber handling
- [x] LiveIntervals and RPTracker integration
- [x] IDF caching in `MachineLaneSSAUpdater`
- [x] RP budget checking before reload insertion

### ⚠️ Known Limitations

- [ ] **Balanced spill not implemented** (always uses split-before-use)
- [ ] **No loop-aware candidate selection** (may spill loop-body candidates)
- [ ] **Premature decision making** (processes reachable uses immediately)
- [ ] **No hoisting cost model** (always uses closest reload placement)
- [ ] **No EWF implementation** (always uses WWM for divergent paths)

### 📊 Testing

- 6 LIT tests passing
- 1 test marked XFAIL (balanced spill not implemented)
- Comprehensive validation of WWM wrapping, PHI insertion, CFG transformation

---

## 13. Performance Considerations

### Register Pressure Reduction

- Spilling reduces VGPR pressure → increases occupancy
- Belady's next-use heuristic minimizes memory traffic

### WWM Overhead

- **2-3 SALU instructions** per spill/reload pair
- **Transient SGPR usage**: 1 SGPR live for ~3 instructions
- **Trade-off**: correctness + Belady optimality vs minor SGPR/SALU cost

### Split-Before-Use Overhead

- **1 extra basic block** per split
- **1 conditional branch** (SCC-based, minimal cost)
- **Benefit**: avoids redundant spills on clean paths

---

## 4. Design Evolution: Key Problems Identified

### Problem 1: Premature Decision Making

**Current Flow:**
```cpp
for (MachineInstr *UseMI : ReachableUses) {
  // Process immediately - NO complete path info!
  emitReload(...);
  handleUniformReachableUse(...);  // Always split-before-use
}
```

**Issues:**
- ❌ Decision made per-use without seeing all paths
- ❌ No information about clean paths (RP, length)
- ❌ Cannot make optimal balanced vs split decision
- ❌ Irreversible transformations (CFG split is permanent)

---

## 4. Design Evolution (continued)

### Problem 2: JoinBB ≠ UseBB

<div class="mermaid">
graph TD
    NCD["NCD"] --> SpillBB["SpillBB spill %0"]
    NCD --> CleanPath["CleanPath (no spill)"]
    SpillBB --> JoinBB["JoinBB (JOIN)"]
    CleanPath --> JoinBB
    JoinBB --> CommonCFG["Common CFG (100+ instructions) High RP!"]
    CommonCFG --> UseBB["UseBB use %0"]
    
    style JoinBB fill:#fff4e1,stroke:#ff9800,stroke-width:3px
    style SpillBB fill:#ffe1e1
    style CleanPath fill:#e1ffe1
    style CommonCFG fill:#ffe1e1,stroke:#f44336,stroke-width:2px
</div>

**Key Insight:**
- JoinBB (where paths merge) can be far from UseBB
- Common CFG (JoinBB → UseBB) has high RP → balanced spill wins!
- Decision must consider BOTH pre-join paths AND common CFG

---

## 4. Design Evolution (continued)

### Problem 3: Loop-Aware Spilling Missing

**Current Behavior:**
- Belady's algorithm favors long-distance uses
- But if use is in loop body → expensive!
- No preference for pre-header spillable candidates

**Required:**
- ✅ Penalize loop-body uses in distance calculation
- ✅ Prefer pre-header spillable candidates when inside loop
- ✅ Avoid placing reloads in loops at all costs

---

## 5. New Design: Deferred Reachable Use Processing

### Core Idea: Process at Join Points with Complete Info

<div class="mermaid">
graph TD
    NCD["NCD"] --> SpillBB["SpillBB spill %0"]
    NCD --> CleanPath["CleanPath RP: 6 Len: 20"]
    SpillBB --> BB10["bb.10 RP: 7 Len: 1"]
    CleanPath --> BB15["bb.15 RP: 6 Len: 1"]
    BB10 --> JoinBB["JoinBB (JOIN) MaxRP: 7 MaxLen: 20 → DECISION POINT"]
    BB15 --> JoinBB
    
    style JoinBB fill:#fff4e1,stroke:#ff9800,stroke-width:3px
    style SpillBB fill:#ffe1e1
    style CleanPath fill:#e1ffe1
</div>

**Workflow:**
1. When spill happens → rewrite dominated uses only
2. Defer reachable uses → `PendingReachableUses[JoinBB]`
3. When processing JoinBB in RPOT → all predecessors processed!
4. Aggregate metrics from all paths → complete information
5. Make decision: balanced vs split

---

## 5. Deferred Processing (continued)

### Path Tracking with RPOT

**RPOT Traversal:**
- Processes predecessors before block
- When we reach JoinBB → all paths already processed!

**Path Metrics Tracking:**
```cpp
struct PathMetrics {
  unsigned PathLength;  // From NCD to this block
  unsigned MaxRP;       // Max RP on path from NCD to this block
};

// Per-block metrics, aggregate from predecessors
DenseMap<MachineBasicBlock *, PathMetrics> BlockMetrics;
```

**At Join Point:**
```cpp
if (MBB->pred_size() > 1) {
  // Aggregate from all predecessors
  for (MachineBasicBlock *Pred : MBB->predecessors()) {
    MaxRP = std::max(MaxRP, BlockMetrics[Pred].MaxRP);
    MaxLen = std::max(MaxLen, BlockMetrics[Pred].PathLength);
  }
  // Now process pending reachable uses with complete info!
}
```

---

## 6. Balanced Spill vs Split-Before-Use Decision

### Decision Factors

**Pre-Join Paths (NCD → JoinBB):**
- Clean path length and RP
- If high RP → balanced spill helps clean paths

**Common CFG (JoinBB → UseBB):**
- Common CFG length and RP
- If high RP → balanced spill wins (reload at JoinBB helps)

**Heuristic:**
```cpp
bool ShouldBalancedSpill = 
  (avgRP_clean >= 0.8 * RPLimit && len_clean >= 50) ||
  (avgRP_common >= 0.8 * RPLimit && len_common >= 50);
```

**Key Clarification:**
- Balanced spill = spills on BOTH paths
- Reloads still follow standard dominated-use logic (closest to uses)
- NOT reloading at JoinBB!

---

## 6. Balanced Spill Illustration

<div class="mermaid">
graph TD
    NCD["NCD"] --> SpillBB["SpillBB spill %0"]
    NCD --> CleanPath["CleanPath RP: 8 (HIGH!) Len: 60"]
    SpillBB --> JoinBB["JoinBB (JOIN)"]
    CleanPath --> JoinBB
    JoinBB --> UseBB["UseBB use %0"]
    
    style JoinBB fill:#fff4e1,stroke:#ff9800,stroke-width:3px
    style SpillBB fill:#ffe1e1
    style CleanPath fill:#ffe1e1,stroke:#f44336,stroke-width:2px
    
    SpillBB -.->|"Balanced: Also spill here"| CleanPath
</div>

**Balanced Spill:**
- Insert spill on clean path BEFORE JoinBB
- Reloads follow standard dominated-use logic
- Reduces RP on clean path

**Split-Before-Use:**
- Only spill on spill path
- Conditional reload at use point
- Clean path keeps high RP

---

## 7. Hoisting Reloads to NCD

### Cost Model: When to Hoist?

**Two Options for Dominated Uses:**

1. **Separate reloads** (standard):
   - One reload per dom group, closest to uses
   - More reloads, but closer

2. **Hoist to NCD** (optimization):
   - Single reload at NCD, serves all uses
   - Fewer reloads, but further from uses

**Decision Factors:**
- Path length from NCD to uses
- Max RP on paths from NCD to uses

**Heuristic:**
```cpp
bool shouldHoistReloadToNCD(...) {
  if (MaxPathLength >= 50 || MaxRP >= 0.8 * RPLimit) {
    return false;  // Keep reloads closer to uses
  }
  return true;  // Hoisting profitable
}
```

---

## 7. Hoisting Illustration

<div class="mermaid">
graph TD
    NCD["NCD (Hoist reload here?)"] --> Path1["Path1 Len: 10 RP: 5"]
    NCD --> Path2["Path2 Len: 12 RP: 6"]
    Path1 --> Use1["Use1 use %0"]
    Path2 --> Use2["Use2 use %0"]
    
    style NCD fill:#e1f5ff,stroke:#2196F3,stroke-width:2px
    
    NCD -.->|"Option 1: Hoist 1 reload at NCD"| Use1
    NCD -.->|"Option 1: Hoist 1 reload at NCD"| Use2
    
    Path1 -->|"Option 2: Separate reloads closer"| Use1
    Path2 -->|"Option 2: Separate reloads closer"| Use2
</div>

**Decision:**
- If paths short AND RP low → hoist (fewer reloads)
- If paths long OR RP high → separate (reload early helps RP)

---

## 8. Loop-Aware Candidate Selection

### Problem: Belady Favors Loop-Body Uses

**Current Behavior:**
```cpp
// Belady's: longest distance first
if (DistA > DistB) {
  spill A;  // But A's use is in loop body!
}
```

**Solution: Penalize Loop-Body Uses**

```cpp
unsigned getEffectiveDistance(VRegMaskPair VMP, MachineInstr *MI) {
  unsigned Dist = NU->getNextUseDistance(MI, VMP);
  
  MachineInstr *NextUse = findNextUse(MI, VMP);
  if (MLI->getLoopFor(NextUse->getParent())) {
    Dist = Dist / 2;  // Heavy penalty for loop-body uses
  }
  
  return Dist;
}
```

**Also: Prefer Pre-Header Spillable Candidates**
```cpp
// Boost priority for candidates that can be spilled in pre-header
if (canSpillInPreHeader(A, MI) && !canSpillInPreHeader(B, MI)) {
  prefer A;  // Spill once in pre-header vs many times in loop
}
```

---

## 8. Loop-Aware Selection Illustration

<div class="mermaid">
graph TD
    PreHeader["Pre-Header (Execute once)"] --> LoopHeader["Loop Header"]
    LoopHeader --> LoopBody["Loop Body use %0 (Execute 1000x)"]
    LoopBody --> LoopHeader
    
    style PreHeader fill:#e1ffe1,stroke:#4CAF50,stroke-width:3px
    style LoopBody fill:#ffe1e1,stroke:#f44336,stroke-width:2px
    
    PreHeader -.->|"Preferred: Spill here"| Spill1["spill %0"]
    LoopBody -.->|"Avoid: Use in loop"| Use1["use %0"]
</div>

**Impact:**
- Pre-header spill executes once
- Loop-body use executes many times
- Prefer pre-header spillable candidates!

---

## 9. Implementation Plan: Phased Approach

### Phase 1: Loop-Aware Candidate Selection (Priority 1)

**Goal:** Avoid loop-body spilling at source

**Changes:**
- Add `getEffectiveDistance()` with loop penalty
- Add `canSpillInPreHeader()` check
- Modify `getVMPsToSpill()` sorting

**Estimated Effort:** 1-2 days

**Impact:** Reduces problematic cases for reload placement

---

## 9. Implementation Plan (continued)

### Phase 2: Deferred Reachable Use Processing (Priority 2)

**Goal:** Process reachable uses at join points with complete info

**Changes:**
- Add `PendingReachableUses` map
- Add `BlockMetrics` map for path tracking
- Modify `emitReloadsAndRepairSSA()` to defer reachable uses
- Add path metrics tracking in `processBlock()`
- Process pending uses at join points

**Estimated Effort:** 3-5 days

**Impact:** Enables optimal balanced vs split decisions

---

## 9. Implementation Plan (continued)

### Phase 3: Decision Logic & Balanced Spill (Priority 3)

**Goal:** Implement cost model and balanced spill

**Changes:**
- Add `decideStrategy()` function
- Add `insertBalancedSpill()` function
- Add `shouldHoistReloadToNCD()` cost model

**Estimated Effort:** 2-3 days

**Total Estimated Effort:** 6-10 days

---

## 10. Path Tracking Example

### Problem: Paths Merge Before Join

<div class="mermaid">
graph TD
    NCD["NCD"] --> SpillBB["SpillBB spill %0"]
    NCD --> CleanPath["CleanPath (no spill)"]
    SpillBB --> BB10["bb.10 PathLen: 1 RP: 7"]
    CleanPath --> BB15["bb.15 PathLen: 1 RP: 6"]
    BB10 --> BB20["bb.20 (MERGE) PathLen: 2 MaxRP: 7"]
    BB15 --> BB20
    BB20 --> JoinBB["JoinBB (JOIN) PathLen: 3 MaxRP: 7"]
    
    style BB20 fill:#fff4e1,stroke:#ff9800,stroke-width:2px
    style JoinBB fill:#fff4e1,stroke:#ff9800,stroke-width:3px
    style SpillBB fill:#ffe1e1
    style CleanPath fill:#e1ffe1
</div>

**Solution:**
- Track metrics per block (`BlockMetrics[MBB]`)
- Aggregate from all predecessors at join points
- Simple stack can't handle intermediate merges!

---

## 11. Updated Decision Table

| **Case** | **EXEC Modified** | **Strategy** | **Decision Point** |
|----------|-------------------|--------------|---------------------|
| Dominated use | No | Single dominating reload | Immediate |
| Not dominated, Uniform | No | **Split-before-use** OR **Balanced spill** | At JoinBB (deferred) |
| | | Split if: paths short AND RP low | |
| | | Balanced if: `avgRP_clean ≥ 0.8·RPLimit` OR `avgRP_common ≥ 0.8·RPLimit` | |
| Not dominated, Divergent | Yes | WWM spill+reload | At JoinBB (deferred) |
| | | Future: EWF if `f_ewf ≤ 0.25` | |

**Key Change:** Decisions made at JoinBB with complete path information!

---

## 12. Benefits of New Design

### ✅ Complete Information

- All paths processed before decision
- Metrics aggregated from all predecessors
- Optimal balanced vs split decision

### ✅ Loop Awareness

- Avoids loop-body spilling at source
- Prefers pre-header spillable candidates
- Reduces problematic cases

### ✅ Incremental Implementation

- Phase 1: Loop-aware selection (low risk)
- Phase 2: Deferred processing (medium risk)
- Phase 3: Decision logic (high risk, but with foundation)

### ✅ Works with Existing Code

- RPOT traversal already processes predecessors first
- No traversal order changes needed
- Minimal disruption to existing logic

---

## 13. Future Work

### 🔮 Planned Enhancements

1. **Phase 1**: Loop-aware candidate selection (this week)
2. **Phase 2**: Deferred reachable use processing (next week)
3. **Phase 3**: Balanced spill implementation (following week)
4. **EWF Implementation**: EXEC-Write Frontier analysis
5. **Cost Model Tuning**: Collect metrics from real workloads
6. **Path Analysis Caching**: Memoize path queries

---

## 14. Conclusion

### Summary

**Current Status:**
- ✅ Core spiller working (WWM, split-before-use, SSA repair)
- ⚠️ Missing: balanced spill, loop awareness, deferred processing

**Design Evolution:**
- Identified premature decision making problem
- Designed deferred processing with complete path info
- Added loop-aware candidate selection

**Next Steps:**
- Phase 1: Loop-aware candidate selection
- Phase 2: Deferred processing infrastructure
- Phase 3: Balanced spill implementation

---

## Questions?

**Thank you!**

---

## 15. Key Design Decisions Made

### Decision 1: Deferred Processing vs Immediate

**Chosen:** Deferred processing at join points
- ✅ Complete path information available
- ✅ Optimal balanced vs split decisions
- ✅ Works with existing RPOT traversal

### Decision 2: Per-Block Metrics vs Stack-Based

**Chosen:** Per-block metrics (`BlockMetrics[MBB]`)
- ✅ Handles intermediate path merges correctly
- ✅ Natural aggregation at join points
- ✅ Simpler than stack-based tracking

### Decision 3: Balanced Spill vs Split-Before-Use

**Decision Factors:**
- Pre-join paths: `avgRP_clean`, `len_clean`
- Common CFG: `avgRP_common`, `len_common`
- Heuristic: Balanced if either threshold exceeded

### Decision 4: Implementation Priority

**Chosen:** Loop-aware candidate selection first
- ✅ Lower risk, independent implementation
- ✅ Prevents problems at source
- ✅ Reduces complexity for reload placement

---

## 16. Related Work & References

### LLVM Infrastructure Used

- `MachineLaneSSAUpdater`: SSA repair with subregister lanes
- `LiveIntervals`: Live range tracking and updates
- `GCNUpwardRPTracker`: AMDGPU-specific register pressure tracking
- `SIRegisterInfo`: AMDGPU register class and wavefront queries

### Academic Background

- **Belady's Algorithm** (1966): Optimal page replacement → register spill selection
- **SSA Form** (Cytron et al., 1991): Static Single Assignment and PHI placement
- **Iterated Dominance Frontier**: Standard algorithm for PHI insertion points

---

## 16. Conclusion

### Summary

We implemented a **production-ready SSA register spiller** for AMDGPU that:

✅ **Correctly handles EXEC drift** via WWM wrapping  
✅ **Preserves SSA form** via automatic PHI insertion  
✅ **Optimizes placement** using dominance + EXEC analysis  
✅ **Supports subregisters** with lane-granular spilling  
✅ **Validates correctness** with comprehensive LIT tests  

### Impact

- Enables high occupancy for VGPR-intensive kernels
- Maintains correctness in presence of divergent control flow
- Provides foundation for advanced spill placement optimizations (EWF, cost model tuning)

---

## Questions?

**Thank you!**

---

### Appendix: Key Files

**Implementation:**
- `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp`
- `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.h`

**Testing:**
- `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-vreg-subregister.mir`

**Documentation:**
- `NOTES.md` (technical diary)
- `WEEKLY_REPORT_2025-10-27_to_30.md`
- This presentation: `SSA_Spiller_Presentation.md`

---

### Appendix: Commands to Build & Test

**Build the spiller:**
```bash
cd /work/atimofee/sandbox/github/llvm-project/build/Debug
ninja AMDGPUCodeGen
```

**Run the test:**
```bash
bin/llvm-lit -v ../../llvm/test/CodeGen/AMDGPU/SSASpiller/spill-vreg-subregister.mir
```

**Convert to PowerPoint:**
```bash
# Install Marp CLI
npm install -g @marp-team/marp-cli

# Generate PPTX
marp SSA_Spiller_Presentation.md --pptx -o SSA_Spiller_Presentation.pptx
```

