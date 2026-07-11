# SSARA Fix Report — §4.4 "Tied use must be colored already" (18 crashes)

**Date:** 2026-07-10
**Author:** analysis for review (no sources edited)
**Crash class:** §4.4 of `CRASH_TRIAGE_REPORT_2026-07-10.md` — `assert: Chosen && "Tied use must be colored already"` (18 tests)
**File to change:** `llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp`, function `color()`
**Status:** root-caused with evidence; patch proposed below; **not applied**, not yet corpus-tested.

---

## 1. Summary

All 18 crashes in this class share a single root cause: an instruction with a
**tied `undef` passthrough operand whose register is the def's own vreg** — the
standard LLVM idiom for a partial/passthrough def where the "old" value is a
don't-care. `color()` reaches the tied def, tries to *inherit* the color of the
tied use, finds it uncolored (it is the very vreg being defined), and asserts.

The fix: when the tied use is `undef`, there is no prior value to inherit — color
the def like an ordinary def via `pickFreePhysReg`. `rewriteOperands()` later
assigns the same physreg to the self-tied use (it is the same vreg), so
two-address form is preserved.

---

## 2. Root cause

`color()` handles a tied def like this
(`AMDGPUSSARegisterAllocator.cpp:388-401`):

```cpp
MCRegister Chosen;
unsigned UseOpIdx;
if (MI.isRegTiedToUseOperand(MO.getOperandNo(), &UseOpIdx)) {
  Chosen = ColorMap.lookup(MI.getOperand(UseOpIdx).getReg());
  assert(Chosen && "Tied use must be colored already");   // <-- fires
  ...
} else {
  Chosen = pickFreePhysReg(...);
  ...
}
```

The invariant "a tied use is always colored before its tied def" holds for a
normal two-address instruction `%dst = OP %src(tied), ...`, because `%src` is a
distinct, earlier-defined SSA value. It does **not** hold for a **self-tied
`undef`** operand:

```
%16:vgpr_32 = V_ADD_U32_dpp undef %16, %14, %14, 1, 15, 15, 1, implicit $exec
              ^^^^^^^^^^^^^^ tied use == the def's own vreg, undef
```

Here the tied use *is* `%16`, the register currently being defined, so
`ColorMap.lookup(%16)` is empty and `Chosen` is null.

This pattern is produced by ISel for instructions with a passthrough/"old" input
that the program does not actually read:
- **DPP** ops (`V_ADD_U32_dpp`, `V_MOV_B32_dpp`, `V_CEIL_F32_dpp`, …): the "old"
  operand is a tied passthrough.
- **D16 loads** (`DS_READ_U16_D16`, `DS_READ_U16_D16_HI`): the untouched half is a
  tied passthrough.
- **MIX ops** (`V_FMA_MIXLO_BF16`): the low/high-half passthrough is tied.

---

## 3. Evidence

Reproduced from the pre-RA MIR (`-stop-before=amdgpu-ssa-register-allocator`).
For every crash instruction the tied self-use carries the `undef` flag — i.e.
there are **zero** cases where the self-tied use is a real (color-bearing) value:

| Test | mcpu | self-tie `undef` | self-tie non-`undef` |
|---|---|---:|---:|
| `dpp_combine.ll` | gfx900 | 4 | 0 |
| `mad-mix-lo-bf16.ll` | gfx1250 | 15 | 0 |
| `load-hi16.ll` | gfx900 | 1 | 0 |

Representative instructions:

```
%16:vgpr_32 = V_ADD_U32_dpp undef %16, %14, %14, 1, 15, 15, 1, implicit $exec        (dpp_combine)
%21:vgpr_32 = V_MOV_B32_dpp undef %21, %82, 0, 0, 0, 0, implicit $exec               (dpp64_combine)
%9:vgpr_32  = DS_READ_U16_D16_HI %8, 0, 0, undef %9, implicit $exec                  (load-hi16)
%11:vgpr_32 = nofpexcept V_FMA_MIXLO_BF16 0,%8,0,%9,0,%10,0, undef %11, 0,0, ...     (mad-mix-lo-bf16)
```

Crash backtrace (all 18 identical modulo function name):

```
AMDGPUSSARegisterAllocator.cpp:392: void llvm::AMDGPUSSARegisterAllocator::color():
Assertion `Chosen && "Tied use must be colored already"' failed.
#12 AMDGPUSSARegisterAllocator::color()            AMDGPUSSARegisterAllocator.cpp:393
#13 AMDGPUSSARegisterAllocator::runOnMachineFunction AMDGPUSSARegisterAllocator.cpp:965
```

### Affected tests (all 18)

```
GlobalISel/llvm.amdgcn.wqm.demote.ll   chain-hi-to-lo.ll
dpp64_combine.ll                       dpp_combine.ll
global-load-saddr-to-vaddr.ll          global-saddr-load.ll
llvm.amdgcn.cvt.fp8.dpp.ll             llvm.amdgcn.permlane16.var.ll
llvm.amdgcn.update.dpp.gfx90a.ll       llvm.amdgcn.wqm.demote.ll
llvm.cos.bf16.ll                       llvm.sin.bf16.ll
load-hi16.ll                           load-lo16.ll
mad-mix-hi-bf16.ll                     mad-mix-lo-bf16.ll
mixed-wave32-wave64.ll                 promote-alloca-globals.ll
```

---

## 4. Why the fix is correct

1. **The value is a genuine don't-care.** The `undef` flag on the tied use means
   the hardware reads whatever is in the register; the program does not depend on
   it. Coloring the def to any free physreg is legal.

2. **Two-address form is preserved.** For a self-tie the tied use and the def are
   the *same vreg* (`%16`). After the def is colored and recorded in `ColorMap`,
   `rewriteOperands()` rewrites *all* operands of that vreg — including the tied
   use — to the same physreg. So `Dst == tied-Src` still holds; no extra copy is
   needed and the two-address constraint is satisfied.

3. **Liveness is unaffected.** `pickFreePhysReg` already considers the def's
   `LiveInterval` and `WiderDefs`; the `undef` use adds no live range (it is not
   live-in). This matches what the greedy allocator does for such operands.

4. **No behavioral change for normal tied defs.** The inherit path is unchanged
   whenever the tied use is already colored; only the previously-asserting case
   (uncolored + `undef`) now takes the free-pick path.

### Edge cases considered
- **Tied use uncolored but NOT undef.** Should be impossible in valid SSA input
  (a real tied source is always defined earlier). The patch keeps a hard failure
  (`llvm_unreachable`) for this case rather than silently mis-coloring — turns a
  future violated-invariant into a loud, localized error instead of a UB miscompile.
- **Wider/aligned tuples.** `pickFreePhysReg` is the same routine used for
  ordinary wide defs, so alignment handling is unchanged.
- **Non-self tie (dst tied to a different undef vreg).** Not observed in the
  corpus, but the patch handles it: it colors `dst` freshly; `rewriteOperands`
  colors the other (undef) vreg independently via its own `ColorMap` entry, or —
  if that vreg is never colored — via the existing undef fallback in
  `rewriteOperands()` (line ~792). This does not force `dst == src`, but because
  the source is `undef` the tie is a don't-care and the machine verifier accepts
  an undef tied source. (If we want to *guarantee* `dst == src` even here we could
  extend the patch; flagged for reviewer preference.)

---

## 5. Proposed patch (unified diff)

```diff
--- a/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp
+++ b/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp
@@ -387,15 +387,29 @@ void AMDGPUSSARegisterAllocator::color() {
 
           MCRegister Chosen;
           unsigned UseOpIdx;
-          if (MI.isRegTiedToUseOperand(MO.getOperandNo(), &UseOpIdx)) {
-            Chosen = ColorMap.lookup(MI.getOperand(UseOpIdx).getReg());
-            assert(Chosen && "Tied use must be colored already");
+          bool IsTied = MI.isRegTiedToUseOperand(MO.getOperandNo(), &UseOpIdx);
+          if (IsTied &&
+              (Chosen = ColorMap.lookup(MI.getOperand(UseOpIdx).getReg()))) {
+            // Ordinary two-address def: inherit the tied use's color.
             LLVM_DEBUG(dbgs() << "    tied: " << printReg(Reg, TRI)
                               << " inherits " << TRI->getName(Chosen) << "\n");
+          } else if (IsTied && MI.getOperand(UseOpIdx).isUndef()) {
+            // The tied use is an `undef` passthrough (the DPP "old" source
+            // `%N = V_..._dpp undef %N, ...`, a D16 load's untouched half, or a
+            // MIX partial def). Its value is a don't-care, so there is no
+            // earlier color to inherit -- color the def like a normal def.
+            // rewriteOperands() then assigns the same physreg to the self-tied
+            // use (same vreg), preserving two-address form.
+            Chosen = pickFreePhysReg(MRI->getRegClass(Reg),
+                                     LIS->getInterval(Reg), WiderDefs);
+            assert(Chosen && "Failed to find free physreg");
+            LLVM_DEBUG(dbgs() << "    color (undef self-tie): "
+                              << printReg(Reg, TRI) << " -> "
+                              << TRI->getName(Chosen) << "\n");
+          } else if (IsTied) {
+            llvm_unreachable("Tied use must be colored already or undef");
           } else {
             Chosen = pickFreePhysReg(MRI->getRegClass(Reg),
                                      LIS->getInterval(Reg), WiderDefs);
             assert(Chosen && "Failed to find free physreg");
             LLVM_DEBUG(dbgs() << "    color: " << printReg(Reg, TRI) << " -> "
                               << TRI->getName(Chosen) << "\n");
           }
```

Note: the assignment-inside-`if` (`(Chosen = ColorMap.lookup(...))`) mirrors the
existing style elsewhere in this file (e.g. `if (auto It = ColorMap.find(Reg); ...)`);
if you prefer no assignment-in-condition I can restructure with an explicit
lookup + branch.

---

## 6. Suggested validation

1. Build: `ninja -C build/user-debug LLVMAMDGPUCodeGen llc`
2. Spot-check the repros compile and verify:
   ```bash
   for t in dpp_combine dpp64_combine load-hi16 load-lo16 mad-mix-lo-bf16 mad-mix-hi-bf16; do
     build/user-debug/bin/llc <RUN-flags> -amdgpu-ssa-regalloc -verify-machineinstrs \
       llvm/test/CodeGen/AMDGPU/$t.ll -o /dev/null && echo "$t OK" || echo "$t FAIL"
   done
   # mad-mix uses gfx1250; dpp_combine/load-* use gfx900 (see each test's RUN line)
   ```
3. Full corpus gate (per project policy — local lit is too narrow):
   ```bash
   python3 scripts/ssara_corpus_harness.py run --jobs 96 --timeout 120 --out /tmp/out-tiedfix
   python3 scripts/ssara_corpus_harness.py report --out /tmp/out-tiedfix
   ```
   Expect: CRASH 195 → ~177; confirm no new crashes in other buckets and no
   MIXED/REGRESSION net regression.

---

## 7. Risk assessment

- **Blast radius:** one `color()` branch; behavior changes only for the
  previously-asserting (crashing) case. Low risk of regressing currently-passing
  tests.
- **Interaction with coalescing work (§4.1/§6):** none — this does not touch
  color *choice* for cross-call values, only unblocks a case that currently
  aborts.
- **Verifier:** the def gets a valid free physreg; the self-tied undef use is
  rewritten to the same physreg. `-verify-machineinstrs` should pass (validate in
  step 2).
