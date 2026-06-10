# MachineLaneSSAUpdater Test Framework - Complete Summary

This document provides a comprehensive overview of the testing infrastructure created for `MachineLaneSSAUpdater`.

## Problem Statement

`MachineLaneSSAUpdater` is a utility class (not an LLVM pass) that performs lane-aware SSA reconstruction. Testing utilities requires a different approach than testing passes:

1. **No direct pipeline integration**: Can't just add to pass manager and run
2. **Two distinct APIs**: Must test both `addDefAndRepairNewDef` and `addDefAndRepairAfterSpill`
3. **Complex scenarios**: Need to simulate spilling, track register pressure, etc.
4. **Lane awareness**: Must verify correct handling of subregister lanes

## Solution: Unit Test-Based Architecture

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Test Framework Layers                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Layer 1: MIR Test Scenarios (.mir)                         │
│  ├─ Declarative test scenarios (documentation)              │
│  ├─ Used as input for unit tests                            │
│  ├─ Can be parsed by MIRParser                              │
│  └─ Located in: llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/ │
│                                                              │
│  Layer 2: Unit Tests (GoogleTest)                           │
│  ├─ Programmatic testing with assertions                    │
│  ├─ Parses MIR files/strings                                │
│  ├─ Sets up analysis pipeline                               │
│  ├─ Directly exercises MachineLaneSSAUpdater APIs           │
│  ├─ Simulates spilling, inserts defs, calls updater         │
│  ├─ Target-independent (in llvm/unittests/CodeGen/)         │
│  └─ Located in: llvm/unittests/CodeGen/MachineLaneSSAUpdaterTest.cpp │
│                                                              │
└─────────────────────────────────────────────────────────────┘

Note: No separate test pass needed - unit tests directly exercise the utility.
This follows the pattern from NextUseAnalysisTest while maintaining target independence.
```

## Component Details

### 1. Unit Tests (Current Implementation)

**File**: `llvm/unittests/CodeGen/MachineLaneSSAUpdaterTest.cpp`

**Purpose**: Basic smoke tests for MachineLaneSSAUpdater API

**Current Scope** (v1):
- **Target Independent**: Located in `llvm/unittests/CodeGen/`
- Verifies API compilation and linking
- Tests basic LaneBitmask operations
- Validates helper function signatures

**Test Cases** (Current):
- `CutEndPointsBasicAPI()`: Verifies CutEndPoints class exists
- `LaneBitmaskOperations()`: Tests LaneBitmask manipulation
- `GetSubRegIndexForLaneMask()`: Tests helper function

**Why Limited Scope?**

Full integration testing requires substantial infrastructure (~1000 lines):
- MIRParser integration for loading test MIR
- PassManager setup for analysis dependencies
- Complex setup of SlotIndexes, LiveIntervals, MachineDominatorTree
- Target initialization and teardown

This is similar to [NextUseAnalysisTest](https://github.com/llvm/llvm-project/pull/156079) complexity.

**Future Enhancement** (v2 - TODO):

Full integration tests would:
- Parse MIR files from test scenarios
- Set up required analyses
- Exercise `addDefAndRepairNewDef` and `addDefAndRepairAfterSpill`
- Verify SSA reconstruction correctness
- Test PHI insertion, partial lanes, etc.

Contributions welcome!

### 2. MIR Test Files (Test Input/Documentation)

**Location**: `llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/*.mir`

**Test Files**:

1. **simple_new_def.mir**
   - Basic SSA reconstruction after new definition
   - Linear control flow
   - Full register updates

2. **spill_reload.mir**
   - Spill at high register pressure
   - Reload before use
   - LiveInterval cutting and extension

3. **partial_lanes.mir**
   - Wide registers with subregisters
   - Partial lane updates
   - REG_SEQUENCE insertion

4. **phi_insertion.mir**
   - Diamond control flow
   - PHI insertion at join points
   - Per-edge lane analysis

**MIR Structure**:
```mir
# These MIR files are parsed by unit tests
# They serve as test scenarios and documentation

---
name: test_function
tracksRegLiveness: true
body: |
  bb.0:
    ; Original code
    %0:vgpr_32 = IMPLICIT_DEF
    S_NOP 0, implicit %0
  
  bb.1:
    ; Unit test will insert new def here programmatically
    ; e.g., %1:vgpr_32 = V_MOV_B32_e32 42
    S_NOP 0
  
  bb.2:
    ; Uses that should be rewritten
    S_NOP 0, implicit %0
...
```

Unit tests parse these files and verify transformations programmatically.


## Pipeline Setup

### Required Analyses

The test pass declares dependencies on:

```cpp
void getAnalysisUsage(AnalysisUsage &AU) const override {
  AU.addRequired<SlotIndexes>();
  AU.addPreserved<SlotIndexes>();
  AU.addRequired<LiveIntervals>();
  AU.addPreserved<LiveIntervals>();
  AU.addRequired<MachineDominatorTree>();
  AU.addPreserved<MachineDominatorTree>();
  MachineFunctionPass::getAnalysisUsage(AU);
}
```

### Pass Registration

```cpp
INITIALIZE_PASS_BEGIN(MachineLaneSSAUpdaterTestPass, 
                      "test-machine-lane-ssa-updater",
                      "MachineLaneSSAUpdater Test Pass", false, false)
INITIALIZE_PASS_DEPENDENCY(SlotIndexes)
INITIALIZE_PASS_DEPENDENCY(LiveIntervals)
INITIALIZE_PASS_DEPENDENCY(MachineDominatorTree)
INITIALIZE_PASS_END(MachineLaneSSAUpdaterTestPass, 
                    "test-machine-lane-ssa-updater",
                    "MachineLaneSSAUpdater Test Pass", false, false)
```

## Testing Workflow

```
┌──────────────┐
│ Unit Test    │  GoogleTest-based test
│ (GTest)      │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Parse MIR    │  Create MachineFunction
│ String       │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Setup        │  Run SlotIndexes, LiveIntervals, etc.
│ Analyses     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Direct       │  Call utility APIs directly
│ Utility      │
│ API Calls    │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ EXPECT_*     │  Assert expected behavior
│ Assertions   │
└──────────────┘
```

## Simulating Register Allocator

### Spill Simulation

```cpp
bool testSpillReload(MachineFunction &MF) {
  // 1. Find high RP point
  MachineBasicBlock &SpillBB = *std::next(MF.begin(), 1);
  SlotIndex SpillIdx = SI.getInstructionIndex(SpillPt);
  
  // 2. Collect cut information
  SpillCutCollector Collector(LIS, MRI);
  CutEndPoints CutInfo = Collector.cut(OrigVReg, SpillIdx, FullMask);
  
  // 3. Insert spill instruction
  // (BUFFER_STORE or equivalent)
  
  // 4. Later, insert reload
  Register ReloadVReg = MRI.createVirtualRegister(RC);
  MachineInstrBuilder ReloadMI = BuildMI(..., ReloadVReg);
  
  // 5. Reconstruct SSA
  MachineLaneSSAUpdater Updater(MF, LIS, SI, MDT);
  Register ResultVReg = Updater.addDefAndRepairAfterSpill(*ReloadMI, CutInfo);
  
  // 6. Verify
  EXPECT_TRUE(ResultVReg.isValid());
  EXPECT_TRUE(LIS.hasInterval(ResultVReg));
}
```

## Running Tests

### Command Examples

**Build Unit Tests**:
```bash
ninja CodeGenTests
```

**Run All Tests**:
```bash
./unittests/CodeGen/CodeGenTests --gtest_filter=MachineLaneSSAUpdaterTest.*
```

**Run Specific Test**:
```bash
./unittests/CodeGen/CodeGenTests --gtest_filter=MachineLaneSSAUpdaterTest.SimpleNewDefReconstruction
```

**With Verbose Output**:
```bash
./unittests/CodeGen/CodeGenTests --gtest_filter=MachineLaneSSAUpdaterTest.* --gtest_verbose
```

**With LLVM Debug Output** (requires debug build):
```bash
./unittests/CodeGen/CodeGenTests --gtest_filter=MachineLaneSSAUpdaterTest.* \
    --debug-only=machine-lane-ssa-updater
```

## Build Integration

### Modified Files:

1. **llvm/unittests/CodeGen/CMakeLists.txt**
   - Added `MachineLaneSSAUpdaterTest.cpp` to CodeGenTests

### File Locations:

- **Utility Code**: `llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`
- **Utility Header**: `llvm/include/llvm/CodeGen/MachineLaneSSAUpdater.h`
- **Unit Tests**: `llvm/unittests/CodeGen/MachineLaneSSAUpdaterTest.cpp` (target-independent)
- **MIR Scenarios**: `llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/*.mir`

### Build Commands:

```bash
# Build everything
ninja

# Build only unit tests
ninja CodeGenTests

# Build only llc (includes test pass)
ninja llc
```

## Why This Approach?

### Advantages:

1. **Target Independence**
   - Tests in `llvm/unittests/CodeGen/` (NOT target-specific directory)
   - Utility is target-independent, so tests should be too
   - Uses AMDGPU for rich subregister structure but tests are generic

2. **No Production Code Pollution**
   - No test pass in `llvm/lib/CodeGen/` (that's for production code only)
   - All test infrastructure in appropriate test directories
   - Follows LLVM best practices

3. **Direct API Testing**
   - Unit tests directly exercise MachineLaneSSAUpdater APIs
   - No intermediate test pass layer needed
   - Simpler and more maintainable

4. **Realism**
   - Simulates actual register allocator behavior
   - Tests with real MachineFunction instances
   - Exercises full analysis pipeline

5. **Maintainability**
   - Easy to add new test scenarios (just add MIR files)
   - Unit tests with clear assertions
   - Well-documented with examples

## Reference Implementation

Based on: [AMDGPU NextUseAnalysis Test](https://github.com/llvm/llvm-project/pull/156079)

Key inspiration:
- Test pass pattern for testing utilities
- MIR-based test scenarios
- Analysis dependency management
- Mode detection from function names

## Future Enhancements

Possible improvements:

1. **Register Pressure Tracking**
   - Use `RegisterPressureTracker` for realistic RP simulation
   - Automatic spill point detection

2. **More Test Scenarios**
   - Loop scenarios
   - Multiple spills
   - Complex subregister patterns

3. **Target Independence**
   - Adapt tests for X86, ARM, etc.
   - Generalize subregister handling

4. **Verification Enhancements**
   - LiveInterval verification helpers
   - SSA form validation
   - Dominance property checks

## Contact / Maintainers

For questions or issues with the test framework, refer to:
- `llvm/test/CodeGen/AMDGPU/MachineLaneSSAUpdater/README.md`
- LLVM CodeGen documentation
- MachineLaneSSAUpdater header comments

