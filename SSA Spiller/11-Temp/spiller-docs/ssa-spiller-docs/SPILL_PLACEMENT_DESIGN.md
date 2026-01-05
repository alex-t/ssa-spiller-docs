# Spill Placement Strategy Decision Design

## Problem Statement

Current implementation makes **split-before-use vs balanced spill** decisions prematurely when processing the first reachable use, without complete information about alternative paths. This leads to:

1. **Suboptimal decisions**: Choosing split-before-use when balanced spill would be better
2. **Irreversible transformations**: Once CFG is split, rolling back is extremely difficult
3. **Incomplete analysis**: Decision made per-use without seeing all paths to join points

## Current Flow Analysis

### Current Implementation (Lines 806-879 in AMDGPUSSARegisterSpiller.cpp)

```cpp
// Step 4: Handle reachable uses
for (MachineInstr *UseMI : ReachableUses) {
  // 1. Emit reload immediately
  MachineInstr *ReloadMI = emitReload(UseMI->getIterator(), SpilledVMP);
  
  // 2. Classify as uniform/divergent
  bool IsDivergent = pathsHaveDivergence(NCD, SpillMI, UseMI);
  
  // 3. Apply transformation immediately (COMMITTED!)
  if (IsDivergent) {
    handleDivergentReachableUse(...);  // Always split-before-use + WWM
  } else {
    handleUniformReachableUse(...);   // Always split-before-use
  }
  
  // 4. Repair SSA
  repairSSAForReload(ReloadMI, SpilledVMP);
}
```

**Problems:**
- Each use processed independently
- Transformation applied immediately (no rollback)
- No global view of all paths
- Balanced spill never considered (TODO at line 1561-1564)

## Key Insight: Join Block vs Use Block

**Critical Understanding:**
- **JoinBB** (IDF block): Where spill path and clean paths merge
- **UseBB**: Where the use happens (can be much later)
- **Common CFG**: JoinBB → ... → UseBB (dominated by JoinBB)

**Decision Scope:**
The decision between split-before-use vs balanced spill should consider:
1. **Pre-join paths** (NCD → JoinBB):
   - Path from NCD to SpillBB (spill path)
   - Paths from NCD to JoinBB that DON'T go through SpillBB (clean paths)
2. **Common CFG** (JoinBB → UseBB):
   - The dominated section after paths merge
   - **Important**: If common CFG has high RP, balanced spill wins (reload at JoinBB helps reduce RP in common CFG)

**CFG Structure:**
```
NCD
 |    \
 |   SpillBB (spill happens here)
 |      /
 |  CleanPath (alternative path)
 |      /
JoinBB ← DECISION POINT: analyze paths BEFORE here AND common CFG after
 |
 |  (common CFG - dominated by JoinBB, BUT relevant if high RP!)
 |
UseBB (use happens here)
```

## Critical Design Consideration: Loop-Aware Spilling

**Fundamental Requirement:**
- **Avoid placing spill/reload inside loops at any cost**
- Loops execute many times → spill/reload overhead multiplies
- Must consider loop structure in ALL decisions

**Impact on Spill Candidate Selection:**
1. **Avoid candidates used far away but in loop body**
   - Belady's algorithm favors long-distance uses
   - But if that use is in a loop, it's expensive!
   - Need to penalize loop-body uses in distance calculation

2. **Prefer pre-header spilling when inside loop**
   - If RP exceeds limit inside loop, prefer candidates that can be spilled in pre-header
   - Pre-header executes once → spill cost is amortized
   - Need to detect which candidates are safe to spill in pre-header

**Impact on Balanced vs Split Decision:**
- **Balanced spill**: Insert spills on BOTH paths (spill path AND clean paths)
  - Reloads follow standard dominated-use logic (closest to uses, dom groups)
  - **NOT** reloading at JoinBB!
- **Split-before-use**: Insert spill on ONE path only, reload conditionally at use
  - Creates conditional reload CFG
- Need to detect loop structure to avoid placing reloads in loops

**Key Clarification:**
- Balanced spill vs split-before-use is about **WHERE TO SPILL** (both paths vs one path)
- **NOT** about where to reload - reloads always follow standard dominated-use placement
- Exception: Cost model for hoisting reloads to NCD (see below)

**Loop Detection Requirements:**
- Need `MachineLoopInfo` to detect:
  - Is a block inside a loop?
  - What is the loop pre-header?
  - Is JoinBB inside a loop?
  - Is UseBB inside a loop?
  - Is common CFG (JoinBB → UseBB) inside a loop?

## Cost Model: Hoisting Reloads to NCD

**Problem:**
For uses dominated by JoinBB (or any common dominator), we have two options:
1. **Separate reloads on each path** (standard dominated-use logic)
   - One reload per dom group, placed closest to uses
   - More reloads, but closer to uses
2. **Hoist reload to NCD** (single reload for all paths)
   - One reload at NCD, serves all uses
   - Fewer reloads, but further from uses

**Decision Factors:**

1. **Path length from NCD to uses**
   - If paths are long → don't hoist (keep reloads closer to uses)
   - If paths are short → hoisting may be profitable

2. **Max RP on paths from NCD to uses**
   - If RP is high on any path → don't hoist (reload early = helps reduce RP)
   - If RP is low on all paths → hoisting may be profitable

**Heuristic:**
```cpp
bool shouldHoistReloadToNCD(
    MachineBasicBlock *NCD,
    const SmallVectorImpl<MachineInstr *> &DominatedUses,
    VRegMaskPair SpilledVMP) {
  
  // Collect metrics for all paths from NCD to uses
  unsigned MaxPathLength = 0;
  unsigned MaxRP = 0;
  
  for (MachineInstr *UseMI : DominatedUses) {
    MachineBasicBlock *UseBB = UseMI->getParent();
    
    // Analyze path from NCD to UseBB
    PathMetrics Path = analyzePathMetrics(NCD, UseBB, SpilledVMP, UseMI);
    MaxPathLength = std::max(MaxPathLength, Path.InstructionCount);
    MaxRP = std::max(MaxRP, Path.MaxRP);
  }
  
  // Don't hoist if:
  // 1. At least one path is long (reload far from use)
  // 2. At least one path has high RP (reload early helps reduce RP)
  if (MaxPathLength >= 50 || MaxRP >= 0.8 * RPLimit) {
    return false;  // Keep reloads closer to uses
  }
  
  // Otherwise, hoisting may be profitable
  return true;
}
```

**Implementation:**
- This cost model applies to **dominated uses** (not reachable uses)
- Check before grouping uses into dom groups
- If hoisting is profitable, place reload at NCD instead of per-group placement
- Still need to handle SSA correctly (PHIs may still be needed)

## Design Options

### Option 1: Two-Phase Analysis + Transformation (Recommended)

**Phase 1: Analysis Pass**
- Collect all reachable uses
- For each use, find JoinBB (IDF block that dominates UseBB)
- **Detect loop structure:**
  - Is JoinBB inside a loop? (if yes, reload at JoinBB = reload in loop!)
  - Is UseBB inside a loop? (if yes, reload at UseBB = reload in loop!)
  - Is common CFG (JoinBB → UseBB) inside a loop?
  - What is the loop pre-header? (for pre-header spilling)
- **Analyze PRE-JOIN paths** (NCD → JoinBB):
  - Path from NCD to SpillBB (spill path)
  - Paths from NCD to JoinBB that don't go through SpillBB (clean paths)
  - **Loop-aware**: Detect if paths go through loops
- **Analyze COMMON CFG** (JoinBB → UseBB):
  - The dominated section after paths merge
  - Important for RP analysis!
  - **Loop-aware**: Detect if common CFG is inside a loop
- Collect metrics:
  - **Pre-join paths:**
    - `len_path`: Instruction count on path (NCD → JoinBB)
    - `avgRP_path`: Average register pressure (or estimate)
    - `hasUseOnPath`: Whether spilled register is used on path (before JoinBB)
    - `goesThroughLoop`: Whether path goes through a loop
  - **Common CFG:**
    - `len_common`: Instruction count on common CFG (JoinBB → UseBB)
    - `avgRP_common`: Average RP on common CFG (JoinBB → UseBB)
    - `isInLoop`: Whether common CFG is inside a loop
  - **Loop structure:**
    - `joinBBInLoop`: Is JoinBB inside a loop?
    - `useBBInLoop`: Is UseBB inside a loop?
    - `preHeader`: Loop pre-header (if applicable)
- Group uses by join point (JoinBB)

**Phase 2: Decision Pass**
- For each join point (JoinBB):
  - Identify spill path vs clean paths (all paths from NCD to JoinBB)
  - Compute metrics:
    - **Pre-join paths:**
      - `len_clean`: Max instruction count on clean paths (NCD → JoinBB)
      - `avgRP_clean`: Average RP on clean paths (NCD → JoinBB)
      - `cleanPathsInLoop`: Do clean paths go through loops?
    - **Common CFG:**
      - `len_common`: Instruction count on common CFG (JoinBB → UseBB)
      - `avgRP_common`: Average RP on common CFG (JoinBB → UseBB)
      - `commonCFGInLoop`: Is common CFG inside a loop?
    - **Loop structure:**
      - `joinBBInLoop`: Is JoinBB inside a loop?
      - `useBBInLoop`: Is UseBB inside a loop?
  - Apply heuristics for balanced spill decision:
    ```cpp
    // Balanced spill wins if:
    // 1. Clean paths have high RP (spill helps clean paths)
    // 2. Common CFG has high RP (spills on both paths help reduce RP in common CFG)
    // Note: Reloads still follow standard dominated-use logic (closest to uses)
    bool ShouldBalancedSpill = 
      (avgRP_clean >= 0.8 * RPLimit && len_clean >= 50) ||
      (avgRP_common >= 0.8 * RPLimit && len_common >= 50);
    ```

**Phase 3: Transformation Pass**
- Apply chosen strategy globally for all uses at this join
- **Balanced**: Insert spills on clean paths BEFORE JoinBB
  - Reloads follow standard dominated-use logic (closest to uses, dom groups)
  - **NOT** reloading at JoinBB - reloads are placed as close to uses as possible
  - **Loop-aware**: Avoid placing reloads in loops (standard dominated-use logic handles this)
- **Split**: Create conditional reload CFG (reload at UseBB, conditional on flag)
  - Reload happens at use point, doesn't help with RP in common CFG
  - **Loop-aware**: If UseBB is in loop, prefer pre-header reload if possible

**Pros:**
- Complete information before decision
- Can optimize globally across all uses
- Clear separation of concerns

**Cons:**
- More complex implementation
- Requires buffering analysis results
- Three passes instead of one

### Option 2: Improved Per-Use Heuristics (Simpler)

Keep current per-use processing but improve heuristics:

```cpp
for (MachineInstr *UseMI : ReachableUses) {
  // Find JoinBB (IDF block that dominates UseBB)
  MachineBasicBlock *JoinBB = findJoinBB(SpillBB, UseBB, IDFBlocks);
  
  // Analyze clean paths BEFORE JoinBB (NCD → JoinBB, avoiding SpillBB)
  PathMetrics CleanMetrics = analyzeCleanPaths(NCD, SpillBB, JoinBB);
  
  // Analyze common CFG AFTER JoinBB (JoinBB → UseBB)
  PathMetrics CommonMetrics = analyzeCommonCFG(JoinBB, UseBB);
  
  // Make decision with better heuristics (considering both pre-join and common CFG)
  if (shouldBalancedSpill(CleanMetrics, CommonMetrics)) {
    // Insert spill on clean path BEFORE JoinBB, reload at JoinBB
    // Reloaded value helps reduce RP in common CFG
    insertBalancedSpill(..., JoinBB);
  } else {
    // Split-before-use (reload at UseBB, conditional on flag from JoinBB)
    splitBlockBeforeReload(..., JoinBB);
  }
}
```

**Pros:**
- Minimal changes to current code
- Still processes uses independently
- Can be implemented incrementally

**Cons:**
- Still makes decisions without full picture
- May miss global optimizations
- Heuristics may be suboptimal

### Option 3: Deferred Decision with Buffering

Buffer transformation decisions, apply after all analysis:

```cpp
struct PendingTransformation {
  MachineInstr *UseMI;
  MachineInstr *ReloadMI;
  PathMetrics Metrics;
  Strategy Decision;  // PENDING, not applied yet
};

SmallVector<PendingTransformation> Pending;

// Analysis phase
for (MachineInstr *UseMI : ReachableUses) {
  PathMetrics Metrics = analyzePaths(...);
  Pending.push_back({UseMI, ReloadMI, Metrics, Strategy::PENDING});
}

// Decision phase (after all analysis)
makeGlobalDecisions(Pending);

// Transformation phase
for (auto &Pending : Pending) {
  applyTransformation(Pending);
}
```

**Pros:**
- Can revise decisions after seeing all uses
- Still processes uses independently initially
- More flexible than Option 1

**Cons:**
- Requires buffering infrastructure
- More complex than Option 2
- May still miss some global optimizations

## Recommended Approach: Hybrid (Option 1 + Incremental)

### Phase 1: Group Uses by Join Point

```cpp
// Group reachable uses by their join point (IDF block)
DenseMap<MachineBasicBlock *, SmallVector<MachineInstr *>> UsesByJoin;

for (MachineInstr *UseMI : ReachableUses) {
  MachineBasicBlock *JoinBB = findJoinBB(SpillBB, UseMI->getParent(), IDFBlocks);
  UsesByJoin[JoinBB].push_back(UseMI);
}
```

### Phase 2: Analyze Paths Per Join

```cpp
for (auto &[JoinBB, Uses] : UsesByJoin) {
  // Analyze all paths to this join
  PathAnalysis Analysis = analyzePathsToJoin(SpillBB, JoinBB, SpilledVMP);
  
  // Make decision for this join
  Strategy Strategy = decideStrategy(Analysis);
  
  // Apply transformation for all uses at this join
  applyStrategy(Strategy, Uses, Analysis);
}
```

### Path Analysis Structure

```cpp
struct PathAnalysis {
  MachineBasicBlock *NCD;      // Nearest common dominator
  MachineBasicBlock *SpillBB;   // Where spill happens
  MachineBasicBlock *JoinBB;    // Where paths merge (IDF block)
  MachineBasicBlock *UseBB;     // Where use happens (for common CFG analysis)
  
  // Clean paths: NCD → JoinBB (avoiding SpillBB)
  SmallVector<PathMetrics> CleanPaths;
  
  // Spill path: NCD → SpillBB → JoinBB
  PathMetrics SpillPath;
  
  // Metrics aggregated across clean paths (PRE-JOIN)
  unsigned MaxLenClean;         // Max instruction count on clean paths (NCD → JoinBB)
  unsigned AvgRPClean;         // Average RP on clean paths (NCD → JoinBB)
  bool CleanPathsInLoop;        // Do clean paths go through loops?
  
  // Metrics for common CFG (POST-JOIN)
  unsigned LenCommon;           // Instruction count on common CFG (JoinBB → UseBB)
  unsigned AvgRPCommon;        // Average RP on common CFG (JoinBB → UseBB)
  bool CommonCFGInLoop;         // Is common CFG inside a loop?
  
  // Loop structure
  bool JoinBBInLoop;            // Is JoinBB inside a loop?
  bool UseBBInLoop;             // Is UseBB inside a loop?
  MachineBasicBlock *PreHeader; // Loop pre-header (if JoinBB/UseBB in loop)
  
  // Note: Common CFG is dominated by JoinBB, but still relevant for RP analysis!
  //       If common CFG has high RP, balanced spill (spills on both paths) wins
  //       Reloads follow standard dominated-use logic (closest to uses, NOT at JoinBB!)
};
```

### Decision Heuristics

```cpp
Strategy decideStrategy(const PathAnalysis &Analysis) {
  // Heuristic from paper (section 6.2), extended for common CFG
  
  // Balanced spill wins if:
  // 1. Clean paths have high RP (spill helps clean paths)
  bool CleanPathsBenefit = 
    (Analysis.AvgRPClean >= 0.8 * RPLimit) &&
    (Analysis.MaxLenClean >= 50);
  
  // 2. Common CFG has high RP (spills on both paths help reduce RP in common CFG)
  bool CommonCFGBenefits = 
    (Analysis.AvgRPCommon >= 0.8 * RPLimit) &&
    (Analysis.LenCommon >= 50);
  
  if (CleanPathsBenefit || CommonCFGBenefits) {
    return Strategy::BALANCED_SPILL;
  }
  
  // Default: split-before-use
  return Strategy::SPLIT_BEFORE_USE;
  
  // Note: Loop avoidance is handled separately in reload placement logic
  // (standard dominated-use logic avoids placing reloads in loops)
}
```

## Spill Candidate Selection: Loop-Aware Belady's Algorithm

**Current Belady's Algorithm** (`getVMPsToSpill`):
- Selects candidates by next-use distance (longest distance first)
- Doesn't consider loop structure

**Required Changes:**

1. **Penalize Loop-Body Uses:**
   ```cpp
   unsigned getEffectiveDistance(VRegMaskPair VMP, MachineInstr *CurrentMI) {
     unsigned Dist = NU->getNextUseDistance(CurrentMI, VMP);
     
     // Find the next use instruction
     MachineInstr *NextUse = findNextUse(CurrentMI, VMP);
     if (!NextUse)
       return Dist;
     
     // Check if next use is in a loop
     MachineBasicBlock *UseBB = NextUse->getParent();
     if (MLI->getLoopFor(UseBB)) {
       // Penalize: reduce effective distance for loop-body uses
       // This makes them less attractive for spilling
       Dist = Dist / 2;  // Or use more sophisticated penalty
     }
     
     return Dist;
   }
   ```

2. **Prefer Pre-Header Spillable Candidates:**
   ```cpp
   bool canSpillInPreHeader(VRegMaskPair VMP, MachineInstr *CurrentMI) {
     // Check if CurrentMI is inside a loop
     MachineBasicBlock *CurrentBB = CurrentMI->getParent();
     const MachineLoop *Loop = MLI->getLoopFor(CurrentBB);
     if (!Loop)
       return false;  // Not in loop, no pre-header
     
     MachineBasicBlock *PreHeader = Loop->getLoopPreheader();
     if (!PreHeader)
       return false;  // No pre-header (irreducible loop?)
     
     // Check if VMP is live at pre-header entry
     // AND not used between pre-header and CurrentMI
     // (simplified check - full analysis needed)
     return isLiveAtPreHeader(VMP, PreHeader) && 
            !hasUseBetween(PreHeader, CurrentBB, VMP);
   }
   
   // In getVMPsToSpill, boost priority for pre-header spillable candidates
   Active.sort([&](const VRegMaskPair &A, const VRegMaskPair &B) {
     bool ACanPreHeader = canSpillInPreHeader(A, MI);
     bool BCanPreHeader = canSpillInPreHeader(B, MI);
     
     // Prefer pre-header spillable candidates
     if (ACanPreHeader != BCanPreHeader)
       return ACanPreHeader;  // A first if it can be spilled in pre-header
     
     // Otherwise use standard distance-based sorting
     unsigned DistA = getEffectiveDistance(A, MI);
     unsigned DistB = getEffectiveDistance(B, MI);
     return DistA < DistB;
   });
   ```

**Key Insight:**
- Loop-aware candidate selection happens BEFORE path analysis
- If we avoid selecting loop-body candidates, we reduce the need for loop-aware path analysis
- But we still need loop-aware path analysis for cases where loop-body candidates are unavoidable

**Separate Concern: Hoisting Reloads to NCD**
- This is a different optimization from balanced vs split decision
- Applies to dominated uses (uses dominated by JoinBB or any common dominator)
- Cost model: hoist if paths are short AND RP is low
- Standard dominated-use logic handles loop avoidance automatically

## Implementation Plan

### Step 0: Add Loop-Aware Candidate Selection (High Priority)

**Before path analysis, improve spill candidate selection:**
- Add `getEffectiveDistance()` with loop penalty
- Add `canSpillInPreHeader()` check
- Modify `getVMPsToSpill()` to prefer pre-header spillable candidates
- **Impact**: Reduces cases where we need loop-aware path analysis

### Step 1: Extract Path Analysis (Low Risk)

Create `analyzePathsToJoin()` function:
- Takes NCD, SpillBB, JoinBB, UseBB, SpilledVMP, MLI (MachineLoopInfo)
- Analyzes paths BEFORE JoinBB:
  - Spill path: NCD → SpillBB → JoinBB
  - Clean paths: NCD → JoinBB (avoiding SpillBB)
  - **Loop detection**: Check if paths go through loops
- Analyzes common CFG AFTER JoinBB:
  - Common CFG: JoinBB → UseBB
  - **Loop detection**: Check if common CFG is inside a loop
- Detects loop structure:
  - Is JoinBB inside a loop?
  - Is UseBB inside a loop?
  - What is the loop pre-header?
- Returns PathAnalysis struct with both PRE-JOIN and COMMON CFG metrics + loop info
- Can be tested independently
- Doesn't change current behavior yet (loop checks return false initially)

### Step 2: Group Uses by Join (Low Risk)

Modify `emitReloadsAndRepairSSA()` to group uses:
- Collect all reachable uses first
- Group by join point
- Process groups instead of individual uses
- Still applies same transformations (no behavior change)

### Step 3: Add Decision Logic (Medium Risk)

Add `decideStrategy()` function:
- Takes PathAnalysis
- Returns Strategy enum
- Initially returns SPLIT_BEFORE_USE (preserves current behavior)
- Can be enhanced incrementally

**Separate: Add Hoisting Cost Model**
- Add `shouldHoistReloadToNCD()` function
- Takes NCD, dominated uses, SpilledVMP
- Returns bool: should we hoist reload to NCD?
- Checks path length and max RP
- Initially returns false (preserves current behavior)

### Step 4: Implement Balanced Spill (High Risk)

Add `insertBalancedSpill()` function:
- Inserts spill on clean paths
- Inserts reload at join point
- Updates SSA correctly
- Requires careful testing

## Metrics Collection

### Current: `hasUseOnPath()` (Line 1276)

Already walks paths, but only returns boolean. Can extend to collect metrics:

```cpp
struct PathMetrics {
  bool HasUse;
  unsigned InstructionCount;  // Count on path from StartBB to EndBB
  unsigned EstimatedRP;       // Optional: rough estimate
};

PathMetrics analyzePathMetrics(
    MachineBasicBlock *StartBB,  // Typically NCD
    MachineBasicBlock *EndBB,     // Typically JoinBB (NOT UseBB!)
    VRegMaskPair SpilledVMP,
    MachineInstr *StopInstr = nullptr);
```

**Two Separate Analyses:**
1. **Pre-join paths**: `analyzePathMetrics(NCD, JoinBB, ...)` - paths BEFORE join
2. **Common CFG**: `analyzePathMetrics(JoinBB, UseBB, ...)` - common CFG AFTER join
- Both are needed for complete decision

**Instruction Count**: Sufficient for `len_clean` heuristic
**RP Estimate**: Can use simple heuristic (count defs/uses) without full RPTracker

## Clarification: Why Only Pre-Join Paths Matter

**User's Key Insight (Confirmed):**
> "Use block is not necessarily the same as join block. 2 paths - from spill to use and from NCD(Spill,use) end to use may have a significant and complex CFG in common, all that common CFG is dominated by the join block. Therefore, from this point of view, whatever complex dominated (common) part is, it is decided as a dominated use. So, we only should take into account the part of paths before the paths join."

**Why This Matters:**
1. **Common CFG is Dominated**: After JoinBB, all paths to UseBB are dominated by JoinBB
2. **But Common CFG RP Matters**: If JoinBB → UseBB has high RP, balanced spill wins
   - Balanced: Reload at JoinBB → value available throughout common CFG → reduces RP
   - Split: Reload at UseBB → doesn't help with RP in common CFG
3. **Decision Considers Both**: 
   - Pre-join paths (NCD → JoinBB): Does clean path benefit from spill?
   - Common CFG (JoinBB → UseBB): Does common CFG benefit from early reload?
4. **Complete Analysis**: We need to analyze both pre-join paths AND common CFG

**Example:**
```
NCD
 |    \
 |   SpillBB (spill %0)
 |      |
 |   bb.10 (complex CFG, low RP)
 |      /
 |  CleanPath (no spill)
 |      |
 |   bb.20 (complex CFG, low RP)
 |      /
JoinBB ← Analyze paths BEFORE here AND common CFG after
 |
 |  bb.30 (common CFG - HIGH RP! 100 instructions, many live regs)
 |  bb.40 (common CFG - HIGH RP! loops, branches, more live regs)
 |  bb.50 (common CFG - HIGH RP! more complexity)
 |
UseBB (use %0)

Decision: Balanced spill wins!
- Clean paths have low RP → doesn't favor balanced
- BUT common CFG has HIGH RP → reload at JoinBB helps reduce RP
- Result: Spill on both paths, reload at JoinBB
```

**Analysis Scope:**
- ✅ Analyze: NCD → SpillBB → JoinBB (spill path)
- ✅ Analyze: NCD → CleanPath → JoinBB (clean paths)
- ✅ Analyze: JoinBB → UseBB (common CFG - important for RP analysis!)
  - If common CFG has high RP, balanced spill wins (reload at JoinBB helps)

## Questions to Resolve

1. **RP Estimation**: Do we need accurate RP or is instruction count sufficient?
   - **Recommendation**: Start with instruction count, add RP later if needed
   - **Note**: Since we only analyze pre-join paths, instruction count should be sufficient

2. **Multiple Join Points**: How to handle uses at different join points?
   - **Recommendation**: Process each join independently (current grouping approach)
   - Each JoinBB has its own pre-join path analysis

3. **Rollback Strategy**: If we choose wrong strategy, can we recover?
   - **Recommendation**: Accept that decisions are final. Focus on making good decisions upfront.
   - Pre-join analysis should provide enough information for good decisions

4. **Performance Impact**: Is three-pass approach too slow?
   - **Recommendation**: Measure first. Analysis is O(pre-join paths), not O(full paths to uses)
   - Should be faster than analyzing full paths since we stop at JoinBB

5. **Loop Pre-Header Reload Hoisting**: Should we implement this now or later?
   - **Current**: Decision logic avoids reloads in loops (prefers earlier reload if both in loops)
   - **Future**: Hoist reload to pre-header if possible (requires more complex analysis)
   - **Recommendation**: Implement basic loop avoidance first, hoisting later

6. **Loop-Aware Candidate Selection**: How aggressive should loop penalties be?
   - **Option A**: Heavy penalty (divide distance by 2) → strongly avoids loop-body candidates
   - **Option B**: Light penalty (divide distance by 1.2) → still considers loop-body if very far
   - **Recommendation**: Start with heavy penalty, tune based on benchmarks

7. **Hoisting Reloads to NCD**: When is this profitable?
   - **Current understanding**: Hoist if paths are short AND RP is low
   - **Thresholds**: Path length < 50 AND max RP < 0.8 * RPLimit?
   - **Question**: Should we consider loop structure? (Don't hoist if NCD is in loop?)
   - **Recommendation**: Start with simple heuristic, tune based on benchmarks

## Next Steps

**Priority Order (Loop-Aware First):**

1. **Implement Step 0** - Add loop-aware candidate selection
   - Add `getEffectiveDistance()` with loop penalty
   - Add `canSpillInPreHeader()` check
   - Modify `getVMPsToSpill()` to prefer pre-header spillable candidates
   - **Impact**: Prevents loop-body spilling at source

2. **Review this design** - Get feedback on loop-aware approach

3. **Implement Step 1** - Extract path analysis with loop detection
   - Add loop structure detection to `analyzePathsToJoin()`
   - Returns loop information in PathAnalysis struct
   - Initially returns "no loops" (preserves behavior)

4. **Implement Step 2** - Group uses by join (low risk, preserves behavior)

5. **Test Steps 0-2** - Verify no regressions, loop detection works

6. **Implement Step 3** - Add decision logic for balanced vs split
   - Initially returns current behavior (split-before-use)
   - Add heuristics for balanced spill decision

7. **Implement Step 3b** - Add hoisting cost model (separate from Step 3)
   - Add `shouldHoistReloadToNCD()` function
   - Initially returns false (preserves current behavior)
   - Check path length and max RP

8. **Implement Step 4** - Balanced spill implementation
   - Insert spills on clean paths
   - Reloads follow standard dominated-use logic (closest to uses)
   - Requires careful testing

## References

- Paper section 6.2: Balanced spill heuristics
- Current code: `AMDGPUSSARegisterSpiller.cpp:806-879` (reachable use handling)
- Current code: `AMDGPUSSARegisterSpiller.cpp:1276` (`hasUseOnPath`)
- Current code: `AMDGPUSSARegisterSpiller.cpp:1561-1564` (TODO for balanced spill)
- Current code: `AMDGPUSSARegisterSpiller.cpp:352-401` (`getVMPsToSpill` - Belady's algorithm)
- LLVM API: `MachineLoopInfo::getLoopFor()`, `MachineLoop::getLoopPreheader()`

