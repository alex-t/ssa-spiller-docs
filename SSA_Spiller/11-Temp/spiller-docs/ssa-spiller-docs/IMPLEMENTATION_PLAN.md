# Spill Placement Design - Summary & Implementation Plan

## Design Summary

### Core Problem
Current implementation makes **split-before-use vs balanced spill** decisions prematurely when processing the first reachable use, without complete information about alternative paths. This leads to suboptimal decisions and irreversible transformations.

### Key Insights

1. **JoinBB ≠ UseBB**: Join point (IDF block) can be far from use point
2. **Common CFG Matters**: JoinBB → UseBB has high RP → balanced spill wins (reload at JoinBB helps)
3. **Pre-Join Paths Matter**: NCD → JoinBB paths determine if clean paths benefit from spilling
4. **Loop Avoidance Critical**: Must avoid placing spill/reload inside loops at all costs
5. **RPOT is Perfect**: Current RPOT traversal already processes predecessors before block → complete info at joins

### Design Approach: Deferred Reachable Use Processing

**Workflow:**
1. **When spill happens**: Rewrite dominated uses only (standard logic)
2. **For each reachable use**: Defer to map `{JoinBB → {SpillBB, UseMI, ...}}`
3. **When processing blocks in RPOT**: Check if block is join point (`pred_size() > 1`)
4. **At join point**: Process all deferred reachable uses with complete path info

**Path Tracking:**
- Track `(PathLength, MaxRP)` per block (`BlockMetrics[MBB]`)
- When processing join in RPOT, aggregate from all predecessors
- Complete information available for decision making

## Implementation Priority Decision

### Option A: Spill Candidate Election First (RECOMMENDED)

**Pros:**
- ✅ **Simpler**: Lower risk, independent implementation
- ✅ **Prevents problems at source**: Avoids loop-body spilling upfront
- ✅ **Reduces complexity**: Fewer problematic cases for reload placement
- ✅ **Testable independently**: Can verify loop-aware selection works
- ✅ **Incremental**: Can deploy without changing reload logic

**Cons:**
- ⚠️ Doesn't solve the core deferred processing problem
- ⚠️ Reload placement still needs fixing later

**Impact:**
- Reduces cases where reload placement needs to handle loop-body spills
- Makes reload placement design simpler (fewer edge cases)

### Option B: Reload Placement First

**Pros:**
- ✅ **Solves core problem**: Deferred processing with complete info
- ✅ **More impactful**: Fixes the main design issue
- ✅ **Enables balanced spill**: Can make optimal decisions

**Cons:**
- ⚠️ **More complex**: Requires path tracking, metrics aggregation
- ⚠️ **Higher risk**: Changes core spiller logic
- ⚠️ **More testing**: Need to verify all CFG patterns work
- ⚠️ **Still need loop handling**: Loop-body cases still problematic

**Impact:**
- Fixes the main design flaw
- But still needs loop-aware candidate selection later

## Recommendation: Spill Candidate Election First

**Rationale:**
1. **Lower risk**: Simpler changes, easier to test
2. **Foundation**: Better candidates → simpler reload placement
3. **Incremental**: Can deploy independently, measure impact
4. **Reduces complexity**: Fewer edge cases for reload placement to handle

**Then Reload Placement:**
- After candidate selection is proven, tackle deferred processing
- Simpler because fewer loop-body cases to handle

## Implementation Plan

### Phase 1: Loop-Aware Spill Candidate Selection (Priority 1)

**Goal:** Avoid selecting candidates whose next use is in a loop body, prefer pre-header spillable candidates.

**Changes:**

1. **Add `getEffectiveDistance()` with loop penalty:**
   ```cpp
   unsigned getEffectiveDistance(VRegMaskPair VMP, MachineInstr *CurrentMI) {
     unsigned Dist = NU->getNextUseDistance(CurrentMI, VMP);
     
     MachineInstr *NextUse = findNextUse(CurrentMI, VMP);
     if (!NextUse)
       return Dist;
     
     MachineBasicBlock *UseBB = NextUse->getParent();
     if (MLI->getLoopFor(UseBB)) {
       // Penalize loop-body uses: reduce effective distance
       Dist = Dist / 2;  // Heavy penalty - tune based on benchmarks
     }
     
     return Dist;
   }
   ```

2. **Add `canSpillInPreHeader()` check:**
   ```cpp
   bool canSpillInPreHeader(VRegMaskPair VMP, MachineInstr *CurrentMI) {
     MachineBasicBlock *CurrentBB = CurrentMI->getParent();
     const MachineLoop *Loop = MLI->getLoopFor(CurrentBB);
     if (!Loop)
       return false;
     
     MachineBasicBlock *PreHeader = Loop->getLoopPreheader();
     if (!PreHeader)
       return false;
     
     // Check if VMP is live at pre-header entry
     // AND not used between pre-header and CurrentMI
     return isLiveAtPreHeader(VMP, PreHeader) && 
            !hasUseBetween(PreHeader, CurrentBB, VMP);
   }
   ```

3. **Modify `getVMPsToSpill()` sorting:**
   ```cpp
   Active.sort([&](const VRegMaskPair &A, const VRegMaskPair &B) {
     // Prefer pre-header spillable candidates
     bool ACanPreHeader = canSpillInPreHeader(A, MI);
     bool BCanPreHeader = canSpillInPreHeader(B, MI);
     if (ACanPreHeader != BCanPreHeader)
       return ACanPreHeader;  // A first if it can be spilled in pre-header
     
     // Otherwise use effective distance (with loop penalty)
     unsigned DistA = getEffectiveDistance(A, MI);
     unsigned DistB = getEffectiveDistance(B, MI);
     return DistA < DistB;
   });
   ```

**Files to Modify:**
- `AMDGPUSSARegisterSpiller.cpp`: `getVMPsToSpill()` (lines 352-401)
- Add helper functions: `getEffectiveDistance()`, `canSpillInPreHeader()`

**Testing:**
- Create test with loop-body uses → verify they're penalized
- Create test with pre-header spillable candidates → verify they're preferred
- Measure impact on existing tests (should not regress)

**Estimated Effort:** 1-2 days

---

### Phase 2: Deferred Reachable Use Processing (Priority 2)

**Goal:** Process reachable uses at join points with complete path information.

**Changes:**

1. **Add data structures:**
   ```cpp
   struct ReachableUseInfo {
     MachineInstr *SpillMI;
     MachineInstr *UseMI;
     MachineBasicBlock *SpillBB;
     MachineBasicBlock *JoinBB;
     // Path metrics (filled when processing join)
     unsigned MaxPathLength;
     unsigned MaxRP;
   };
   
   DenseMap<MachineBasicBlock *, SmallVector<ReachableUseInfo>> PendingReachableUses;
   DenseMap<MachineBasicBlock *, PathMetrics> BlockMetrics;
   
   struct PathMetrics {
     unsigned PathLength;  // From NCD to this block
     unsigned MaxRP;       // Max RP on path from NCD to this block
   };
   ```

2. **Modify `emitReloadsAndRepairSSA()`:**
   - Handle dominated uses immediately (existing logic)
   - **Defer** reachable uses to their join points
   - Store in `PendingReachableUses[JoinBB]`

3. **Add path metrics tracking in `processBlock()`:**
   ```cpp
   void processBlock(MachineBasicBlock *MBB) {
     // Aggregate metrics from predecessors
     PathMetrics Aggregated;
     if (MBB->pred_size() > 1) {
       // Join point - aggregate from all predecessors
       for (MachineBasicBlock *Pred : MBB->predecessors()) {
         PathMetrics PredMetrics = BlockMetrics[Pred];
         Aggregated.MaxRP = std::max(Aggregated.MaxRP, PredMetrics.MaxRP);
         Aggregated.PathLength = std::max(Aggregated.PathLength, PredMetrics.PathLength);
       }
     } else if (MBB->pred_size() == 1) {
       // Single predecessor - continue path
       MachineBasicBlock *Pred = *MBB->pred_begin();
       PathMetrics PredMetrics = BlockMetrics[Pred];
       Aggregated = PredMetrics;
       Aggregated.PathLength += MBB->size();
     }
     
     // Update RP for current block
     updateRPForBlock(MBB, Aggregated);
     
     // Check if this is a join with pending uses
     if (MBB->pred_size() > 1 && PendingReachableUses.count(MBB)) {
       processPendingReachableUses(MBB, Aggregated);
     }
     
     // Store metrics for this block
     BlockMetrics[MBB] = Aggregated;
     
     // Process instructions (spilling, etc.)
     processInstructions(MBB);
   }
   ```

4. **Add `processPendingReachableUses()`:**
   ```cpp
   void processPendingReachableUses(MachineBasicBlock *JoinBB, PathMetrics Aggregated) {
     auto &PendingUses = PendingReachableUses[JoinBB];
     
     for (ReachableUseInfo &Info : PendingUses) {
       // Now we have complete path info:
       // - MaxPathLength: from NCD to JoinBB
       // - MaxRP: max RP on any path to JoinBB
       
       // Make decision: balanced vs split
       Strategy Strategy = decideStrategy(Info, Aggregated);
       
       // Apply transformation
       applyStrategy(Strategy, Info);
     }
     
     PendingReachableUses.erase(JoinBB);
   }
   ```

**Files to Modify:**
- `AMDGPUSSARegisterSpiller.h`: Add data structures
- `AMDGPUSSARegisterSpiller.cpp`: 
  - `emitReloadsAndRepairSSA()`: Defer reachable uses
  - `processFunction()`: Add path metrics tracking
  - Add `processPendingReachableUses()`

**Testing:**
- Test with diamond CFG → verify deferred processing works
- Test with multiple joins → verify each join processed correctly
- Test with loops → verify metrics tracked correctly
- Measure impact on existing tests

**Estimated Effort:** 3-5 days

---

### Phase 3: Decision Logic & Balanced Spill (Priority 3)

**Goal:** Implement cost model for balanced vs split decision, implement balanced spill.

**Changes:**

1. **Add `decideStrategy()` function:**
   ```cpp
   Strategy decideStrategy(const ReachableUseInfo &Info, const PathMetrics &Aggregated) {
     // Heuristic from paper (section 6.2)
     bool CleanPathsBenefit = 
       (Aggregated.MaxRP >= 0.8 * RPLimit) &&
       (Aggregated.PathLength >= 50);
     
     // TODO: Add common CFG analysis (JoinBB → UseBB)
     
     if (CleanPathsBenefit) {
       return Strategy::BALANCED_SPILL;
     }
     
     return Strategy::SPLIT_BEFORE_USE;
   }
   ```

2. **Add `insertBalancedSpill()` function:**
   - Insert spills on clean paths BEFORE JoinBB
   - Reloads follow standard dominated-use logic (closest to uses)
   - Handle SSA correctly

3. **Add hoisting cost model (`shouldHoistReloadToNCD()`):**
   - For dominated uses, decide if reload should be hoisted to NCD
   - Check path length and max RP

**Files to Modify:**
- `AMDGPUSSARegisterSpiller.cpp`: Add decision logic and balanced spill implementation

**Testing:**
- Test balanced spill decision → verify spills on both paths
- Test hoisting decision → verify reload placement
- Measure performance impact

**Estimated Effort:** 2-3 days

---

## Summary

**Recommended Order:**
1. **Phase 1** (Spill Candidate Election) - 1-2 days
2. **Phase 2** (Deferred Processing) - 3-5 days  
3. **Phase 3** (Decision Logic) - 2-3 days

**Total Estimated Effort:** 6-10 days

**Key Benefits:**
- Incremental approach: each phase can be tested independently
- Lower risk: simpler changes first
- Foundation: better candidates → simpler reload placement
- Complete solution: addresses all design requirements

**Questions to Resolve:**
1. Should we start with Phase 1 (candidate election)?
2. Any concerns about the implementation plan?
3. Should we create detailed design docs for each phase before implementation?






