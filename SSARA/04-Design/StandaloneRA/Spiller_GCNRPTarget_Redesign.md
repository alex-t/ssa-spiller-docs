# Spiller pressure gate: replace scalar VGPRLimit with GCNRPTarget

## Status
🔬 PROPOSED (2026-07-19), user-approved direction. Reviewable plan; not yet
implemented. Rollback point committed at f5a701bf8e86 (ACL-off 41 / ACL-on 40).

## Problem (recap, proven)
The SSA spiller is limit-driven off a single scalar `VGPRLimit` and caps it to
the VGPR_32-file count (`AMDGPUSSARegisterSpiller.cpp` ~:1262
`std::min(VGPRLimit, getAllocatableSet(VGPR_32RegClass).count())`). Correct for
pure-VGPR values, WRONG for `av_` (AGPR-or-VGPR) values on unified-file targets
(gfx90a/gfx942/gfx1250): their real budget is the combined VGPR+AGPR file. So the
spiller spills av_ tuples that would fit, while Greedy allocates the same kernel
with zero spills by using VGPR + a few AGPRs (proven: v256i8_liveout, 63 VGPRs,
no scratch, one tuple in `a[0:3]`). Coloring already can place av_ in AGPRs
(pickFreePhysReg uses getOrder(RC)); the spiller sheds them first.

## Solution
Replace the scalar gate with **GCNRPTarget** (GCNRegPressure.h/.cpp), which
already implements the correct TWO-ceiling model and serves BOTH target kinds
with one API:
- `MaxVGPRs = min(getAddressableNumArchVGPRs(), N)` — always (arch-VGPR file).
- `MaxUnifiedVGPRs = UnifiedRF ? min(getAddressableNumVGPRs(), N) : 0` — unified
  targets only. `UnifiedRF == hasGFX90AInsts()`.
- `isSaveBeneficial(Reg)` / `satisfied()` gate the unified clause behind
  `UnifiedRF`, so on split targets they reduce to the plain arch-VGPR check
  (NO behavior change, no split-target regression) and on unified targets add
  the combined ceiling.

## API used
- ctor `GCNRPTarget(unsigned Occupancy, const MachineFunction &MF, const
  GCNRegPressure &RP)` (or the (NumSGPRs,NumVGPRs,MF,RP) form).
- `setRP(const GCNRegPressure &)` — set current pressure at each walk point.
- `satisfied()` — replaces `CurRP <= RPLimit`.
- `isSaveBeneficial(Register)` — replaces the per-candidate "does spilling help".
- `saveReg(Reg, Mask, MRI)` — tentatively remove a (Reg,Mask) from the target's
  RP (verified: calls RP.inc(Reg, Mask→none) = decrement), so `satisfied()`
  re-tests correctly as candidates are selected.

## Wrinkle 1 — LivePhysRP folding
Today `CurRP = getVGPRNum(...) + LivePhysRP`, where LivePhysRP is *physical*-reg
pressure (block live-in physregs + phys defs), which `GCNRegPressure` (vreg-only)
does not track. GCNRPTarget::setRP takes a GCNRegPressure, so LivePhysRP would be
lost.
DECISION: fold LivePhysRP into the target by LOWERING the ceilings by LivePhysRP
for the current instruction — i.e. construct/adjust the target so
MaxVGPRs_eff = MaxVGPRs - LivePhysRP (and likewise the unified ceiling). Cleanest:
keep computing LivePhysRP as today, and pass an occupancy/limit to GCNRPTarget
that already subtracts it, OR after setRP, treat "satisfied" as
`Target.satisfied() && (archVGPRnum + LivePhysRP <= MaxVGPRs)`. Prefer the
former (adjust the target's N down by LivePhysRP per point) so all of
GCNRPTarget's internal two-ceiling logic stays authoritative. NOTE physregs are
arch-VGPRs (not av_), so they count against MaxVGPRs AND MaxUnifiedVGPRs — lower
both. (Confirm getAddressableNumVGPRs vs LivePhysRP units both = 32-bit regs.)

## Wrinkle 2 — deficit loop -> satisfied()-driven selection
`getVMPsToSpill` today: `SizeToSpill = CurRP - RPLimit`, pop candidates (sorted by
next-use, farthest last) until SizeToSpill units met, splitting a too-wide
candidate by sub-lane. Rework to:
  Target.setRP(CurPressure);                 // full GCNRegPressure at MI
  sort Active by next-use (unchanged);
  while (!Target.satisfied() && !Active.empty()):
     cand = pop_back (farthest next-use);
     if (!Target.isSaveBeneficial(cand)) continue;   // spilling it won't help
                                                      // (e.g. wrong file)
     ToSpill.insert(cand);
     Target.saveReg(cand.VReg, cand.Mask, MRI);       // update RP, re-test
  ToSpill.coalesceByVReg();                            // keep the coalesce fix
Sub-lane split: KEEP partial spilling (user decision 2026-07-19). When a
candidate is wider than needed, select sub-lane slices as today; coalesceByVReg()
then unifies same-reg lanes into ONE spill (the already-landed fix). So the loop
still supports sub-lane selection, and satisfied()/saveReg() drive termination
per selected slice. The isSaveBeneficial() check NATURALLY skips values in the
wrong file (its per-file logic), replacing the getLiveRegsForCurrentFile
filtering rationale.

## Keep unchanged
- SSASpillEmitter (store-at-def + reload + SSA repair) — untouched.
- Store-at-def, KillIdx derivation, ACL passes structure (they can adopt the
  target similarly later; first cut = the ordinary processFunction gate).
- coalesceByVReg() — retained; complements this.

## Subsumes / dissolves
- Backlog Q3 (flat 10% margin) — the target's occupancy-based limits replace it.
- The wrong VGPR-only cap at :1262.
- The partial-reload bug (C2) on vni8 — av_ tuples no longer spilled at all.

## Verification
1. vni8 v256i8_liveout: colors with NO spill (match Greedy 63), RP-verify clean.
2. Corpus ACL-off ≤ 41, ACL-on ≤ 40 (expect improvement as overspill drops).
3. Split-target sanity (a non-gfx90a test): behavior unchanged.

## Risk
Committed rollback exists. Main risk = LivePhysRP folding correctness and the
selection-loop rework; both covered above, validated by corpus.
