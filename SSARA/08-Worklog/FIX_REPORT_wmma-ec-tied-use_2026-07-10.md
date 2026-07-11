# SSARA Fix Report — §4.2 sub-cause A: WMMA early-clobber tied-use RMW (28 crashes)

**Date:** 2026-07-10
**Author:** analysis for review (no sources edited)
**Crash class:** §4.2 of `CRASH_TRIAGE_REPORT_2026-07-10.md` —
`MachineVerifier: Reading virtual register without a def`.
**This report covers sub-cause A only** (28 of the 31 tests: the WMMA accumulators).
The other 3 tests (`amdgcn.bitcast.{320,384,448}bit`) are a **different** root cause
(wide partial-def-chain REG_SEQUENCE) and need more investigation — tracked
separately, not addressed here.
**Failing pass:** `AMDGPU Rebuild SSA` (verified — not the spiller or RA).
**Status:** root-caused with evidence; patch proposed below; **not applied**, not yet
corpus-tested.

---

## 1. Summary

The 28 WMMA crashes share one root cause in `MachineLaneSSAUpdater`. A two-address
WMMA accumulator is a **read-modify-write with an early-clobber def**. When
RebuildSSA renames the WMMA's def to a fresh vreg, the WMMA's own **tied use** must
be rewritten to read the *incoming* accumulator value (the partial-COPY chain that
built it). It is not — because the reaching-value query for the tied use is taken at
the plain register slot, where the WMMA's **own early-clobber def** already sits. The
query therefore resolves to the instruction's own def instead of the incoming value,
no incoming def ever "owns" the tied-use lanes, and the tied use is left dangling as
the now-def-less `OrigVReg`.

The fix: query the reaching value for a **tied use** at the instruction's *base
index* (the read point), which precedes every def slot — including the early-clobber
def — so the incoming value is seen and the tied use is rewritten correctly.

---

## 2. Symptom

`wmma-gfx12-w32.ll` (gfx1200), after RebuildSSA, `-verify-machineinstrs`:

```
*** Bad machine code: Reading virtual register without a def ***
- instruction: early-clobber %76:vreg_256 = V_WMMA_F32_16X16X16_F16_w32_twoaddr
      8, %69, 8, %70, 8, %71:vreg_256(tied-def 0), 0, 0, implicit $exec
- operand 6:   %71:vreg_256(tied-def 0)
*** Bad machine code: Two-address instruction operands must be identical ***
- operand 6:   %71:vreg_256(tied-def 0)
```

The def was renamed `%71 → %76`, but the tied use (operand 6) still reads `%71`,
which now has no def.

---

## 3. Input MIR (before RebuildSSA)

`%71` is a two-address WMMA accumulator with **9 defs**: 8 partial-subreg COPYs that
assemble it lane-by-lane, then the WMMA that reads and redefines it.

```
undef %71.sub7:vreg_256 = COPY $vgpr15
%71.sub6:vreg_256 = COPY $vgpr14
%71.sub5:vreg_256 = COPY $vgpr13
%71.sub4:vreg_256 = COPY $vgpr12
%71.sub3:vreg_256 = COPY $vgpr11
%71.sub2:vreg_256 = COPY $vgpr10
%71.sub1:vreg_256 = COPY $vgpr9
%71.sub0:vreg_256 = COPY $vgpr8
early-clobber %71:vreg_256 = V_WMMA_..._twoaddr 8, %69, 8, %70, 8, %71, 0, 0, ...
GLOBAL_STORE_DWORDX4 %68, %71.sub4_sub5_sub6_sub7, ...
GLOBAL_STORE_DWORDX4 %68, %71.sub0_sub1_sub2_sub3, ...
```

---

## 4. What RebuildSSA does (trace)

`%71` has 9 VNs. From
`-debug-only=amdgpu-rebuild-ssa,machine-lane-ssa-updater`:

1. **WMMA def processed first** (`%71 → %76`, DefMask=0xFFFF). `performSSARepair`
   rewrites the two `GLOBAL_STORE` uses to `%76` and recomputes `%71`'s interval.
   The WMMA's own tied use is correctly **skipped** here by the
   `UseMI == DefMI && !isPHI` guard (`MachineLaneSSAUpdater.cpp:529`) — at this
   moment the tied use must read the *incoming* accumulator, not `%76`.
2. **Then the 8 partial COPYs** (`%71.sub0..sub7 → %77..%84`). Each runs
   `rewriteDominatedUses(%71, %77.., laneMask)`, iterating `MRI.use_operands(%71)`.
   The WMMA tied use **is** in that set and **is** visited.

The 6 emitted `[reaching] use` rewrites are all `GLOBAL_STORE` / `REG_SEQUENCE` —
**the WMMA tied use is never among them.** All 9 defs get renamed; the tied use keeps
reading `%71`, now def-less.

---

## 5. Root cause — early-clobber slot collision in the reaching query

`rewriteUseReaching` (`MachineLaneSSAUpdater.cpp:396-447`) computes the reaching-value
query point for a non-PHI use as the plain register slot:

```cpp
} else {
  UsePt = LIS.getInstructionIndex(*UseMI).getRegSlot();   // line 410
}
...
collectReachingVNIs(*FrozenOrigLI, OpMask & MaskToRewrite, UsePt, Pieces);
LaneBitmask Owned = LaneBitmask::getNone();
for (auto &[L, V] : Pieces) {
  if (!V) continue;
  bool Match = (!V->isPHIDef() && V->def == DefSlot);     // line 441
  if (Match) Owned |= L;
}
if (Owned.none())
  return;   // line 446 — nothing owned -> tied use left as dangling %71
```

The WMMA def is **early-clobber**. An early-clobber def's VNInfo sits at the
early-clobber slot `getRegSlot(/*EC=*/true)`, which is **at/adjacent to** the plain
`getRegSlot()`. For the WMMA's own tied use (same instruction),
`getVNInfoBefore(getRegSlot())` on the frozen interval therefore resolves to the
**WMMA's own early-clobber def VNInfo**, not the incoming COPY values.

So when each partial COPY def tests ownership of the WMMA tied-use lanes, the
reaching `V` is the WMMA's own EC def (whose `V->def` is the WMMA EC slot), never a
COPY's `DefSlot`. `Owned` stays empty for every COPY → early return at line 446 →
the tied use is never rewritten and remains a dangling `%71` placeholder that nothing
patches.

**One line:** the tied use of an early-clobber two-address def queries its reaching
value at the plain reg slot, which the instruction's *own* early-clobber def already
occupies — so the incoming (pre-instruction) value is never seen, and the tied use is
never rewritten to it.

---

## 6. Proposed fix

Query the reaching value for a **tied use** at the instruction's *base index* (the
point where the operand is read), which precedes every def slot — including the
early-clobber def — so `getVNInfoBefore` returns the incoming value (the COPY chain).
The partial COPY defs then own the tied-use lanes and rewrite it via the existing
`Owned != OpMask` REG_SEQUENCE path.

```diff
--- a/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp
+++ b/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp
@@ -403,7 +403,17 @@ void MachineLaneSSAUpdater::rewriteUseReaching(
   SlotIndex UsePt;
   if (UseMI->isPHI()) {
     unsigned OpIdx = UseMI->getOperandNo(&MO);
     MachineBasicBlock *Pred = UseMI->getOperand(OpIdx + 1).getMBB();
     UsePt = LIS.getMBBEndIdx(Pred);
   } else {
-    UsePt = LIS.getInstructionIndex(*UseMI).getRegSlot();
+    // A tied use is read before the instruction's own def executes. For an
+    // early-clobber two-address def (e.g. V_WMMA_*_twoaddr accumulator), that
+    // def's VNInfo sits at getRegSlot(EC=true), i.e. at/adjacent to the plain
+    // reg slot; querying the reaching value there resolves to the instruction's
+    // OWN def instead of the incoming value, so the tied use is never rewritten
+    // and is left reading the now-renamed OrigVReg ("Reading virtual register
+    // without a def"). The base index precedes every def slot, so it yields the
+    // incoming value. Non-tied uses are unaffected (no def of OrigVReg on the
+    // use instruction to collide with).
+    SlotIndex Idx = LIS.getInstructionIndex(*UseMI);
+    UsePt = MO.isTied() ? Idx.getBaseIndex() : Idx.getRegSlot();
   }
```

**Why gated to `MO.isTied()`:** for an ordinary (non-tied) use, `getBaseIndex()` and
`getRegSlot()` select the same reaching value (there is no def of `OrigVReg` on the
use instruction), so the gate keeps the change minimal and the blast radius to
exactly the broken case. The unconditional form is likely also correct but touches
every non-PHI rewrite; the gated form is recommended for a tight, corpus-verifiable
change.

**Note on `DefSlot` (line 431):** it is correctly computed with `getRegSlot(EC)` for
*matching a specific def* and must stay as-is. The bug is solely the *use* query
point; once `UsePt` uses the base index for tied uses, the partial COPYs match and
build the REG_SEQUENCE via the existing path.

---

## 7. Why the fix is correct

1. **A tied use reads before the def.** By definition of two-address / early-clobber
   semantics, the tied source is consumed before the instruction produces its
   result. The base index is the read slot; querying there yields the value that
   actually flows in — the assembled COPY chain — which is what the tied use must
   name after SSA rename.
2. **Existing partial-source machinery handles the rest.** With `Owned` now non-empty
   per COPY, the `Owned != OpMask` branch builds a REG_SEQUENCE of `%77..%84`
   (`buildRSForSuperUse`), exactly as it already does for the two `GLOBAL_STORE`
   super-uses in this same function. No new code path.
3. **Two-address form is restored.** After the tied use is rewritten to the assembled
   incoming value and the def is `%76`, the subsequent RA/two-address handling sees a
   well-formed tied pair; the verifier's "operands must be identical" also clears
   because the dangling `%71` is gone.
4. **Non-tied uses unchanged.** The gate leaves every non-tied rewrite on the
   existing `getRegSlot()` path.

### Edge cases considered
- **Non-early-clobber tied def** (plain two-address, def at regular reg slot): the
  base index still correctly precedes the def, so the incoming value is returned —
  same correct result, no regression.
- **Tied use where the incoming value is genuinely dead on some path**: handled by
  the existing `AddOldGroup` undef classification in `buildRSForSuperUse` (null
  reaching VNI → undef source), unchanged by this patch.
- **PHI uses**: untouched (separate `UseMI->isPHI()` branch).

---

## 8. Affected tests (sub-cause A, 28)

```
GlobalISel/llvm.amdgcn.wmma_32.ll        GlobalISel/llvm.amdgcn.wmma_64.ll
GlobalISel/wmma-gfx12-w32-f16-f32-matrix-modifiers.ll
GlobalISel/wmma-gfx12-w32-iu-modifiers.ll
GlobalISel/wmma-gfx12-w32-swmmac-index_key.ll
GlobalISel/wmma-gfx12-w32.ll
GlobalISel/wmma-gfx12-w64-f16-f32-matrix-modifiers.ll
GlobalISel/wmma-gfx12-w64-iu-modifiers.ll
GlobalISel/wmma-gfx12-w64-swmmac-index_key.ll
GlobalISel/wmma-gfx12-w64.ll
llvm.amdgcn.wmma.gfx1250.w32.ll          llvm.amdgcn.wmma.imm.gfx1250.w32.ll
llvm.amdgcn.wmma.imod.gfx1250.w32.ll     llvm.amdgcn.wmma.index.gfx1250.w32.ll
llvm.amdgcn.wmma_32.ll                    llvm.amdgcn.wmma_64.ll
wmma-gfx12-w32-f16-f32-matrix-modifiers.ll   wmma-gfx12-w32-imm.ll
wmma-gfx12-w32-iu-modifiers.ll           wmma-gfx12-w32-swmmac-index_key.ll
wmma-gfx12-w32.ll                        wmma-gfx12-w64-f16-f32-matrix-modifiers.ll
wmma-gfx12-w64-imm.ll                    wmma-gfx12-w64-iu-modifiers.ll
wmma-gfx12-w64-swmmac-index_key.ll       wmma-gfx12-w64.ll
wmma_multiple_32.ll                      wmma_multiple_64.ll
```

(NOT included — sub-cause B, separate report: `amdgcn.bitcast.{320,384,448}bit.ll`.)

---

## 9. Validation plan

```bash
ninja -C build/user-debug LLVMCodeGen llc     # MachineLaneSSAUpdater lives in CodeGen

# spot-check WMMA repros compile + verify (adjust mcpu/-global-isel per each RUN line):
for t in wmma-gfx12-w32 wmma-gfx12-w64 llvm.amdgcn.wmma_32 llvm.amdgcn.wmma_64 \
         wmma_multiple_32 wmma_multiple_64; do
  build/user-debug/bin/llc -mtriple=amdgcn -mcpu=gfx1200 -amdgpu-ssa-regalloc \
    -verify-machineinstrs llvm/test/CodeGen/AMDGPU/$t.ll -o /dev/null \
    && echo "$t OK" || echo "$t FAIL"
done
# gfx1250 tests: -mcpu=gfx1250 ; GlobalISel variants: add -global-isel

# full corpus gate (per project policy — local lit is too narrow):
python3 scripts/ssara_corpus_harness.py run --jobs 96 --timeout 120 --out /tmp/out-wmmafix
python3 scripts/ssara_corpus_harness.py report --out /tmp/out-wmmafix
```

Expect: CRASH 195 → ~167 (−28). Confirm no new `Invalid subregister index` /
`incorrect register class` regressions — the reaching-query change alters how tied
uses are rebuilt into REG_SEQUENCEs, so the corpus is the gate.

---

## 10. Risk

- **Blast radius:** one line, gated to `MO.isTied()`. Changes the reaching value only
  for tied uses — precisely today's broken case.
- **Interaction:** independent of the §4.1 coalescer work and of the §4.4 tied-undef
  RA fix (that was in the *allocator*; this is in the *SSA updater*, shared by
  RebuildSSA and the spiller — so it also hardens the spiller's reload repair for any
  early-clobber tied RMW).

---

## 11. Evidence commands (reproducible)

```bash
# accumulator RMW in the input:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=gfx1200 -amdgpu-ssa-regalloc \
  -stop-before=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/wmma-gfx12-w32.ll -o - \
  | grep -B8 WMMA          # 8 partial COPYs + early-clobber WMMA reading %71

# dangling tied use after RebuildSSA:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=gfx1200 -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/wmma-gfx12-w32.ll -o - 2>&1 \
  | grep -A2 "Reading virtual register"     # %76 def, %71 tied use def-less

# trace showing WMMA tied use never rewritten (6 reaching rewrites, none WMMA):
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=gfx1200 -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-rebuild-ssa \
  -debug-only=amdgpu-rebuild-ssa,machine-lane-ssa-updater \
  llvm/test/CodeGen/AMDGPU/wmma-gfx12-w32.ll -o /dev/null 2>&1 \
  | grep "\[reaching\] use"
```
