# SSARA Fix Report — §4.2 sub-cause B: oversized-class padding lanes (3 crashes)

**Date:** 2026-07-10
**Author:** analysis for review (no sources edited; debug prints used during
investigation were removed, tree verified clean)
**Crash class:** §4.2 of `CRASH_TRIAGE_REPORT_2026-07-10.md` —
`MachineVerifier: Reading virtual register without a def` (+ `Invalid subregister
index for virtual register`). This report covers the **3 non-WMMA** tests
(`amdgcn.bitcast.{320,384,448}bit.ll`); the 28 WMMA tests were sub-cause A, fixed in
commit `75b82ebe5521`.
**Failing pass:** `AMDGPU Rebuild SSA` (`MachineLaneSSAUpdater::buildRSForSuperUse`).
**Status:** root cause confirmed with runtime evidence (gdb + freeze-time interval
dump). Fix proposed below. **Not applied**, not yet corpus-tested.

---

## 1. Summary

A value lives in an **oversized `sgpr_512`** register class whose upper `16 − N`
dwords are **never defined** (padding). A whole-register use of that value
(`%120 = COPY %40`) crosses a CFG join. When RebuildSSA recomputes `%40`'s
LiveInterval, `LiveIntervalCalc` fabricates a subrange for the never-defined padding
lanes with a **PHI-def VNInfo over `undef` (`@x`) inputs** — a synthetic value with
no real definition, created only to make the whole-register use well-formed.

`buildRSForSuperUse` then reconstructs the use as a REG_SEQUENCE. Its `AddOldGroup`
classifier treats **any non-null reaching VNInfo** as a live value to be sourced
from `OrigVReg` and patched later. The fabricated PHI-def is non-null, so the padding
lanes are emitted as a live placeholder `%40.sub10_..._sub15` that (a) no real def
ever patches → "Reading virtual register without a def", and (b) uses an unaligned
subreg index illegal for the SGPR class → "Invalid subregister index".

**Fix:** treat a reaching value that is a **PHI-def with no real (non-PHI,
non-undef) definition backing it** as **undef** in `AddOldGroup`, so the padding
lanes are sourced with `RegState::Undef` and split through the covering-subreg path.

---

## 2. Affected tests and shared pattern

| test | value | defined dwords | sgpr_512 padding | failing operand |
|---|---|---:|---|---|
| `amdgcn.bitcast.320bit.ll` | v10 | sub0–sub9 | sub10–sub15 | `%40.sub10_sub11_sub12_sub13_sub14_sub15` |
| `amdgcn.bitcast.384bit.ll` | v12 | sub0–sub11 | sub12–sub15 | `%44.sub12_sub13_sub14_sub15` |
| `amdgcn.bitcast.448bit.ll` | v14 | sub0–sub13 | sub14–sub15 | `%31.sub14_sub15` |

All: `-mtriple=amdgcn -mcpu=tahiti`, function `bitcast_v{N}...`, whole-register
`COPY` of an oversized `sgpr_512` reaching across a join.

---

## 3. Input MIR (320bit, before RebuildSSA)

```
bb.0:
  undef %40.sub9:sgpr_512 = COPY $sgpr25     ; only sub0..sub9 defined (10 dwords)
  ...
  %40.sub0:sgpr_512 = COPY $sgpr16
  S_CMP_LG_U32 ... ; S_CBRANCH_SCC1 %bb.5
bb.3:
  %120:vreg_512 = COPY %40, implicit $exec    ; whole-register (16-dword) use of %40
```

No PHIs, no REG_SEQUENCE in the input — both are created by RebuildSSA. `%40` is
`sgpr_512` (16 dwords) but sub10–sub15 are never written.

---

## 4. Runtime evidence (removed debug prints + gdb)

### 4.1 Pre-rebuild `%40` interval has NO padding subrange
LiveIntervals dump before RebuildSSA — `%40` subranges are only:
```
L0000000000000003 … L00000000000C0000   (sub0 … sub9)
```
No `L…FFF00000`. So the padding subrange is **not** original.

### 4.2 The super-use build reads the full register
`buildRSForSuperUse` for the `COPY %40`:
```
[DBG-B] buildRSForSuperUse: OldVR=%40 MO.subreg=0 UseMask=00000000FFFFFFFF
        OldVR fullmask=00000000FFFFFFFF in %120:vreg_512 = COPY %40:sgpr_512
```
`MO.subreg=0` (whole register) → `UseMask = getMaxLaneMaskForVReg(%40) = 0xFFFFFFFF`
(all 16 dwords) → `LanesFromOld = 0xFFFFFFFC` (sub1–sub15, includes padding).

### 4.3 The frozen oracle already contains a fabricated padding subrange
Freeze-time dump of `%40` at session start:
```
[DBG-B] FREEZE %40 : %40 [...] 10@288B-phi
   L00000000FFF00000 [288B,416r:2) 0@x 1@x 2@288B-phi
   L0000000000000003 [...] 1@288B-phi
   ... (sub1..sub9 subranges, each with a real def + a join PHI-def)
```
The padding subrange `L00000000FFF00000` exists with values `0@x 1@x` (`@x` = no def
slot = undef) merged by `2@288B-phi` (a PHI-def at the bb.0→bb.3 join `288B`). This
subrange was fabricated by `createAndComputeVirtRegInterval(%40)` during repair,
because the whole-register `COPY %40` makes the padding lanes live-in to bb.3 with no
def, so LI calc synthesizes an undef+PHI subrange to keep the use well-formed.

### 4.4 The classifier picks the wrong branch
```
[DBG-B] collectReachingVNIs LanesFromOld=00000000FFFFFFFC Covered=00000000FFFFFFFC
        NoSub=0000000000000000 (frozen hasSubRanges=1)
[DBG-B] AddOldGroup piece=00000000FFF00000 V=0x... PHIdef -> LIVE(placeholder)
```
Because the frozen interval **has** a padding subrange, `collectReachingVNIs` returns
a non-null (PHI-def) VNI for `0xFFF00000`; `Covered` fully covers `LanesFromOld`, so
the `NoSub` undef fallback (line 837) never fires. `AddOldGroup` sees a non-null
PHI-def → `renamedForReachingVNI` returns null for a PHI-def (correct) → falls to the
**`Live` (placeholder)** branch → emits `%40.sub10_..._sub15` non-undef, expecting a
later patch that never comes (no real def of those lanes exists).

### 4.5 Why the defined lanes are fine
sub1–sub9 pieces are ALSO `PHIdef -> LIVE(placeholder)`, but each has a **real COPY
def** behind its join PHI, so a later `repairSSAForNewDef(sub_i)` patches its
placeholder to the renamed vreg (`%147`, `%149`, …). The padding PHI-def has **only
`@x` undef inputs** — no real def — so nothing patches it. `%40` has real defs only
for sub0–sub9 (confirmed: `MRI` def operands are exactly `%40.sub0..sub9`).

---

## 5. Root cause (one line)

`AddOldGroup` treats every non-null reaching VNInfo as a real, patch-later value, but
a **fabricated PHI-def over undefined padding lanes** is not a real value — it has no
backing definition, so it must be sourced as `undef`, not as a live `OrigVReg`
placeholder.

---

## 6. Proposed fix

In `AddOldGroup` (`MachineLaneSSAUpdater.cpp:792-802`), classify a reaching value as
**undef** when it is a PHI-def that is **not backed by any real (non-PHI) definition**
of those lanes. The cleanest predicate: a PHI-def VNInfo whose lanes have no real
establishing def in the frozen interval is undef. Two implementation options:

### Option 1 (targeted, recommended): treat un-renamable PHI-def reaching values as undef
A real merge PHI is only meaningful to the reconstruction if at least one of its
inputs is (or will be) a renamed real def. For the padding case every input is `@x`
(undef). Detect this: a PHI-def VNInfo none of whose predecessor-edge reaching values
resolve to a real def ⇒ undef.

```diff
--- a/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp
+++ b/llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp
@@ auto AddOldGroup = [&](LaneBitmask PieceLanes, VNInfo *V) {
     Register SrcReg = OldVR;
     LaneBitmask SrcBase = LaneBitmask::getNone();
     bool Undef = false, Live = false;
-    if (!V)
+    if (!V || isUndefBackedPHIDef(V, PieceLanes))
       Undef = true;
     else if (const RenamedDef *RD = renamedForReachingVNI(V)) {
       SrcReg = RD->VReg;
       SrcBase = RD->OrigLanes;
     } else
       Live = true;
```

where `isUndefBackedPHIDef(V, Lanes)` returns true when `V->isPHIDef()` and, walking
the frozen subrange for `Lanes`, every value reaching the PHI's predecessors is a
`@x` undef VNInfo (no real def). This preserves the working defined-lane behavior
(their PHIs have real-def inputs) while routing the fabricated padding PHI to undef.

### Option 2 (simpler, robust): compute the "has a real def" lane set once
Before decomposing, compute `DefinedLanes` = union of lane masks of `%40`'s real
(non-PHI, non-`@x`) defs from the frozen interval / `MRI.def_operands`. Then treat
`LanesFromOld & ~DefinedLanes` as undef explicitly (add to the `NoSub` set), so any
lane with no real def anywhere is sourced undef regardless of fabricated subranges:

```diff
@@ collectReachingVNIs(*FrozenOrigLI, LanesFromOld, QueryIdx, OldPieces);
     LaneBitmask Covered = LaneBitmask::getNone();
     for (auto &[L, V] : OldPieces)
       Covered |= L;
-    if (LaneBitmask NoSub = LanesFromOld & ~Covered; NoSub.any())
-      OldPieces.push_back({NoSub, nullptr});
+    // Lanes with no real (non-PHI, non-undef) def of OrigVReg anywhere are undef,
+    // even if LiveIntervalCalc fabricated a PHI-def subrange for them to make a
+    // whole-register use of an oversized class well-formed (padding lanes).
+    LaneBitmask DefinedLanes = realDefLaneMask(OrigVReg);   // union of real defs
+    LaneBitmask NoReal = LanesFromOld & ~DefinedLanes;
+    // Drop fabricated-live pieces over never-defined lanes; re-add them as undef.
+    for (auto &P : OldPieces)
+      if ((P.first & NoReal).any())
+        P.second = nullptr;          // force undef for the never-defined part
+    if (LaneBitmask NoSub = LanesFromOld & ~Covered; NoSub.any())
+      OldPieces.push_back({NoSub, nullptr});
```

(Exact form to be finalized; `realDefLaneMask` = OR of `operandLaneMask` over
`MRI.def_operands(OrigVReg)` excluding undef subreg defs. Option 2 is more robust to
other fabricated-subrange shapes; Option 1 is more surgical.)

### Illegal subreg index (second error) falls out
Once the padding lanes are `Undef`, the covering-subreg path
(`getCoveringSubRegsForLaneMask(..., getRegClass(OldVR))`, line 825) emits only
class-legal aligned subregs, and an undef source needs no reaching def — both verifier
errors clear. Recommend additionally validating at line 822 that
`getSubRegIndexForLaneMask(PieceLanes)` is legal **for `getRegClass(OldVR)`** (not
just present in TRI's global table) before using it directly, so an illegal unaligned
index can never be emitted even for a live piece.

---

## 7. Why this is correct
- The padding lanes are semantically **undef** (never written; the source language
  never defines them — v10 in an sgpr_512). Sourcing them `undef` matches their true
  value and is what Greedy/normal lowering does for such reads.
- Defined lanes are untouched: their reaching PHIs have real-def inputs, so
  `isUndefBackedPHIDef` is false (Option 1) / they are in `DefinedLanes` (Option 2).
- No new live ranges are created for undef sources, so pressure accounting is
  unaffected.

### Edge cases
- **Partial-def chains (RMW):** real defs back the PHIs → not misclassified.
- **Genuinely dead lane at a point but defined elsewhere:** handled by the existing
  per-use-point `collectReachingVNIs` (null VNI at that point) → already undef.
- **384/448bit:** same mechanism, smaller padding (4/2 dwords) → same fix.

---

## 8. Validation plan

```bash
ninja -C build/user-debug LLVMCodeGen llc
for t in amdgcn.bitcast.320bit amdgcn.bitcast.384bit amdgcn.bitcast.448bit; do
  build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
    -verify-machineinstrs llvm/test/CodeGen/AMDGPU/$t.ll -o /dev/null \
    && echo "$t OK" || echo "$t FAIL"
done
python3 scripts/ssara_corpus_harness.py run --jobs 96 --timeout 120 --out /tmp/out-padfix
python3 scripts/ssara_corpus_harness.py report --out /tmp/out-padfix
```
Expect: CRASH −3. Watch the `Invalid subregister index` (§4.6, 17) and
`Found PHI with NoPHIs` (§4.7, 4) buckets — these tests also emit those secondary
errors, so the fix should reduce them too; confirm no new regressions.

Note: these three tests currently also report `Found PHI instruction with NoPHIs
property set` on the merge PHIs RebuildSSA inserts. Verify the `NoPHIs` reset in
`AMDGPURebuildSSA.cpp` covers them once the REG_SEQUENCE verifies; if not, that is a
small follow-up (conditional `NoPHIs` reset, as the spiller already does).

---

## 9. Risk
- **Blast radius:** one classifier branch in `AddOldGroup` (Option 1) or the
  `LanesFromOld` decomposition (Option 2). Only changes lanes that have **no real
  def** — today exactly the crashing padding lanes.
- **Interaction:** independent of sub-cause A (WMMA, committed) and of the
  spiller/RA work. Shared updater code, so it also hardens spiller reload repair for
  any oversized-class value.

---

## 10. Evidence commands (reproducible; debug prints since removed)
```bash
# pre-rebuild %40 has only sub0..sub9 subranges (no padding):
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-before=amdgpu-rebuild-ssa -debug-only=liveintervals \
  llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o /dev/null 2>&1 | grep -m1 "L00000000000C0000"

# only sub0..sub9 are ever defined:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-before=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o - 2>/dev/null \
  | grep -oE "%40\.sub[0-9]+" | sort -u

# the failing REG_SEQUENCE + both verifier errors:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o - 2>&1 \
  | grep -A2 -E "Reading virtual register|Invalid subregister index"
```
