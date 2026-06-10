# SSA-Aware Register Spiller Development Notes

## Project Overview

Developing an SSA-aware register spiller for AMDGPU that handles subregisters, divergent control flow, and maintains SSA form throughout the spilling process.

**Key Innovation:** "Store at Definition" strategy - stores registers at their definition point (when EXEC is full) to eliminate EXEC drift issues, then uses `shrinkToUses()` to trim LiveIntervals after reload placement.

---

## Current Status (2025-11-19 Evening)

### Working Implementation

**Core Spilling Strategy:**
1. **Store at definition** (`spillAtDefinition()`) - physically stores register right after definition when EXEC is full
2. **Set virtual spill point** - computes `KillIdx` at high-pressure point, but does NOT prune LiveInterval
3. **Emit reloads** for dominated uses with dominance grouping
4. **Handle reachable uses** - currently using standard PHI insertion (split-before-use commented out)
5. **Shrink LiveIntervals** - `shrinkToUses()` called at end of `emitReloadsAndRepairSSA()` after all SSA repairs

**Key Files:**
- `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp` (1643 lines)
- `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.h` (279 lines)
- `llvm/lib/Target/AMDGPU/VRegMaskPair.h` (subregister-aware register tracking)

### Recent Changes (2025-11-19)

**1. Removed WWM (Whole Wave Mode) Wrapping**
- **Rationale:** With "store at definition", we store the same mask as defined, so WWM is unnecessary
- **Removed:**
  - `wrapWithWWM()` method
  - All calls to `wrapWithWWM()`
  - WWM-related SGPR allocation

**2. Removed Divergence Detection Helpers**
- **Rationale:** No longer needed for spill placement with "store at definition"
- **Removed:**
  - `isDivergentInstr()`
  - `pathHasDivergence()`
  - `pathsHaveDivergence()`
  - Divergence classification in `emitReloadsAndRepairSSA()`

**3. Removed IDF Parameter**
- **Changed:** `splitBlockBeforeReload()` now computes JoinBB directly from CFG structure
- **Algorithm:** JoinBB is UseBB if it has multiple predecessors, otherwise computed via dominator tree
- **Benefit:** Simpler, no need to compute IDF in `emitReloadsAndRepairSSA()`

**4. Merged Handler Functions**
- **Merged:** `handleUniformReachableUse()` and `handleDivergentReachableUse()` into single `handleReachableUse()`
- **Simplified:** Always uses split-before-use without WWM

**5. Removed spillBefore() Call**
- **Old flow:** `spillAtDefinition()` → `spillBefore()` (prune) → `emitReloadsAndRepairSSA()`
- **New flow:** `spillAtDefinition()` → compute KillIdx → `emitReloadsAndRepairSSA()` → `shrinkToUses()`
- **Key change:** LiveInterval stays valid during reload placement, only shrunk once at end

**6. Temporarily Commented Out Split-Before-Use**
- **Location:** Line 832 in AMDGPUSSARegisterSpiller.cpp
- **Reason:** Need to implement cost model to decide when split-before-use is profitable
- **Current behavior:** Uses standard PHI insertion for reachable uses (reloads on all paths)
- **TODO:** Implement cost model considering path length and RP from JoinBB to use

### Current Code Structure

**spillAndReload() - Main Entry Point:**
```cpp
for (each VMP to spill) {
  1. spillAtDefinition(VMP)           // Store at def, when EXEC full
  2. Compute KillIdx at high-RP point // Virtual spill point
  3. assignVirt2StackSlot(VMP)        // Get frame index
  4. emitReloadsAndRepairSSA(VMP, KillIdx, FI)  // Place reloads, repair SSA
}
```

**emitReloadsAndRepairSSA() - Reload Placement:**
```cpp
1. Collect all uses of spilled register
2. Classify uses:
   - Dominated uses: handled with dominance grouping
   - Non-dominated uses: check reachability
3. Group dominated uses by dominance chains
4. Emit one reload per group at group head
5. Call MachineLaneSSAUpdater::repairSSAForNewDef()
6. Try to hoist spill to NCD if no uses on paths
7. Handle reachable uses:
   - Currently: emit reload at use, let SSAUpdater insert PHIs
   - TODO: use handleReachableUse() with cost model
8. shrinkToUses(&SpilledLI)  // Trim LiveInterval after all repairs
```

**spillAtDefinition() - Store at Definition:**
```cpp
1. Find definition: MRI->getVRegDef(VReg)
2. Insert store right after definition with isKill=false
3. Track in StoredAtDefinition set
4. Returns store instruction
```

**handleReachableUse() - Split-Before-Use (COMMENTED OUT):**
```cpp
1. Compute JoinBB from CFG structure
2. Insert flag PHI at JoinBB (1 from spill path, 0 from clean)
3. Split UseBB into: UseBB_Pre → ReloadBB → UseBB_Post
4. Conditional branch: if clean path, skip ReloadBB
5. MachineLaneSSAUpdater inserts value PHI at UseBB_Post
```

### What's Working

✅ Store at definition eliminates EXEC drift
✅ No WWM needed - simpler code
✅ LiveIntervals stay valid during reload placement
✅ Dominated use handling with grouping works
✅ Reachable use handling works (with standard PHI insertion)
✅ shrinkToUses() correctly trims LiveIntervals after repairs
✅ Subregister spilling with VRegMaskPair
✅ Reachability checks filter unreachable uses

### What's Temporarily Disabled

⚠️ **Split-before-use optimization** (line 832 commented out)
- Reason: Need cost model to decide when profitable
- Impact: More reloads than optimal (reloads on all paths instead of just spill path)
- Not a correctness issue, just performance

### Known Issues & TODOs

**High Priority:**
- [ ] **Implement cost model for split-before-use decision**
  - Measure path length from JoinBB to use
  - Check max RP on path from JoinBB to use
  - Decision thresholds: long path (>50 insts) or high RP (>70% limit)
  - See NOTES.md 2025-11-18 Evening section for detailed algorithm

- [ ] **Fix test cases with RP budget violations**
  - `spill-dominated-branches.mir`: Remove %2 from join (12 VGPRs live, budget 7-8)
  - `spill-linear-dominated.mir`: Remove excess register
  - `spill-multi-path-independent.mir`: Remove %2 (3rd vreg_128)

- [ ] **Update tryHoistSpillToNCD() logic**
  - Currently hoists by pruning LiveInterval at NCD
  - With "store at definition", verify this still makes sense
  - May need to adjust how we represent hoisted kill point

**Medium Priority:**
- [ ] Pre-allocation feasibility check (bail if max RP > limit)
- [ ] Balanced spill decision for clean paths with high RP
- [ ] EWF (EXEC Write Frontier) as alternative to WWM for divergent paths
- [ ] Path analysis caching for performance
- [ ] Comprehensive MIR test suite for subregister scenarios

**Low Priority:**
- [ ] Loop-aware spilling optimizations
- [ ] Performance evaluation on real AMDGPU workloads
- [ ] Integration with SSA-based register allocator

### Code Locations

**Key Methods:**
- `spillAndReload()` - Lines 543-614
- `emitReloadsAndRepairSSA()` - Lines 617-854
- `spillAtDefinition()` - Lines 894-962
- `spillBefore()` - Lines 964-1044 (UNUSED after recent changes, can be removed)
- `handleReachableUse()` - Lines 1549-1559 (COMMENTED OUT at call site line 832)
- `splitBlockBeforeReload()` - Lines 1405-1547
- `tryHoistSpillToNCD()` - Lines 1338-1403

**Helper Methods:**
- `hasUseOnPath()` - Lines 1278-1336
- `usesSpilledVMP()` - Lines 1237-1261
- `repairSSAForReload()` - Uses MachineLaneSSAUpdater

### Test Files

**MIR Tests:**
- `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-dominated-branches.mir`
- `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-linear-dominated.mir`
- `llvm/test/CodeGen/AMDGPU/SSASpiller/spill-multi-path-independent.mir`
- Others in `llvm/test/CodeGen/AMDGPU/SSASpiller/`

**Note:** Some tests currently have RP budget violations and need fixing.

---

## Technical Background

### Store at Definition Strategy

**Problem:** Spilling at high-pressure point can occur after divergent branches where EXEC mask has changed, leading to only a subset of lanes being stored.

**Solution:** Store register immediately after its definition (when EXEC is guaranteed to be full), then mark it dead at the virtual spill point. Use `shrinkToUses()` to trim LiveInterval after all reloads are placed.

**Benefits:**
1. **Correctness:** All lanes stored when EXEC is full
2. **Simplicity:** No WWM wrapping needed
3. **Clean LiveIntervals:** Stay valid during reload placement
4. **Efficient:** Only one physical store per register

**Key Insight:** Separate "when to store" (at definition, for correctness) from "when to free the register" (at spill point, for register pressure).

### Why No WWM Needed

With "store at definition":
- **Stores happen when EXEC is full** (at definition) → all lanes stored correctly
- **Reloads load the same mask that was defined** → correctness preserved
- **No EXEC drift concern** → no need for WWM to save/restore EXEC

### Why No Divergence Detection Needed

- **Spills are always correct** (stored at definition when EXEC full)
- **Divergence only matters for reload optimization** (split-before-use decision)
- **Current approach:** Use standard PHI insertion for all reachable uses
- **Future optimization:** Add divergence check only for split-before-use cost model

### Split-Before-Use Strategy

**Goal:** Extend RP decrease window by avoiding PHI at JoinBB.

**Without split-before-use (Case 2a):**
```
DefBB → ... → JoinBB → ... → UseBB
              ↑ PHI here
              RP decrease window: spill to end of spill path
```

**With split-before-use (Case 2b):**
```
DefBB → ... → JoinBB → ... → UseBB_Pre → ReloadBB → UseBB_Post
                               ↑ split here      ↑ PHI here
              RP decrease window: spill to UseBB_Pre (much longer)
```

**When to use split-before-use:**
- Long path from JoinBB to use (>50 instructions)
- High RP on path from JoinBB to use (>70% of limit)
- Otherwise, standard PHI at JoinBB is simpler

---

## Recent Discoveries & Clarifications

### 2025-11-18 (Monday Evening) - Hoisting and Split-Before-Use

**User Clarification on Hoisting:**
> "I am sorry: 'if we have 2 uses on disjoint paths but at least on one path RP is high - we cannot hoist to NCD as we increase RP!' - is wrong, I made a mistake. The high RP on both spill and clean paths is exactly the main reason for hoisting!"

**Correct Understanding:**
- **Hoist to NCD when:** High RP on both paths
- **Benefit:** Spill once at NCD instead of potentially on both paths
- **Don't hoist when:** Uses exist on either path between NCD and join/use

**Why split-before-use is still needed:**
Even with hoisting and "store at definition", split-before-use helps when there's a long or high-RP path from JoinBB to the use:
- **Without split:** PHI at JoinBB → RP decrease window is short
- **With split:** No PHI at JoinBB → RP decrease window extends to split point

### 2025-11-18 (Monday Afternoon) - shrinkToUses Verification

Confirmed that `shrinkToUses(LiveInterval*)` automatically handles subranges:
- No need for separate subrange shrinking calls
- Verified in `LiveIntervals.cpp` lines 481-537

### 2025-11-10 - Store-at-Definition Implementation

Original implementation of the "store at definition" approach:
- Added `spillAtDefinition()` method
- Modified `spillBefore()` to use `pruneValue()` (now unused after recent changes)
- Updated `spillAndReload()` workflow
- Changed `emitReloadsAndRepairSSA()` signature to use `SlotIndex KillIdx`

---

## Implementation History

### Major Milestones

1. **Initial Framework** - Basic spill/reload with SSA form
2. **MachineLaneSSAUpdater Integration** - Lane-aware SSA reconstruction
3. **Subregister Support** - VRegMaskPair for partial spills
4. **Dominance Grouping** - Efficient reload placement for dominated uses
5. **Reachability Analysis** - IDF-based reachable use detection
6. **Split-Before-Use** - CFG transformation for optimal RP
7. **Store at Definition** - EXEC drift elimination (2025-11-10)
8. **WWM/Divergence Removal** - Simplified after store-at-definition (2025-11-19)
9. **spillBefore Removal** - Deferred LiveInterval trimming (2025-11-19)

### Major Bug Fixes

1. **Invalid MIR between spill/reload** - Fixed with atomic per-register processing
2. **SSAUpdater interface mismatch** - Fixed by reloading into original VReg
3. **Subregister def replacement undef flag** - Fixed in MachineLaneSSAUpdater
4. **PHI use infinite loop** - Fixed by skipping PHI instructions in use collection
5. **Over-spilling bug** - Fixed RemainingToSpill not reset to 0
6. **Immediate reload after spill** - Fixed by skipping triggering instruction
7. **Stale LiveIntervals** - Fixed by moving shrinkToUses to end
8. **Manual PHI creation** - Fixed by removing manual PHI, relying on SSAUpdater
9. **rewriteDominatedUses bug** - Fixed dominance vs reachability check
10. **SSA Updater refactoring breakage** - Fixed IDF caching and DenseMapInfo
11. **Register budget violation at reload** - Added RP check before reload
12. **Stale use bug** - Added usesSpilledVMP() check

---

## Key Design Decisions

### Why Store at Definition?

**Alternatives considered:**
1. WWM wrapping around spills - Complex, requires SGPR pairs, costly
2. EWF (EXEC Write Frontier) - Move reload to first EXEC write - Loses optimal placement
3. Store at definition - Simple, correct, no runtime cost

**Chosen:** Store at definition (option 3)

### Why Defer LiveInterval Trimming?

**Alternatives considered:**
1. Prune immediately at spill point - LiveIntervals become invalid, uses broken
2. Prune after each reload - Multiple pruning operations, complex
3. Defer until all reloads placed - Clean, works with SSAUpdater

**Chosen:** Defer until end (option 3)

### Why Split-Before-Use?

**Alternatives considered:**
1. Always reload on all paths - Simple but wasteful
2. Always split-before-use - Complex CFG transformations
3. Cost model based split - Optimal but needs tuning

**Chosen:** Cost model based (option 3) - pending implementation

---

## Collaboration Notes

### Colleague's Input

Key insights from colleague:
- "Store at definition" strategy to avoid EXEC drift
- Use `pruneValue()` to mark register dead without emitting redundant stores
- Hoisting to NCD when high RP on both paths
- Split-before-use extends RP decrease window

### Presentation Feedback

After presentation, decided to:
1. Remove WWM wrapping (not needed with store-at-definition)
2. Remove divergence detection (not needed for spill placement)
3. Simplify to: store at def → virtual spill point → reload → shrinkToUses
4. Defer split-before-use until cost model is implemented

---

## Next Steps for New Machine

When resuming work on the new machine:

1. **Verify build and tests**
   ```bash
   cd llvm-project/build
   ninja AMDGPUSSARegisterSpiller
   ninja check-llvm-codegen-amdgpu
   ```

2. **Enable split-before-use**
   - Uncomment line 832 in AMDGPUSSARegisterSpiller.cpp
   - Implement cost model in `handleReachableUse()` caller
   - Add decision logic based on path metrics

3. **Implement cost model**
   - Add `measurePathMetrics()` helper
   - Add `shouldSplitBeforeUse()` decision function
   - Test with various thresholds

4. **Fix test cases**
   - Address RP budget violations in existing tests
   - Run CFG analysis to verify correctness

5. **Performance evaluation**
   - Run on real shaders/kernels
   - Measure RP reduction vs overhead
   - Tune cost model thresholds

6. **Clean up dead code**
   - Remove unused `spillBefore()` method (lines 964-1044)
   - Remove any other dead code from refactoring

---

## Build & Test Commands

```bash
# Build
cd /work/atimofee/sandbox/github/llvm-project/build
ninja AMDGPUSSARegisterSpiller

# Run specific test
./bin/llc -march=amdgcn -mcpu=gfx900 -verify-machineinstrs \
  ../llvm/test/CodeGen/AMDGPU/SSASpiller/spill-linear-dominated.mir

# Run all SSASpiller tests
ninja check-llvm-codegen-amdgpu-ssaspiller

# Debug with gdb
gdb --args ./bin/llc -march=amdgcn -mcpu=gfx900 -verify-machineinstrs \
  -debug-only=amdgpu-ssa-spiller test.mir
```

---

## References

- **LLVM Live Intervals:** `llvm/include/llvm/CodeGen/LiveIntervals.h`
- **MachineLaneSSAUpdater:** `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`
- **VRegMaskPair:** `llvm/lib/Target/AMDGPU/VRegMaskPair.h`
- **GCNRegPressure:** `llvm/lib/Target/AMDGPU/GCNRegPressure.h`
- **SIInstrInfo:** `llvm/lib/Target/AMDGPU/SIInstrInfo.h`

---

**Last Updated:** 2025-11-19 Evening
**Ready for:** Migration to new development machine
**Status:** Core implementation working, split-before-use optimization pending cost model

---

## 2025-12-12 – Documentation refresh (current design) + test comment cleanup

- **Context / goal**
  - Refresh docs to reflect the current SSA spiller design (store-at-definition + virtual spill point) and make the Obsidian knowledge base renderable/reviewable.
  - Ensure MIR tests and documentation don’t describe obsolete behavior.

- **Attempts / hypotheses**
  - Re-audited key behaviors from sources:
    - `AMDGPUSSARegisterSpiller::spillAndReload` / `emitReloadsAndRepairSSA` / `spillAtDefinition`
    - `MachineLaneSSAUpdater::isUseReachableFromDef` (pruned IDF reachability)
  - Iterated on Mermaid diagrams to satisfy Obsidian/Cursor preview constraints:
    - Avoid diff `+/-` markers inside Mermaid blocks (causes syntax errors).
    - Avoid embedded newlines in node labels (`\n` either breaks parsing or renders as literal text).
    - Use “subgraph per basic block” + dotted intra-block ordering edges (`-.->`) to show instruction order.
    - Use an HTML flex container to place two Mermaid diagrams side-by-side (Before/After) without large subgraph background panels.

- **Results / discoveries**
  - Virtual spill marker behavior confirmed:
    - Option: `--amdgpu-ssa-spill-markers=1`
    - Emits `SI_VIRTUAL_SPILL_MARKER <vreg_index>, <lane_mask>` so LIT tests can assert the virtual spill point.
    - Marker insertion is omitted when it would be adjacent to the physical store for the same `(VReg, LaneMask)`.
  - Found misleading/outdated comments in `spill-vreg-subregister.mir` describing WWM/split-before-use; updated them to match current CHECK output and behavior.

- **Decisions / rationale**
  - Docs must avoid workspace-local paths; cite source using:
    - symbolic LLVM-relative paths, and
    - canonical GitHub links when known (fork/branch), plus upstream PR references for SSA Updater (PR 163421) and NextUse (PR 156079).
  - Prefer diagrams that are robust in Obsidian:
    - Side-by-side “Before spill” / “After spill” diagrams
    - Subgraph-per-BB instruction grouping for aligned instruction lists.

- **Next actions**
  - Revisit `SSA_SPILLER_DESIGN.md` Reach/IDF LaTeX and wording as needed (keep both intent and code-equivalent definition).
  - Continue expanding the design doc with any additional diagrams/examples if required.
  - When implementation resumes: cost model for split-before-use + balanced spill, and corresponding test updates.

### 2026-05-13 – DebugBreak RFC Review [DESIGN] [REVIEW]

- **Context / goal**
  - Read and analyzed the DebugBreak Proposal RFC from `AMD-ROCm-Internal/rocm-gdb-docs` PR #1 (`debugger-docs/design-notes/2026-04-21_DebugBreak.md`).
  - RFC proposes unified diagnostic code primitives: `DiagnosticBreak()`, `IsDiagnosticEnabled()`, `SetDiagnosticEnabled()`, `StartThreadsWithDiagnostics` attribute.
  - GPU codegen maps these to `S_TRAP 3/4`, `S_CBRANCH_CDBG_USER_OR_SYSTEM`, with EXEC mask guards.
  - Two-level state: per-wave `DBGUSER` (programmatic) | per-device `DBGSYSTEM` (debugger override).

- **Results / discoveries**
  - RFC claims "almost zero performance cost" and "only cost is effectively code size" when diagnostics are present but not enabled.
  - This claim is based on cold code layout (MachineBlockPlacement) and branch prediction — valid for I-cache locality.
  - **However**, the RFC does not address register pressure or instruction scheduling impact:
    - RA does not distinguish hot from cold blocks — live ranges extend through diagnostic blocks.
    - MachineScheduler considers all successors, so diagnostic blocks alter scheduling on the hot path.
    - AMDGPU occupancy cliffs: even small RP increase from diagnostic code can drop waves per SIMD.
    - Spill cascades: diagnostic RP overflow causes spills on the hot path too.
    - Small kernels: diagnostic blocks can constitute a significant fraction of total code.

- **Questions prepared for meeting**
  1. What exactly is meant by "almost zero performance cost"? Is the claim limited to I-cache/branch prediction, or does it also account for RA and scheduling?
  2. How is register pressure impact on the hot path addressed? Live ranges extending through diagnostic blocks increase RP even when diagnostics are never executed.
  3. What about occupancy cliffs on AMDGPU? Even a small VGPR/SGPR increase from diagnostic code can drop occupancy at discrete thresholds.
  4. Does the compiler discount cold blocks during scheduling? MachineScheduler considers all successors — diagnostic blocks can alter hot-path scheduling.
  5. Can diagnostic code cause spill cascades on the hot path? RP overflow in diagnostic blocks causes spills globally.
  6. Should diagnostic code be outlined rather than inlined? Machine outlining would isolate RP; hot path pays only for a call.
  7. Is separate compilation of diagnostic code feasible? Eliminates RP and scheduling interference entirely.
  8. What is the expected code size overhead, especially for small kernels? Each diagnostic site adds `S_CBRANCH EXECZ` + `S_TRAP` + cold block. For small kernels, diagnostic blocks could constitute a significant fraction of total code, fundamentally changing layout, cache footprint, and scheduling characteristics.

- **Next actions**
  - Raise these questions at the DebugBreak RFC review meeting.
  - Follow up on whether outlining or separate compilation is viable for diagnostic code isolation.
