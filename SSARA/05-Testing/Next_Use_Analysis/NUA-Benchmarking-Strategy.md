# NUA Benchmarking Strategy

> **Current implementation status.** In the `ssara` worktree, the in-tree ML
> NUA is registered as `amdgpu-next-use` (`DEBUG_TYPE "amdgpu-next-use"`,
> `AMDGPUNextUseAnalysisWrapper`). It is **lazily analyzed** — `init()` +
> `analyze()` are deferred to the first query via `ensureAnalyzed()` — and is
> **used only by the SSA spiller**. The timer flag
> `-amdgpu-next-use-analysis-timers` exists today (timers `"Time spent in
> analyze()"` and `"Time spent in getNextUseDistance()"`, group description
> `"AMDGPU Next Use Analysis"`); distance dumping is
> `-amdgpu-next-use-dump-distance`. The `-amdgpu-next-use-per-function-timers`
> flag and the `exerciseQueries()` method described below are part of the
> **comparison harness / GFX NUA instrumentation** (Section 3 patch), not the
> current in-tree ML NUA. This document describes the methodology for comparing
> the two implementations.

## 1. Motivation: Why Timers Are Needed

Comparing the two Next Use Analysis implementations (ML NUA and GFX NUA) by
wall-clock time alone produces misleading results. Both implementations run
inside `llc` as a `MachineFunctionPass`, and the measured wall time includes
significant overhead that has nothing to do with the analysis algorithm itself:

| Overhead source | Typical cost (Blender, 235 MB MIR, 310 kernels) |
|---|---|
| MIR parsing and pass infrastructure setup | ~34 s |
| MIR serialization to `-o /dev/null` | < 1 s |
| Dump I/O (`-dump-distance` to stderr) | **~25 minutes** (gigabytes of text) |

When `-dump-distance` is enabled, I/O dominates: the dump produces gigabytes of
distance tables on stderr, inflating wall time from ~40 s to ~26 minutes. Even
redirecting to `/dev/null` leaves measurable syscall overhead.

To obtain a meaningful comparison we need to isolate the **pure algorithmic
cost** of each implementation. The analysis has two distinct phases:

1. **Initialization / Analysis** -- building internal data structures
   (dataflow fixpoint for ML NUA, shortest-path tables for GFX NUA).
2. **Query** -- answering `getNextUseDistance()` calls, which is the API the
   spiller actually uses at every instruction.

Fine-grained LLVM timers allow us to measure each phase independently, without
I/O or parsing noise.

## 2. Common Benchmarking API

Both implementations expose identical command-line flags and produce
identically-formatted timer output, enabling direct comparison.

### 2.1 Command-Line Flags

| Flag | Effect |
|---|---|
| `-amdgpu-next-use-analysis-timers` | Enable aggregate timer reporting (printed once at process exit) |
| `-amdgpu-next-use-per-function-timers` | Additionally print per-function breakdown (requires the flag above) |

Both flags are `cl::Hidden` and have no effect on analysis correctness or
output. They only add timer instrumentation.

### 2.2 Timer Structure

Each implementation defines two timers inside a single `TimerGroup`:

| Phase | ML NUA timer description | GFX NUA timer description |
|---|---|---|
| Init / Analysis | `"Time spent in analyze()"` | `"Time spent in initialize()"` |
| Query | `"Time spent in getNextUseDistance()"` | `"Time spent in exerciseQueries()"` |

The `TimerGroup` name is `"AMDGPU Next Use Analysis"` in both implementations.

### 2.3 Query Exercise

When timers are enabled, both implementations call an `exerciseQueries()`
method after initialization. This method iterates all basic blocks,
instructions, and defined virtual registers in the function, calling
`getNextUseDistance()` for each. This provides a consistent, reproducible
workload that exercises the query API without any I/O.

The exercise is wrapped in a single `TimeRegion` to avoid per-call timer
overhead (millions of `getNextUseDistance()` calls would otherwise generate
millions of syscalls from individual timer start/stop).

### 2.4 Timer Output Format

LLVM's `TimerGroup` prints to stderr at process exit. The format is:

```
===-------------------------------------------------------------------------===
                            AMDGPU Next Use Analysis
===-------------------------------------------------------------------------===
  Total Execution Time: X.XXXX seconds (X.XXXX wall clock)

   ---User Time---   --System Time--   --User+System--   ---Wall Time---  --- Name ---
   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)  Time spent in analyze()
   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)   X.XXXX ( XX.X%)  Time spent in getNextUseDistance()
   X.XXXX (100.0%)   X.XXXX (100.0%)   X.XXXX (100.0%)   X.XXXX (100.0%)  Total
```

When `-amdgpu-next-use-per-function-timers` is also passed, each function's
timer block is preceded by a header line:

```
=== _Z17integrate_surfaceILj8389563EEiPK16KernelGlobalsGPUiPf (9743 BBs) ===
```

The per-function mode resets timers after each print, so each report shows the
isolated time for that function. The aggregate report at exit is suppressed
(timers are zero after the last reset).

### 2.5 Pass Names

The two implementations are registered under different pass names:

| Implementation | `-run-pass=` value |
|---|---|
| ML NUA | `amdgpu-next-use` |
| GFX NUA | `amdgpu-next-use-analysis` |

### 2.6 Parsing Timer Output

Timer lines can be extracted from stderr with:

```bash
grep -E "Time spent in|Total Execution" output.log
```

The wall-time value for a specific timer can be extracted with:

```bash
grep "Time spent in analyze" output.log | grep -oE '[0-9]+\.[0-9]+' | head -1
```

## 3. Patch for GFX NUA

The patch below adds timer instrumentation to the GFX NUA implementation. It
modifies two files and adds ~60 lines of code. No existing behavior is changed;
timers are only active when `-amdgpu-next-use-analysis-timers` is passed.

### 3.1 Applying the Patch

Save the diff below as `nua-timers.patch` in the GFX NUA repository root and
run:

```bash
git apply nua-timers.patch
```

Then rebuild `llc`:

```bash
cd build/Release-with-asserts && ninja llc
```

### 3.2 Patch Contents

```diff
diff --git a/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp b/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp
index 4225b8a72e3b..38095195e53d 100644
--- a/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp
+++ b/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.cpp
@@ -15,6 +15,7 @@
 #include "llvm/IR/ModuleSlotTracker.h"
 #include "llvm/InitializePasses.h"
 #include "llvm/Support/FileSystem.h"
+#include "llvm/Support/Timer.h"
 #include "llvm/Support/ToolOutputFile.h"
 
 #include <cmath>
@@ -36,6 +37,21 @@ static cl::opt<bool>
     DumpNextUseDistanceVerbose("amdgpu-next-use-analysis-dump-distance-verbose",
                                cl::init(false), cl::Hidden);
 
+static cl::opt<bool>
+    EnableTimers("amdgpu-next-use-analysis-timers",
+                 cl::desc("Enable timing for Next Use Analysis"),
+                 cl::init(false), cl::Hidden);
+
+static cl::opt<bool>
+    PerFunctionTimers("amdgpu-next-use-per-function-timers",
+                      cl::desc("Print per-function timer breakdown"),
+                      cl::init(false), cl::Hidden);
+
+static TimerGroup TG("AMDGPU Next Use Analysis",
+                      "AMDGPU Next Use Analysis");
+static Timer InitTimer("init", "Time spent in initialize()", TG);
+static Timer QueryTimer("query", "Time spent in exerciseQueries()", TG);
+
 static cl::opt<AMDGPUNextUseAnalysis::CompatibilityMode> CompatModeOpt(
     "amdgpu-next-use-analysis-compatibility-mode", cl::Hidden,
     cl::init(AMDGPUNextUseAnalysis::CompatibilityMode::Graphics),
@@ -628,6 +644,8 @@ public:
                SmallVector<const MachineOperand *> &Uses);
 
   void printFurthestDistancesAsJson(raw_ostream &OS, const LiveIntervals *LIS);
+
+  void exerciseQueries();
 };
 
 void AMDGPUNextUseAnalysisImpl::calcInstrIds(
@@ -1664,6 +1682,27 @@ void AMDGPUNextUseAnalysisImpl::printFurthestUse(raw_ostream &OS,
   OS << "      }" << (Last ? "\n" : ",\n");
 }
 
+void AMDGPUNextUseAnalysisImpl::exerciseQueries() {
+  for (const MachineBasicBlock &MBB : *MF) {
+    for (const MachineInstr &MI : MBB) {
+      for (const MachineOperand &MO : MI.operands()) {
+        if (!MO.isReg() || MO.isUse())
+          continue;
+        Register Reg = MO.getReg();
+        if (Reg.isPhysical() || TRI->isAGPR(*MRI, Reg))
+          continue;
+        SmallVector<const MachineOperand *> Uses;
+        for (MachineOperand &UseMO : MRI->use_nodbg_operands(Reg))
+          if (!UseMO.isUndef())
+            Uses.push_back(&UseMO);
+        if (Uses.empty())
+          continue;
+        (void)getNextUseDistance(Reg, MI, Uses);
+      }
+    }
+  }
+}
+
 void AMDGPUNextUseAnalysisImpl::printFurthestDistancesAsJson(
     raw_ostream &OS, const LiveIntervals *LIS) {
   const Function *F = &MF->getFunction();
@@ -1752,6 +1791,10 @@ void AMDGPUNextUseAnalysis::printFurthestDistancesAsJson(
   Impl->printFurthestDistancesAsJson(OS, LIS);
 }
 
+void AMDGPUNextUseAnalysis::exerciseQueries() {
+  Impl->exerciseQueries();
+}
+
 //~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 // AMDGPUNextUseAnalysisPass
 //~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
@@ -1762,7 +1805,22 @@ bool AMDGPUNextUseAnalysisPass::runOnMachineFunction(MachineFunction &MF) {
       &getAnalysis<MachineDominatorTreeWrapperPass>().getDomTree();
 
   NUA = std::make_unique<AMDGPUNextUseAnalysis>();
-  NUA->initialize(&MF, MLI, DT);
+  {
+    llvm::TimeRegion TR(EnableTimers ? &InitTimer : nullptr);
+    NUA->initialize(&MF, MLI, DT);
+  }
+
+  if (EnableTimers) {
+    {
+      llvm::TimeRegion TR(QueryTimer);
+      NUA->exerciseQueries();
+    }
+    if (PerFunctionTimers) {
+      llvm::errs() << "=== " << MF.getName()
+                    << " (" << MF.size() << " BBs) ===\n";
+      TG.print(llvm::errs(), /*ResetAfterPrint=*/true);
+    }
+  }
 
   if (DumpNextUseDistanceAsJson.getNumOccurrences()) {
     const LiveIntervals *LIS =
diff --git a/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h b/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h
index 24fe3a1d7a80..8f1c4bebd4d3 100644
--- a/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h
+++ b/llvm/lib/Target/AMDGPU/AMDGPUNextUseAnalysis.h
@@ -60,6 +60,8 @@ public:
                SmallVector<const MachineOperand *> &Uses);
 
   void printFurthestDistancesAsJson(raw_ostream &OS, const LiveIntervals *LIS);
+
+  void exerciseQueries();
 };
 
 //------------------------------------------------------------------------------
```

## 4. Benchmarking Procedure

### 4.1 Build Configuration

Use **Release-with-asserts** (`-DCMAKE_BUILD_TYPE=Release`,
`-DLLVM_ENABLE_ASSERTIONS=ON`). This gives optimized code with safety checks
enabled.

### 4.2 Test Input

Recommended: Blender Cycles `bigSSA.mir` -- a 235 MB MIR file containing 310
GPU kernels ranging from 1 basic block to 9743 basic blocks. This provides a
realistic, large-scale workload.

### 4.3 Measurement Modes

**Mode 1: Aggregate timers (recommended for comparison)**

```bash
# ML NUA
llc -march=amdgcn -mcpu=gfx1030 \
    -run-pass=amdgpu-next-use \
    -amdgpu-next-use-analysis-timers \
    -o /dev/null bigSSA.mir

# GFX NUA
llc -march=amdgcn -mcpu=gfx1030 \
    -run-pass=amdgpu-next-use-analysis \
    -amdgpu-next-use-analysis-timers \
    -o /dev/null bigSSA.mir
```

Produces one timer report per implementation with init and query breakdown.

**Mode 2: Per-function timers (for investigating scaling)**

```bash
llc -march=amdgcn -mcpu=gfx1030 \
    -run-pass=<pass-name> \
    -amdgpu-next-use-analysis-timers \
    -amdgpu-next-use-per-function-timers \
    -o /dev/null bigSSA.mir 2> per_function.log
```

Produces 310 individual timer reports, each tagged with function name and BB
count. Useful for verifying that analysis time scales with function size.

**Mode 3: Wall time only (baseline)**

```bash
time llc -march=amdgcn -mcpu=gfx1030 \
    -run-pass=<pass-name> \
    -o /dev/null bigSSA.mir 2>/dev/null
```

Measures total wall time including MIR parsing, with no dump or timer overhead.

### 4.4 Key Metrics

| Metric | Source | Description |
|---|---|---|
| `wall_sec` | `time` or `/usr/bin/time` | Total elapsed time including parsing |
| `init_sec` | Timer output | Time in initialization / analysis phase |
| `query_sec` | Timer output | Time in `exerciseQueries()` |
| `init_%` | `100 * init_sec / wall_sec` | Fraction of wall time spent in init |
| `query_%` | `100 * query_sec / wall_sec` | Fraction of wall time spent in queries |
| `overhead_sec` | `wall_sec - init_sec - query_sec` | MIR parsing + pass setup (shared, not NUA-specific) |

### 4.5 Example Results (ML NUA, Blender, Release-with-asserts)

```
  wall_sec  analyze_sec  analyze_%  query_sec    query_%  num_functions
     40.16       3.5988      8.96%     2.3640      5.88%            310
```

Interpretation: of 40 s total, ~6 s is NUA work (analyze + query), ~34 s is
MIR parsing and pass infrastructure overhead shared by both implementations.
