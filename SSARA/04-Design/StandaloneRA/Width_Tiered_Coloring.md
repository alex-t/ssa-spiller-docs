# Width-Tiered Coloring: Hack-fast wide-first + hole-scan-or-spill for narrower

## Source Mapping
- **Component**: SSA Register Allocator — coloring phase (`color()` in
  [`AMDGPUSSARegisterAllocator.cpp`](https://github.com/alex-t/llvm-project/blob/ssara/llvm/lib/Target/AMDGPU/AMDGPUSSARegisterAllocator.cpp))
- Related: [[SSA_RA_Coloring]] (current width-descending design + §10 divergent-CF
  note), [[ACL_Pass_and_CallSite_Capacity]], [[Decisions#Store at Definition]].

## Status
🔬 **PROPOSED, evidence-backed (2026-07-18).** Motivated by the proven finding
that width-descending multi-pass coloring is not a valid single PEO and can fail
to color a chordal graph at RP ≤ limit (see [[project note: coloring feasibility
gap]] / `%1072` in `schedule-regpressure-limit.ll`). This design keeps Hack where
Hack applies and confines the NP-hard remainder to a bounded, spill-backed scan.

## The problem it solves

Hack CC'06 guarantees polynomial optimal coloring for an idealized machine
(unit-width, freely interchangeable registers, one file, no precoloring). AMDGPU
violates the assumptions: **aligned tuples** (a `vreg_128` needs 4 consecutive
aligned lanes), aliased/mixed classes (`av_*`), cross-file operands, and ACL
precoloring. The current width-descending multi-pass was an attempt to handle
tuples but it partitions the single dominance PEO into per-width sub-walks —
that partition is **precoloring extension**, NP-complete on chordal graphs, and
empirically fails at RP ≤ limit. So "point-pressure ≤ k ⟹ colorable" (the
spiller's feasibility contract) is unsound on this HW.

## Tiering axis: (POOL, width), not RC, not raw width (finalized 2026-07-19)

A tier is a **(register pool, width)** pair, NOT a register class. AMDGPU has
dozens of RCs of the same width sharing the same physical registers (VReg_64,
av_64, AReg_64, …); tiering per-RC would mean ~dozens of near-duplicate Hack
passes. Tier by the underlying POOL instead:
- **SGPR pool** — always separate.
- **Vector pool** — TARGET-CONDITIONAL:
  - SPLIT target (pre-gfx90a): VGPR file and AGPR file are physically separate →
    TWO pools (VGPR order, AGPR order).
  - UNIFIED target (gfx90a/gfx942/gfx1250): VGPR+AGPR are ONE physical file → ONE
    unified vector order enumerating aligned tuples across BOTH v and a regs.

Discipline (the reason for this shape — auditable Hack-compliance): within one
pass ALL values draw from THE SAME virgin order; a value's RC only MASKS which
entries it may take (RC->contains), it never switches pools. So:
- av_64 on a unified target → draws from the unified vector order (v and a
  tuples) naturally — NO "fall from VGPR to AGPR" (that ad-hoc mixing was
  rejected as a bug source).
- VReg_64 → same unified order, RC-filtered to v-tuples.
- AReg_64 → same order, RC-filtered to a-tuples.
Per width, #orders = SGPR + (unified ? 1 unified-vector : VGPR + AGPR). Small.

## The scheme

Color **widest tier first, narrower tiers into what the wider tiers left free.**
Illustrated with widths 128/64/32 (within one pool):

1. **128-bit tier — pure Hack.** The 128-bit values among themselves form a
   chordal interference graph; walk in dominance order (a valid PEO); greedy over
   4-aligned slots is optimal. No precoloring constrains this tier → fast, always
   succeeds at its own ω. Allocation order = vector of 4-aligned physreg tuples.
2. **64-bit tier — Hack-fast IF a virgin pool exists.** Build the allocation
   order from 2-aligned pairs that **no 128-bit value occupies anywhere in the
   function** ("virgin along the whole function"). A 64-bit value placed in a
   virgin pair cannot interfere with any 128-bit value, so this sub-walk stays
   chordal/dominance-order/Hack-fast. If the virgin pool is exhausted → step to
   the bounded remainder (below).
3. **32-bit tier — same idea** against pairs+singles left virgin by 128 and 64.

## The remainder is NOT NP-hard graph coloring — it is hole-scan-or-spill

When a tier's virgin pool is exhausted, we do **not** solve precoloring
extension. Per value, in dominance order:

```
scan the register file for a hole of the right size + alignment,
    free across THIS value's whole live range
  found -> take it
  none  -> SPILL it (store-at-def, reload-at-use)
```

This is **linear-scan-with-spill-fallback** — polynomial, no search, no
backtracking. The NP-hard problem is *sidestepped*, not attacked: "give up and
spill" is the escape hatch.

### Why the spill is sound here (store-at-def ⇒ exec-safe)

For any **non-PHI** value V defined under exec E_def, every use is dominated by
the def and reads lanes ⊆ E_def (a use reading lanes V never defined is UB — that
is what PHIs are for). So **store-at-def captures a superset of every lane any
reload will need**, and a reload is exec-safe under any mask, anywhere. Thus
coloring MAY insert store-at-def + reload after CF lowering with no exec drift —
the original "coloring must never insert / must be guaranteed before it starts"
invariant existed only to avoid exec-unsafe *stores*, which store-at-def removes.
**Carve-out:** PHI / exec-mask values (a value crossing a reconvergence into a
wider mask) are NOT covered — see [[SSA_RA_Coloring#10]] / the divergent-CF task.
Those are not spilled by this path.

### Why this is not "just Greedy RA"

Greedy spills reactively across the WHOLE allocation, post-CF, and must find
exec-safe spill points (the hell SSARA avoids). This scheme does **Hack-optimal
on the hard part** (aligned wide tuples, placed first, provably) and confines the
hole-scan-or-spill to the **narrow leftovers**, where store-at-def guarantees
exec-safety. The dumb path only ever handles trivially-spillable values and never
disturbs the wide-tuple placement that was the actual difficulty.

## Evidence: the fast path dominates, spill is the tail

Measured across the AMDGPU LIT corpus (2402 tests, **41,298 function
measurements**; `[WIDTHSTAT]` probe = final-assignment proxy for virgin-pool
availability, a likely lower bound since a wide-first packer clusters tuples
tighter):

| tier | fully virgin (100%) | median virgin | <20% virgin (remainder likely bites) |
|---|---|---|---|
| 64-pair after 128 | **63%** of funcs | **100%** | 18% |
| 32-single after 128+64 | **51%** of funcs | **100%** | 16% |

So for ~63% of functions the 64-bit tier never leaves the Hack-fast path, median
virgin pool is the whole file, and the bounded hole-scan-or-spill remainder is a
~16–18% tail — small and controllable, exactly where the `%1072`-class failures
live. (`load_fma_store`, our hardest coloring failure: 28/30 virgin pairs,
55/61 virgin singles — even tuple-heavy kernels leave the file mostly virgin.)

## Complexity

- Wide tier: O(V·file) greedy over aligned slots — Hack, optimal.
- Virgin-pool sub-passes: O(V·file), chordal/dominance — Hack-fast.
- Remainder: per value O(file · range) hole scan, else spill — polynomial, no
  search. Whole allocator stays polynomial; NP-hardness never entered.

## Open items before implementation
- Cross-file / `av_*` coupling: the per-file decoupling assumes SGPR/VGPR
  colorings are independent; instructions with mixed-type operands and `av_*`
  classes couple them. Confirm the tiers remain sound (or scope to pure-VGPR /
  pure-SGPR first). (User-raised; not yet proven.)
- ACL interaction: ACL precolors around-call-livers; ensure ACL and ordinary
  draw from genuinely disjoint pools so the two are independent chordal problems
  (else we manufacture precoloring-extension ourselves — user-raised).
- Reload scratch: the narrow-value spill reload needs a register; bounded to the
  narrow tier, ties to the getTmpRegister / reserve work.
- Validate on the 27-cluster: does hole-scan-or-spill resolve them with the fast
  tiers intact, no corpus regression vs 44?
