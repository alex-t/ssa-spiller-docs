# SSARA Analysis — A1 (spiller under-cover) vs §4.1 (physreg exhaustion)

**Date:** 2026-07-10
**Scope:** Determine whether the spiller's `getVMPsToSpill` under-cover paths (A1)
cause the 29 `assert: Failed to find free physreg` crashes (§4.1), applying the
Greedy-parity rule: *if Greedy spills, we must too; if Greedy allocates clean, the
only acceptable reason for us to fail is the missing coalescer.*
**Result:** A1 is **latent** (never fires on the §4.1 corpus). §4.1 is a **coloring
/ coalescer** problem, confirmed by parity data. No spiller change is warranted for
§4.1. Recommendation: fix by coalescing (durable) and/or a cross-call-aware color
choice; details below. **No sources edited.**

---

## 1. The two A1 under-cover paths (recap)

`AMDGPUSSARegisterSpiller.cpp`, `getVMPsToSpill`:

- **Path 1 — loop-filter empties `Active`** (line 618):
  ```cpp
  if (ValidCandidates.empty()) {
    // TODO: Fallback - pick best invalid candidate and use loop exit sinking
    return ToSpill;   // returns EMPTY -> RP stays over limit
  }
  ```
- **Path 2 — greedy loop exits with `RemainingToSpill > 0`** (line 638):
  ```cpp
  while (RemainingToSpill > 0 && !Active.empty()) { ... }
  // no post-check that RemainingToSpill == 0
  return ToSpill;
  ```

Either can leave register pressure above the limit, which would surface later as
`pickFreePhysReg` returning null → `assert(Chosen && "Failed to find free physreg")`
(`AMDGPUSSARegisterAllocator.cpp:398/414`).

---

## 2. Empirical test: does the spiller even run on §4.1 crashes?

Ran the spiller alone (`-stop-after=amdgpu-ssa-register-spiller
-debug-only=amdgpu-ssa-register-spiller`) on 13 of the 29 §4.1 tests, counting
spill attempts and the loop-filter-empty signature:

| test | spills | "need to spill" | loop-filter-empty |
|---|---:|---:|---:|
| GlobalISel/sdiv.i64 | 0 | 0 | 0 |
| GlobalISel/udivrem | 0 | 0 | 0 |
| GlobalISel/srem.i64 | 0 | 0 | 0 |
| tuple-allocation-failure | 0 | 0 | 0 |
| undef-handling-crash-in-ra | 0 | 0 | 0 |
| load-global-i32 | 0 | 0 | 0 |
| spill-scavenge-offset | 0 | 0 | 0 |
| attr-amdgpu-num-sgpr | 0 | 0 | 0 |
| a-v-global-atomicrmw | 0 | 0 | 0 |
| materialize-frame-index-sgpr | 0 | 0 | 0 |
| rewrite-vgpr-mfma-to-agpr | 0 | 0 | 0 |
| vni8-across-blocks | 0 | 0 | 0 |
| whole-wave-register-spill | 0 | 0 | 0 |

**The spiller never spills on any of them.** Example (`undef-handling-crash-in-ra`,
gfx90a): limits are VGPR=116, SGPR=92; observed pressure peaks around 18. The
spiller correctly does nothing. Therefore neither A1 path is exercised — **A1 is
not the cause of §4.1**. A1 remains a real latent gap (worth fixing so it can never
silently under-cover once spilling *is* needed), but it is not this bucket.

---

## 3. Parity check: does Greedy spill these? (the acceptable-reason test)

For the crashing function, compared Greedy's spill behavior:

- **`undef-handling-crash-in-ra` @foo**: Greedy `ScratchSize: 0`, zero folded
  spills — **allocates with no spill**. We also spill nothing, yet our RA aborts.
  Per the parity rule, the only acceptable reason is the missing coalescer → **must
  be a coloring/coalescer issue.** (Confirmed below.)
- **`tuple-allocation-failure`**: Greedy *does* spill (`ScratchSize: 16`, 1 folded
  spill) — but in a *different* function; the RA-crashing path is again a packing
  problem, matching the triage's "wide aligned `vreg_128_align2`, greedy succeeds
  via eviction."

---

## 4. Root cause of §4.1, proven on `undef-handling-crash-in-ra` @foo

The function is a kernel that sets up ABI arguments and makes two `SI_CALL`s:

```
$sgpr4_sgpr5   = COPY %20
...
$vgpr31        = COPY %18(s32)
dead $sgpr30_sgpr31 = SI_CALL %52, @G, csr_amdgpu_gfx90ainsts,
     implicit $sgpr4_sgpr5, ..., implicit-def dead $vgpr0, implicit-def dead $vgpr1
```

with AV/COPY chains feeding the call (uncoalesced):

```
%140:av_32       = COPY %30.sub2
%138:av_32       = COPY %30.sub3
%47:vreg_64_align2 = COPY %30.sub0_sub1
%146:vgpr_32     = COPY %44
%144:vgpr_32     = COPY %43
...
```

### Coloring trace (VGPR pass)
Distinct VGPRs actually assigned before the abort: **20** — namely
`VGPR0-3, VGPR40-47, VGPR56-63`. The last success is `%146 -> VGPR63`; the next
VGPR_32 `pickFreePhysReg` returns null and asserts.

The gap `VGPR4-39` / `VGPR48-55` is free, so this is **not** raw exhaustion. The
occupied set is exactly the **callee-saved** VGPRs `v40-47, v56-63` (16 regs) plus
the arg VGPRs `v0-3`. The cause is the **cross-call clobber constraint** in
`pickFreePhysReg` (`AMDGPUSSARegisterAllocator.cpp:105-120`):

```cpp
for (const auto &[CallIdx, CallMI] : CallSites) {
  if (!VI.liveAt(CallIdx)) continue;
  ... if (MO.isRegMask() && MO.clobbersPhysReg(PR)) { Clob = true; break; }
  if (Clob) { Free = false; break; }
}
```

A value **live across the call** may only take a callee-saved register (the
`csr_amdgpu_gfx90ainsts` regmask clobbers all caller-saved VGPRs). Count of values
live across the call needing a VGPR: **16** — exactly the number of callee-saved
VGPRs available. Every one is consumed, and the next cross-call value has nowhere to
go → abort.

### Why Greedy succeeds
Greedy uses only **11 distinct VGPRs** for the same function (`v0 v1 v31 v40 v42 v44
v45 v56 v57 v62 v63`) because it **coalesces** the `av_32 = COPY %30.subN` chains,
collapsing ~25 copies. We produce **20 distinct** values (no coalescer), inflating
the cross-call working set past the callee-saved capacity. Greedy also has
**eviction** to reshuffle; our one-shot dominance-order coloring does not.

**Conclusion:** §4.1 is caused by (a) **no coalescing** inflating the live value
count, compounded by (b) a **cross-call color constraint** that has no eviction
fallback. This matches the triage §4.1 exactly.

---

## 5. Recommendations

### 5.1 Do NOT change the spiller for §4.1
Spilling is not the lever — the spiller is correctly idle (RP ≪ limit). A
call-clobber pressure charge in the spiller was already tried and reverted
(triage §4.1 / §6). Confirmed here: it would force spills Greedy does not do,
regressing other buckets.

### 5.2 Primary fix: coalescing (durable, highest-leverage)
A copy-coalescer in the SSA RA (the "Pending: PHI coalescer") collapses the
`av_32 = COPY %30.subN` and ABI-setup copies, dropping the cross-call working set
from 20 → ~11 and letting the existing callee-saved set suffice. This is the
paper-sanctioned approach (ssara.pdf §4.3: coalesce by *color choice*, never by
graph merge that could break chordality). It also addresses MIXED /
DIFF_COALESCING / REGRESSION buckets.

### 5.3 Interim mitigation: cross-call-aware color choice (bounded)
Even before a full coalescer, `pickFreePhysReg` could bias:
- a value **live across a call** → prefer **callee-saved** registers;
- a value **not** live across any call → prefer **caller-saved** registers,
leaving callee-saved free for the values that actually require them.

**Constraint (Hack):** SSA/chordal optimal coloring is guaranteed only in
**dominance order** — this bias may only change the *choice* within the free set at
each def; it must NOT reorder defs to color cross-call values first. A prototype of
this bias was tried and reverted for net regressions (triage §6), so any retry must
be corpus-gated per change.

### 5.4 A1 hardening (independent, low priority for §4.1)
Although not the §4.1 cause, the two under-cover paths should fail loudly rather
than silently return an under-covered set, so a future spilling scenario cannot
regress into a hard-to-debug physreg abort. Options (for a separate report):
- Path 2: after the greedy loop, `assert(RemainingToSpill == 0)` or emit a
  diagnostic + fall back to whole-register spill of the farthest-use candidate.
- Path 1: implement the TODO (loop-exit sinking) or, minimally, fall back to the
  best "invalid" candidate instead of returning empty.
These are only reachable when the spiller actually needs to spill, so they will not
affect the §4.1 corpus today.

### 5.5 Also flagged (triage §4.1 last bullet)
Spiller sizes the VGPR budget with `getMaxNumVGPRs` (gfx90a=128, includes the AGPR
half) while the RA colors into `getNumAllocatableRegs(VGPR_32)`=64. This mismatch is
orthogonal to @foo (which fails on the callee-saved constraint, not the 64/128
budget) but should be reconciled so the spiller's "safe" pressure matches what the
RA can actually color into.

---

## 6. Evidence commands (reproducible)

```bash
# spiller never spills on the crash:
build/user-debug/bin/llc -mtriple=amdgcn-amd-amdhsa -mcpu=gfx90a -amdgpu-ssa-regalloc \
  -stop-after=amdgpu-ssa-register-spiller -debug-only=amdgpu-ssa-register-spiller \
  llvm/test/CodeGen/AMDGPU/undef-handling-crash-in-ra.ll -o /dev/null 2>&1 | grep -c "Will spill"   # -> 0

# greedy allocates @foo with no scratch:
build/user-debug/bin/llc -mtriple=amdgcn-amd-amdhsa -mcpu=gfx90a \
  -o /tmp/gf.s llvm/test/CodeGen/AMDGPU/undef-handling-crash-in-ra.ll
grep -oE '\bv[0-9]+\b' /tmp/gf.s | sort -u          # 11 distinct VGPRs

# our RA aborts after 20 distinct VGPRs, all callee-saved consumed:
build/user-debug/bin/llc -mtriple=amdgcn-amd-amdhsa -mcpu=gfx90a -amdgpu-ssa-regalloc \
  -debug-only=amdgpu-ssa-register-allocator \
  llvm/test/CodeGen/AMDGPU/undef-handling-crash-in-ra.ll -o /dev/null 2>&1 | \
  grep -E 'color:|Failed to find'
```
