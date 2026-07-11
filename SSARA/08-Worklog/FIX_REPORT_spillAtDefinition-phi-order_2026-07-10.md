# SSARA Fix Report — "Found PHI instruction after non-PHI" (10 crashes)

**Date:** 2026-07-10
**Author:** analysis for review (fix validated on-tree, then stashed; tree clean)
**Crash class:** postfix corpus (`/tmp/corpus-postfix`, CRASH=103) —
`MachineVerifier: Found PHI instruction after non-PHI` (10 tests).
**Failing pass:** `AMDGPU SSA Register Spiller` — **proven by bisect**, NOT RebuildSSA.
**Root cause:** `spillAtDefinition` inserts a spill store at `std::next(DefMI)` when
the def is a PHI, landing the store between PHIs.
**Fix:** insert after the last PHI (`getFirstNonPHI()`) when the def is a PHI.
**Status:** fix written and validated (0 verifier errors; tests advance past this
bug); reverted to a git stash pending review. One-line diff below.

---

## 1. Affected tests (10)

```
amdgcn.bitcast.1024bit.ll   amdgcn.bitcast.512bit.ll    amdgcn.bitcast.640bit.ll
amdgcn.bitcast.320bit.ll    amdgcn.bitcast.704bit.ll    amdgcn.bitcast.768bit.ll
amdgcn.bitcast.832bit.ll    amdgcn.bitcast.960bit.ll    amdgcn.bitcast.896bit.ll
vgpr-mark-last-scratch-load.ll
```

---

## 2. Bisect — it is the spiller, not RebuildSSA

Initial suspicion was RebuildSSA (the crashing verify prints as CGSCC "pass #2").
That was **wrong**; a `-stop-after` / `-run-pass` bisect settled it:

1. Dump MIR after RebuildSSA:
   `llc ... -stop-after=amdgpu-rebuild-ssa -o afterRebuild.mir` → **exit 0**.
2. Verify that MIR standalone:
   `llc ... -run-pass=none -verify-machineinstrs afterRebuild.mir` → **exit 0, 0
   errors**. RebuildSSA output is clean.
3. Run the spiller on that clean MIR:
   `llc ... -run-pass=amdgpu-ssa-register-spiller -verify-machineinstrs afterRebuild.mir`
   → **11 "Found PHI instruction after non-PHI", all in `bitcast_v20i16_to_v40i8`
   %bb.1 Flow**.

Input clean, spiller output broken ⇒ the spiller introduces the misorder. (The
`Invalid Object Idx` seen in some `-run-pass`/`-stop-after` invocations is a
*separate* frame-index bug on the inverse function `bitcast_v40i8_to_v20i16`, not
this class.)

---

## 3. Root cause

Runtime evidence (temporary `LLVM_DEBUG` at the end of `emitReloadsAndRepairSSA`,
scanning each block for a PHI after a non-PHI):

```
[DBG-D] MISORDERED in %bb.1
   firstNonPHI = SI_SPILL_V32_SAVE %711:vgpr_32, %stack.12, $sgpr32, 0, ...
```

The non-PHI sitting **before** the block's PHIs is a **spill store**
(`SI_SPILL_V32_SAVE`). `%711` is a **PHI def**:
```
%711:vgpr_32 = PHI %710:vgpr_32, %bb.1, %712:vgpr_32, %bb.2
```

`spillAtDefinition` stores a value "right after its definition"
(`AMDGPUSSARegisterSpiller.cpp:1443-1444`):

```cpp
MachineBasicBlock *DefMBB = DefMI->getParent();
MachineBasicBlock::iterator InsertAfter = std::next(DefMI->getIterator());
...
TII->storeRegToStackSlot(*DefMBB, InsertAfter, VReg, ...);
```

When `DefMI` is a PHI and the block has multiple PHIs (bb.1 Flow here has ~40),
`std::next(PHI)` points at the **next PHI**, so the store is inserted **between two
PHIs**. Every PHI after that store then violates the MIR invariant "all PHIs must be
contiguous at the block top" → "Found PHI instruction after non-PHI".

This is the only spill/reload path with the bug:
- reloads use `InsertBefore->getIterator()` or `getFirstTerminator()` — safe;
- `spillBefore` uses the caller's `InsertBefore` — safe;
- only `spillAtDefinition` uses `std::next(DefMI)` and can see a PHI `DefMI`.

A PHI value gets spilled-at-definition here because the reconstruction (RebuildSSA /
spiller reload repair) turned wide bitcast values into per-lane PHIs in the Flow
block, and the spiller then chooses some of those PHI results as spill candidates.

---

## 4. Fix

Insert the store after the **last** PHI when the def is a PHI, preserving the
PHIs-at-top invariant; otherwise keep `std::next(DefMI)`.

```diff
--- a/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp
+++ b/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterSpiller.cpp
@@ spillAtDefinition
   MachineBasicBlock *DefMBB = DefMI->getParent();
-  MachineBasicBlock::iterator InsertAfter = std::next(DefMI->getIterator());
+  // Store right after the def. When the def is a PHI, all PHIs must stay
+  // contiguous at the block top, so std::next(PHI) could land the store between
+  // PHIs ("PHI after non-PHI"). Insert after the last PHI instead.
+  MachineBasicBlock::iterator InsertAfter =
+      DefMI->isPHI() ? DefMBB->getFirstNonPHI()
+                     : std::next(DefMI->getIterator());
```

`MachineBasicBlock::getFirstNonPHI()` returns the first non-PHI iterator (block end
if all-PHI), i.e. exactly the earliest legal store position after all PHIs.

### Correctness
- **Semantics preserved.** The store must observe the PHI result's value, which is
  fully defined at the block top (all PHIs execute as a parallel copy on entry). Any
  position after the last PHI reads the same value; `getFirstNonPHI()` is the
  earliest such point, so the "store while EXEC is full, before divergent control
  flow" intent of `spillAtDefinition` is kept (no branch sits between the PHIs and
  the first non-PHI).
- **Non-PHI defs unchanged.** The ternary leaves the existing `std::next(DefMI)`
  path for ordinary defs.
- **SlotIndexes.** The store is indexed via `LIS->InsertMachineInstrInMaps` exactly
  as before, just at a slightly later position; no PHI is displaced.

---

## 5. Validation (on-tree, then reverted to stash)

Built `llc` with the one-line fix and re-ran the affected tests:

| test | before | after fix |
|---|---|---|
| `vgpr-mark-last-scratch-load.ll` | crash (PHI-after-non-PHI) | **compiles, exit 0** |
| `amdgcn.bitcast.320bit.ll` | 11 PHI errors | **0 PHI errors** → advances to a *separate* `Invalid Object Idx` (§4.7) |
| `amdgcn.bitcast.512bit.ll` | PHI-after-non-PHI | **0 PHI errors** → advances to §4.1 `Failed to find free physreg` |
| `amdgcn.bitcast.1024bit.ll` | PHI-after-non-PHI | **0 PHI errors** → advances to §4.1 |

The fix eliminates this crash class cleanly. The bitcast tests then hit their *next*
pre-existing bug (§4.1 coalescer or §4.7 frame-index) — expected, not a regression
introduced by this change. `vgpr-mark-last-scratch-load` is fully fixed.

Recover the validated change with:
```bash
git stash list   # "spillAtDefinition PHI fix (validated)"
git stash pop
```

---

## 6. Suggested full validation
```bash
ninja -C build/user-debug LLVMAMDGPUCodeGen llc
# spot-check:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -verify-machineinstrs llvm/test/CodeGen/AMDGPU/vgpr-mark-last-scratch-load.ll -o /dev/null && echo OK
# corpus gate:
python3 scripts/ssara_corpus_harness.py run --jobs 96 --timeout 120 --out /tmp/out-phifix
python3 scripts/ssara_corpus_harness.py report --out /tmp/out-phifix
```
Expect: `Found PHI instruction after non-PHI` → 0; CRASH drops by up to 10 (some
bitcast tests will re-bucket into §4.1/§4.7 rather than disappear, since they have
further bugs). Confirm no new regressions.

---

## 7. Risk
- **Blast radius:** one line in `spillAtDefinition`, gated to `DefMI->isPHI()`. Only
  changes store placement for spilled PHI-result values — the crashing case.
- **Interaction:** independent of the WMMA/padding/NewDefMI fixes. Purely a
  placement correction; does not affect which values are spilled or their liveness.

---

## 8. Evidence commands (debug prints since removed)
```bash
# bisect: RebuildSSA output clean
llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc -stop-after=amdgpu-rebuild-ssa \
  llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o /tmp/afterRebuild.mir
llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc -run-pass=none \
  -verify-machineinstrs /tmp/afterRebuild.mir -o /dev/null            # exit 0

# spiller breaks it
llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -run-pass=amdgpu-ssa-register-spiller -verify-machineinstrs \
  /tmp/afterRebuild.mir -o /dev/null 2>&1 | grep -c "Found PHI instruction after non-PHI"  # 11

# the offending non-PHI is a spill store of a PHI result (%711 = PHI ...)
```
