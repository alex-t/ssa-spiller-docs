# Permutation Scratch Reserve

How SSARA guarantees the scratch register that `resolvePermutation` needs to
break an SSA-destruction copy cycle, at minimal (usually zero) register cost, and
without the crude flat 10% spiller margin it replaces.

This is the design for the `resolvePermutation` "no free scratch register"
asserts (AGPR and SGPR variants) and is the principled replacement for
[[Decisions#Flat spiller margin]] / the `VGPRLimit -= VGPRLimit/10` reserve.

---

## Problem

At SSA destruction, PHIs lower to parallel edge copies. A set of parallel copies
whose sources and destinations form a permutation contains **cycles**
(`a<-b, b<-a`). `resolvePermutation` (AMDGPUSSARegisterAllocator.cpp) breaks each
cycle either **in place** (a swap primitive) or with **one scratch register**
(save a cycle member, walk the cycle with plain copies, restore from scratch).

The scratch, when required, must be a register **free at the cycle's insertion
point**. On a function at the edge of its register budget there may be none —
`resolvePermutation` then hits:

```
assert(ScratchFits && "AGPR permutation cycle with no free scratch register");
assert((!UseScratch || ScratchFits) &&
       "SGPR permutation cycle with live SCC and no free scratch register");
```

The old mitigation was a blanket `-= budget/10` margin (see
[[Decisions#Flat spiller margin]]): wasteful (reserves up to ~6 VGPRs when at most
one dword is ever needed) and still unsound (a 10% margin can be exhausted).

---

## Key facts

**A permutation cycle is always width-1 at scratch time.** `resolvePermutation`
decomposes every copy wider than one dword into per-dword copies *before* building
the dependence map (the `DwordCopies` pre-pass), so by the cycle phase every cycle
is a single-dword permutation. Verified empirically across the wide-tuple tests
(schedule-xdl, spill-vgpr, spill-vgpr-to-agpr, spill-classless, rewrite-mfma
gfx942, spill-agpr): every Phase-2 `CycleWidth == 1`. The `CycleWidth != 1`
scratch-super-reg path is dead in practice.

**One scratch suffices per insertion point.** The scratch is transient: saved at
the cycle start, dead after the cycle-end restore. Cycles are resolved
sequentially, so at most one scratch is live at any instant. All cycles on one
edge share it, and `resolvePermutation` is called once per `(Pred, MBB)` edge, so
"one scratch per call" == "one scratch per insertion point". (The former
`MaxIdx += CycleWidth` per-cycle bump that over-counted this was fixed
separately — see [[Decisions#Transient permutation scratch]].)

**Consequently the reserve is at most one 32-bit register, per file, only where a
cycle actually needs it** — never the whole-function 10%.

---

## Per-file design

The three register files differ in how a cycle can be broken, so the reserve is
per-file. **VGPR never needs a reserve; AGPR needs none either (handled at rescue
time); only SGPR-with-live-SCC can require one.**

### VGPR — no reserve, ever

`emitSwap` breaks a VGPR cycle in place with `V_SWAP_B32` (GFX9+) or a `V_XOR`
triplet — both scratch-free. The VGPR arm's `UseScratch` is opportunistic
(`!hasSwap() && ScratchOcc == CurrentOcc && ScratchFits`) and falls back to the
XOR triplet when a scratch does not fit. There is no VGPR assert; no reserve is
required.

### AGPR — no reserve; rescue declines instead

AGPR has no swap or XOR primitive, so an AGPR cycle *must* use a scratch. But an
AGPR permutation cycle only exists if a **PHI-participating value is AGPR-classed**,
and the only thing that makes a PHI value AGPR is the VGPR→AGPR rescue
(`widenToAVOnUnified`) — input MIR AGPR PHIs feeding MFMA are the other source.

**Chosen: rescue treats "would create an AGPR permutation cycle with no
affordable scratch" as a legality condition and declines the widening**, rather
than reserving an AGPR up front.

**Chosen over:** an up-front AGPR reserve in the spiller. **Reason:** pass order.
The spiller runs *before* rescue (`RebuildSSA → SSARegisterSpiller →
SSARegisterAllocator[rescue → classifyVRegs → color → resolvePermutation]`), so at
spiller time the rescue-introduced AGPRs do not exist yet and the spiller cannot
know whether to reserve. Rescue itself, however, has full knowledge at its own
decision point (it can consult the collected PHI-cycle set), so it is the correct
place to decide. Declining a widening only forgoes an optimization; it never
forces a spill.

This leaves the genuine over-subscription corner (a function that needs the full
AGPR file *and* has an AGPR cycle, e.g. schedule-xdl at `waves-per-eu=1,1` where
Greedy itself spills to memory) to the memory fallback below — the reserve cannot
help there because the function is not `Max-1`-spillable.

### SGPR — layered, reserve only as last resort

An SGPR cycle comes from an **input-MIR SGPR PHI** (rescue never touches SGPRs),
so it is knowable exactly in SSA, before rescue. SGPR has no swap; it uses an
`S_XOR` triplet — but `S_XOR` **writes SCC**. So:

1. **SCC dead at the cycle** → in-place `S_XOR` triplet. No scratch, no reserve.
   The common case.
2. **SCC live + a structurally-even register live at the cycle** → **SCC-preserve
   trick** (below): fold SCC into the even register's bit 0, run the triplet,
   restore. Three scalar instructions, **zero** register cost.
3. **SCC live + no even register available** → reserve **one** SGPR at the cycle
   point (phantom interval, below), or spill to memory.

Because SGPR pressure is rarely the binding constraint, layer 3 is cheap and rare;
layers 1–2 cover the overwhelming majority at zero register cost.

---

## SCC-preserve trick (SGPR layer 2)

Reuses the mechanism from frame-index lowering (SIRegisterInfo.cpp `NeedSaveSCC`
path). SCC is one bit; if a register `X` in scope is **provably even** (bit 0
known zero), bit 0 is free storage:

```
s_addc_u32   X, X, 0    ; carry-in (SCC) lands in bit0 (X even => bit0 was 0)
... S_XOR triplet, clobbering SCC freely ...
s_bitcmp1_b32 X, 0      ; regenerate SCC from bit0
s_bitset0_b32 X, 0      ; clear bit0 -> restore X to its even value
```

Sound only across the contiguous window (nothing reads `X` between save and
restore), and only if `X` is genuinely even.

**Evenness must be STRUCTURAL, not analytic.** MIR known-bits does not help at this
stage: `GISelValueTracking` + `SITargetLowering::computeKnownBitsForTargetInstr`
cover only `S_BFE_*` and a few intrinsics, and the generic engine reasons over
`G_*` opcodes that are gone after instruction selection. On SSARA's post-ISel
target opcodes it returns "nothing known". So we cannot *prove* an arbitrary cycle
value even, in SSA or SSA-out.

The tractable even register is one known even **by identity**:

- **Frame pointer** — ABI dword-aligned (AMDGPUUsage.rst), a reserved register
  (`SIMachineFunctionInfo::FrameOffsetReg`). Identifiable without analysis.
- Possibly other reserved aligned registers (scratch-wave-offset) by identity.

Caveat: FP is not always present (leaf / no-frame functions, `hasFP()` false), so
layer 2 fires only when such a register is live at the cycle; otherwise layer 3.

---

## SGPR layer 3 — phantom interval reserve

When a reserve is genuinely needed, model it as a **tight, width-1 phantom live
interval at the cycle's insertion point**, and let the spiller's normal
register-pressure walk free the slot. Do **not** lower the function-wide
`SGPRLimit`.

**Chosen over:** a global `SGPRLimit -= 1`. **Reason:** the reserve is local. The
spiller processes points in order, so injecting the phantom at the cycle point
only affects spill decisions at and after that point — the already-processed
prefix and every region without a cycle keep the full budget. The scratch is
guaranteed free exactly where `resolvePermutation` needs it, at no cost anywhere
else.

**Modeling discipline:** one phantom **per insertion point**, not per cycle (all
cycles on an edge share one scratch), kept tight to the point (else two points'
phantoms spuriously overlap and inflate the reserve past one).

If even layer 3 cannot fit (function needs the full file — not `Max-1`-spillable),
`resolvePermutation` must fall back to a **memory scratchpad** (store a cycle
member, shuffle, reload) rather than assert — matching what Greedy does when both
files are full.

---

## Feasibility of the "need scratch" predicate

Collected once, cheaply, from the PHI-cycle set built while still in SSA (see
[[PHI_Coalescer]] for the cycle machinery):

```
needSGPRScratch(edge) = hasSGPRPermutationCycle(edge)
                     && SCCLiveAt(edge)                 // LIS / gated dom-order SCC scan
                     && !structurallyEvenRegLiveAt(edge) // FP etc. -> layer 2 instead
```

- `hasSGPRPermutationCycle`, `SCCLiveAt`, and even-reg identity are all knowable in
  SSA before rescue — no dependence on the (later) rescue pass or on MIR
  known-bits.
- The SCC-liveness scan runs only when an SGPR cycle exists (rare), so it is
  pay-for-what-you-use, not a blanket walk.

AGPR needs no predicate here — it is handled entirely at rescue time.

---

## Status

Design only; not yet implemented. Prerequisite landed: transient-scratch reuse
(one shared scratch per call, [[Decisions#Transient permutation scratch]]).
Related open item: the genuine-over-subscription memory-scratch fallback for the
`Max`-required corner (schedule-xdl class).
