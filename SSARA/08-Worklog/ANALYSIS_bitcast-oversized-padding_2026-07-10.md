# SSARA Analysis — §4.2 sub-cause B: bitcast oversized-class padding lanes (3 crashes)

**Date:** 2026-07-10
**Author:** investigation for review (no sources edited)
**Crash class:** §4.2 of `CRASH_TRIAGE_REPORT_2026-07-10.md` —
`MachineVerifier: Reading virtual register without a def` (this report covers the
**3 non-WMMA** tests; the 28 WMMA tests are sub-cause A, separate report
`FIX_REPORT_wmma-ec-tied-use_2026-07-10.md`).
**Failing pass:** `AMDGPU Rebuild SSA` (`MachineLaneSSAUpdater`).
**Status:** root cause identified with strong evidence; one internal detail (the
padding subrange's VNI state) still to be confirmed at code level before finalizing
the exact patch. Fix direction proposed. **No sources edited.**

---

## 1. Affected tests and the shared pattern

| test | value | dwords defined | sgpr_512 padding (undefined) | failing operand |
|---|---|---:|---|---|
| `amdgcn.bitcast.320bit.ll` | v10 | 10 (sub0–sub9) | sub10–sub15 (6) | `%40.sub10_sub11_sub12_sub13_sub14_sub15` |
| `amdgcn.bitcast.384bit.ll` | v12 | 12 (sub0–sub11) | sub12–sub15 (4) | `%44.sub12_sub13_sub14_sub15` |
| `amdgcn.bitcast.448bit.ll` | v14 | 14 (sub0–sub13) | sub14–sub15 (2) | `%31.sub14_sub15` |

All three: a value lives in an **oversized `sgpr_512`** register class whose upper
`16 − N` dwords are **never defined** (padding). RebuildSSA reconstructs a
whole-register super-use and sources those padding lanes wrongly.

---

## 2. Symptom (320bit)

`amdgcn.bitcast.320bit.ll` (tahiti), function `bitcast_v10f32_to_v5f64_scalar`,
after RebuildSSA, `-verify-machineinstrs` reports **two** errors on the same
operand:

```
*** Bad machine code: Reading virtual register without a def ***
- basic block: %bb.3
- instruction: %145:sgpr_512 = REG_SEQUENCE %144, %subreg.sub0, ..., %147, %subreg.sub1,
      %40.sub10_sub11_sub12_sub13_sub14_sub15:sgpr_512, %subreg.sub10_sub11_sub12_sub13_sub14_sub15
- operand 21:  %40.sub10_sub11_sub12_sub13_sub14_sub15:sgpr_512

*** Bad machine code: Invalid subregister index for virtual register ***
- operand 21:  %40.sub10_sub11_sub12_sub13_sub14_sub15:sgpr_512
```

(plus 10 `Found PHI instruction with NoPHIs property set` — a secondary property
bookkeeping issue on the newly inserted merge PHIs, see §6.)

---

## 3. Input MIR (before RebuildSSA)

```
bb.0:
  undef %40.sub9:sgpr_512 = COPY $sgpr25      ; only sub0..sub9 defined (10 dwords)
  %40.sub8:sgpr_512 = COPY $sgpr24
  ...
  %40.sub0:sgpr_512 = COPY $sgpr16
  ... S_CMP / S_CBRANCH ...
bb.3:
  %120:vreg_512 = COPY %40, implicit $exec    ; whole-register super-use of %40
```

`%40` is `sgpr_512` (16 dwords) but only **sub0–sub9** are ever defined. sub10–sub15
are padding that no instruction writes. There are **no** PHIs or REG_SEQUENCEs in the
input — both are created by RebuildSSA. The `%120 = COPY %40` in `bb.3` is a
whole-register (0xFFFFFFFF, 16-dword) read that crosses the bb.0→bb.3 join, so
RebuildSSA must merge `%40`'s per-lane defs with PHIs and rebuild the whole value
via a REG_SEQUENCE.

---

## 4. What RebuildSSA does (trace)

`%40` has per-dword subranges for the 10 defined dwords. RebuildSSA renames each
partial COPY def (sub0..sub9) to a fresh vreg, inserts a per-lane merge PHI at the
join (BB#2), and rewrites the `%120 = COPY %40` super-use into a REG_SEQUENCE.

`buildRSForSuperUse` (for `%120 = COPY %40`, `UseMask = 0xFFFFFFFF`) splits:
- `LanesFromNew = 0x3` (the lane currently being rewritten) → the PHI/renamed vreg;
- `LanesFromOld = 0xFFFFFFFC` (all other lanes) → sourced per their reaching VNI.

`collectReachingVNIs(FrozenOrigLI, 0xFFFFFFFC, …)` returns pieces for the defined
lanes (sub1..sub9), each later patched to its PHI (`%147`, `%149`, …). The **padding
lanes sub10–sub15** are emitted as a **single `%40.sub10_..._sub15` source that is
(a) never patched and (b) not marked `undef`** — confirmed from the final REG_SEQUENCE
the verifier sees (operand 21, no `undef` flag).

Evidence the padding lanes have no def and no PHI:
- PHIs are created only for lanes `0x3 … 0xC0000` (= sub0–sub9); **no** PHI for any
  lane ≥ `0x100000` (sub10+).
- The final `%145` has sub0–sub9 patched to `%144…%163`, while sub10–sub15 remains
  a raw `%40` read.

---

## 5. Root cause

`buildRSForSuperUse` assumes every lane in `LanesFromOld` is either:
1. covered by a subrange with a **live reaching VNI** → sourced from that def
   (patched later), or
2. **undef** (no reaching value) → sourced with `RegState::Undef`
   (`AddOldGroup`, `V == nullptr` path).

The **oversized-class padding lanes** break this dichotomy. sub10–sub15 are never
defined, yet they land in neither branch cleanly:

- If `%40`'s subrange structure reports the padding lanes under a subrange whose VNI
  is **non-null** at the query point (main-range spillover / a lumped subrange), then
  `collectReachingVNIs` returns `{sub10-15, VNI≠null}` → `AddOldGroup` takes the
  **Live** path → emits an `%40.sub10-15` placeholder expected to be patched by a
  later def's rewrite. **No def ever covers sub10-15**, so it is never patched →
  "Reading virtual register without a def."
- Additionally, the covering subreg index chosen for the padding remainder,
  `sub10_sub11_sub12_sub13_sub14_sub15`, is **not a class-legal index for the SGPR
  lattice** (SGPR tuples ≥64-bit exist only at aligned bases; a 6-dword tuple at
  offset 10 is not allocatable) → "Invalid subregister index for virtual register."

**In one line:** RebuildSSA reconstructs a whole-register use of a value held in an
oversized register class, but the class's never-defined padding lanes are sourced as
a live placeholder with an unaligned/illegal subreg index, instead of being dropped
as `undef`.

### Open detail to confirm before finalizing the patch
Whether the padding piece reaches `AddOldGroup` with a **non-null VNI** (stale
subrange, Live path) or a **null VNI** that is nonetheless emitted without the undef
flag. The two candidate spots:
- `collectReachingVNIs` (`MachineLaneSSAUpdater.cpp:569-575`): pushes
  `{Piece, S.getVNInfoBefore(Idx)}` for every subrange overlapping `Mask`, including
  a subrange that is dead (null) at `Idx` — but a **live** subrange covering padding
  lanes would send a non-null VNI down the Live path.
- The `NoSub` remainder fallback (`MachineLaneSSAUpdater.cpp:837-838`) only fires for
  lanes **not** covered by any subrange; if a subrange nominally covers the padding
  lanes, the fallback never runs, so the undef path is skipped.

This needs a focused code-level check of `%40`'s subrange lane masks (a temporary
`FrozenOrigLI->dump()` at freeze time, or stepping `collectReachingVNIs` for
`0xFFF00000`). It does not change the fix *direction* (below), only which line the
guard lands on.

---

## 6. Secondary: "Found PHI with NoPHIs property set" (same tests)
The 10 merge PHIs RebuildSSA inserts trip the verifier because the function still
carries the `NoPHIs` property. RebuildSSA sets `IsSSA`/resets `NoPHIs` at pass end
(`AMDGPURebuildSSA.cpp:217-221`) — verify that the reset actually happens before the
post-pass verifier for these functions, and/or that the spiller's conditional
`NoPHIs` reset (only when it inserts a PHI) has an analogue here. This is bookkeeping,
likely resolved once the REG_SEQUENCE error is fixed and the function verifies; note
it so it isn't mistaken for a separate crash class.

---

## 7. Proposed fix direction (to finalize after §5 confirmation)

Make padding / never-defined lanes in a whole-register reconstruction be sourced as
`undef`, and split any remainder that has no class-legal single subreg index into
covering (aligned) subregs:

1. **Treat lanes with no *live* reaching def as undef, not as a placeholder.** In
   `AddOldGroup`, the Live path should be taken only when `V` is non-null **and**
   the lane actually has an establishing def that will be renamed/patched. For a lane
   whose only "reaching" value is a dead/stale subrange VNI (no real def), use the
   undef path. Concretely: gate the Live vs undef decision on
   `V && !V->isUnused() && there-exists-a-def-covering-this-lane`, falling back to
   `RegState::Undef` otherwise.

2. **Never emit an illegal subreg index.** When the remainder mask has no single
   class-legal index (`getSubRegIndexForLaneMask` returns 0 *or* returns an index not
   valid for `getRegClass(OldVR)`), always route through
   `getCoveringSubRegsForLaneMask(..., MRI.getRegClass(OldVR))` so only aligned,
   class-legal subreg sources are produced. The current guard at line 822 trusts
   `getSubRegIndexForLaneMask(PieceLanes)` without checking it is valid **for the
   register class** — an index can exist in TRI's global table yet be illegal for
   `sgpr_512`'s allocatable lattice.

3. **Simplest robust variant:** when `LanesFromOld` includes lanes that the frozen
   interval has **no establishing (non-PHI, non-dead) def** for, add them to the
   `NoSub` undef set explicitly (compute `Defined = union of lanes with a real def`
   from `FrozenOrigLI`, and treat `LanesFromOld & ~Defined` as undef), rather than
   inferring undef only from "no subrange."

The `NoSub` undef fallback already exists (lines 837-838) and the covering-subreg
splitter already exists (`getCoveringSubRegsForLaneMask`); the fix is to make the
padding lanes actually reach them, and to validate subreg indices against the
register class.

I recommend confirming §5's open detail first (one `dump()` probe), then landing a
targeted change gated to the "no real def for these lanes" case, corpus-gated.

---

## 8. Why this is separate from sub-cause A
Sub-cause A (WMMA) is a **tied early-clobber use** whose reaching query hits the
instruction's own def (fix: query at base index). Sub-cause B is a **whole-register
super-use of an oversized class** whose padding lanes have no def (fix: source them
undef + legal covering subregs). Different instructions, different code paths, no
shared fix. They only share the verifier message.

---

## 9. Evidence commands (reproducible)

```bash
# oversized-class padding in the input (only sub0..sub9 of an sgpr_512 defined):
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-before=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o - \
  | grep -E "%40\.sub|COPY %40"

# padding sourced non-undef with illegal subreg after RebuildSSA:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-rebuild-ssa llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o - 2>&1 \
  | grep -A2 "Reading virtual register"

# PHIs only for defined lanes sub0..sub9, none for padding sub10..15:
build/user-debug/bin/llc -mtriple=amdgcn -mcpu=tahiti -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-rebuild-ssa -debug-only=machine-lane-ssa-updater \
  llvm/test/CodeGen/AMDGPU/amdgcn.bitcast.320bit.ll -o /dev/null 2>&1 \
  | grep -oE "createPHIInBlockReaching in BB#. OrigVReg=%40 Lane=[0-9A-F]+"

# all three cases share the oversized-padding shape:
for t in 320 384 448; do
  grep -A3 "Reading virtual register without a def" \
    /tmp/ssara-corpus-run5/stderr/amdgcn.bitcast.${t}bit.ll.ssara.err \
    | grep -oE "sub[0-9]+(_sub[0-9]+)*:sgpr_512" | tail -1
done
```
