# SSARA (AMDGPU SSA Register Allocator) — Crash Triage & State Report

**Date:** 2026-07-10  **Branch/worktree:** `ssara` (`/work/atimofee/sandbox/github/ssara`)
**Baseline commit for the numbers below:** `392ccad7379c` (tip after this session's 6 commits).

---

## 1. What this is

An SSA-based register allocator for the AMDGPU backend, offered as an alternative
to the greedy allocator behind the flag **`-amdgpu-ssa-regalloc`**. Pipeline
(replaces the SGPR/WWM/VGPR greedy chain in
`GCNPassConfig::addRegAssignAndRewriteOptimized`):

```
RebuildSSA  ->  SSA Spiller  ->  SSA Register Allocator  ->  SILowerSGPRSpills
```

- **RebuildSSA** (`AMDGPURebuildSSA.cpp`): re-derives SSA from post-PHIElimination
  MIR (splits multi-def vregs, inserts lane-aware PHIs) via the reaching-VNI
  `MachineLaneSSAUpdater` (`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp`).
- **SSA Spiller** (`AMDGPUSSARegisterSpiller.cpp`): Belady/next-use spilling to fit
  a per-class register budget; reloads are modeled as **redefs of OrigVReg**
  (Option-3), repaired inline by the same updater.
- **SSA RA** (`AMDGPUSSARegisterAllocator.cpp`): width-descending multi-pass PEO
  coloring over the dominator tree (greedy smallest-free), then SSA destruction
  (PHI lowering + permutation resolution) + operand rewrite.

Design docs: `ssa-spiller-docs/SSARA/04-Design/SSA_RA_Coloring.md`,
`.../Architecture.md`. Worklog: `.../08-Worklog/NOTES.md`, `BACKLOG.md`.

---

## 2. How to reproduce the corpus numbers

Harness: `scripts/ssara_corpus_harness.py` (reuses each AMDGPU test's own RUN line,
adds `-amdgpu-ssa-regalloc -verify-machineinstrs`, compares metrics vs greedy,
buckets the outcome). 3060 `.ll` tests under `llvm/test/CodeGen/AMDGPU`.

```bash
# build
ninja -C build/user-debug LLVMAMDGPUCodeGen llc
# run
python3 scripts/ssara_corpus_harness.py run --jobs 96 --timeout 120 --out /tmp/out
python3 scripts/ssara_corpus_harness.py report --out /tmp/out   # or read /tmp/out/report.md
```

Debug helpers: `scripts/gdbctl.sh` (persistent gdb sessions),
`scripts/mir2cfg.py` (render MIR CFG to PNG). Single-test triage:
`llc ... -amdgpu-ssa-regalloc -stop-before/-stop-after=amdgpu-rebuild-ssa|amdgpu-ssa-register-spiller|amdgpu-ssa-register-allocator`.

---

## 3. Current corpus health (baseline `392ccad7379c`, 3060 tests)

| Bucket | Count | Meaning |
|---|---:|---|
| OK_EQUAL | 725 | compiles, metrics == greedy |
| OK_BETTER | 344 | compiles, better than greedy |
| DIFF_COALESCING | 376 | compiles, differs by coalescing only |
| MIXED | 477 | compiles, mixed reg-count deltas |
| **CRASH** | **195** | assert/verifier/abort |
| REGRESSION_OCC_OR_SPILL | 31 | compiles but worse occupancy/scratch |
| TIMEOUT | 2 | > 120 s |
| SKIP_* / NO_METRICS | 650 | not applicable (run-pass, r600, O0, custom RA, etc.) |

Of the **195 crashes: ~170 are SelectionDAG, ~25 GlobalISel.** So compilation
succeeds on the large majority of the ~1920 in-scope tests; the work is (a) drive
CRASH → 0, (b) then close the occupancy/coalescing gaps.

---

## 4. Crash classes (prioritized) — the ask

Each class below lists count, a couple of repros, and our current understanding.
"Investigated" = root-caused with evidence this/last session; "Hypothesis" = best
guess, not yet proven; "Unknown" = not yet looked at.

### 4.1 (29) `assert: Failed to find free physreg` — **INVESTIGATED**
Repros: `GlobalISel/sdiv.i64.ll`, `srem.i64.ll`, `udiv.i64.ll`, `spill-scavenge-offset.ll`,
`tuple-allocation-failure.ll`, `undef-handling-crash-in-ra.ll` (now fixed — see §5).
- **This is a COLORING problem, not under-spilling.** Greedy compiles these with
  `ScratchSize:0` (no spill). A value **live across a call** may only occupy a
  **callee-saved** register (a call regmask clobbers all caller-saved). The SSA
  one-shot greedy-smallest-free coloring lets non-cross-call values grab
  callee-saved regs first, and cannot pack the cross-call values (especially wide
  **aligned** `vreg_128_align2`) where greedy succeeds via **eviction**.
- Sub-causes confirmed: (i) spurious wide width from ISel partial-undef defs +
  **uncoalesced COPY chains** inflating demand on the few aligned callee-saved
  tuples; (ii) the SSA RA has **no coalescing** ("Pending: PHI coalescer").
- **Theory constraint (Hack):** SSA/chordal coloring is only guaranteed in
  **dominance order** — a fix may bias the color *choice* (cross-call → callee-saved;
  others → caller-saved) but must NOT reorder to color cross-call first.
- We prototyped a spiller call-clobber pressure charge + an RA color-choice bias;
  both were corpus-tested and **reverted** (net regressions in other classes —
  see §6). The durable lever is **coalescing** + safe partial-def narrowing.
- Also open: **spiller and RA size the RP budget differently** — spiller uses
  `getMaxNumVGPRs` (gfx90a=128, incl. the AGPR half) while the RA colors into
  `RegClassInfo.getNumAllocatableRegs(VGPR_32)`=64. Reconcile.

### 4.2 (28) `MachineVerifier: Reading virtual register without a def` — HYPOTHESIS
Repros: `GlobalISel/llvm.amdgcn.wmma_{32,64}.ll`, `wmma-gfx12-*`.
- SSA reconstruction leaves a use with no reaching def on some path. Heavily WMMA
  (wide matrix ops) — likely a lane-aware repair gap for very wide / structured
  defs. (Same *symptom family* we fixed for loop-PHI self-refs and RMW chains, but
  these specific WMMA cases are unverified.)

### 4.3 (25) `MachineVerifier: Operand has incorrect register class` — HYPOTHESIS
Repros: `flat-atomicrmw-f{sub,max,min,add}.ll`, `GlobalISel/llvm.amdgcn.mov.dpp.ll`.
- Coloring/operand-rewrite assigns a physreg (or subreg) whose class doesn't match
  the operand's required class. Concentrated in atomic-rmw + dpp. Unverified.

### 4.4 (18) `assert: Tied use must be colored already` — HYPOTHESIS
Repros: `dpp_combine.ll`, `dpp64_combine.ll`, `chain-hi-to-lo.ll`.
- Coloring processes a tied def before its tied use is colored (ordering / the
  tied-operand handling in `color()`). Likely a self-contained fix.

### 4.5 (18) `assert: NewDefMI should have a def operand for OrigVReg` — HYPOTHESIS
Repros: `inline-asm.ll`, `InlineAsmCrash.ll`, `shufflevector.v3{f32,i32}.v2*.ll`.
- RebuildSSA driver assumes a re-def instruction has an explicit def operand for
  OrigVReg; inline-asm (variadic operands) and shufflevector partial defs break it.

### 4.6 (17) `MachineVerifier: Invalid subregister index for virtual register` — PARTIAL
Repros: `insert_vector_elt.ll`, `scc-clobbered-sgpr-to-vmem-spill.ll`,
`sgpr-spill-incorrect-fi-bookkeeping-bug.ll`, `identical-subrange-spill-infloop.ll`.
- Subregister-index computation in reconstruction / REG_SEQUENCE building produces
  an illegal index (or one that violates an align2 class). NOTE: our reverted
  partial-def-narrowing prototype *inflated* this class (+10) — narrowing wide
  partial defs is subreg/align2-fragile; whoever revisits it must rebase lanes to
  legal, aligned subregs.

### 4.7 Smaller classes
- (9) `Found PHI instruction after non-PHI` — `amdgcn.bitcast.{640..960}bit.ll` (PHI placement ordering in very wide bitcasts).
- (6) `Register class not set, wrong accessor` — GlobalISel image/shuffle.
- (6) `VOP* violates constant bus restriction` — `fneg-combines.new.ll`, scan atomics.
- (6) `Invalid Object Idx!` — spill frame-index bookkeeping (`branch-relax-spill.ll`, extload/loads).
- (6) `Remaining virtual register` — GWS intrinsics (`llvm.amdgcn.ds.gws.*`).
- (5) `Multiple virtual register defs in SSA form` — `spill-vgpr.ll`, `spill-agpr.ll`, a-v atomic cmpxchg.
- (4) `Found PHI with NoPHIs property set` — `amdgcn.bitcast.{320,384,448}bit.ll`, `issue98474-*` (down from 43→9→4 over prior sessions).
- (3) `v_div_scale require src0=src1|src2`; (3) `Too many positional arguments` (test-cmdline, not RA); plus ~10 singletons (see `/tmp/out/report.md`).

Full per-test lists are in the harness output (`results.jsonl`, filter `bucket==CRASH`).

---

## 5. Fixed this session (committed + pushed) — for context, not re-work

| Commit | Fix |
|---|---|
| `fad0fc8a00d7` | Loop-carried PHI self-reference: `rewriteDominatedUses` skipped a PHI's own back-edge operand (`UseMI==DefMI` guard) → use with no reaching def. |
| `90a204f519fb` | Partial reload preserved un-spilled lanes: dropped unconditional `RegState::Undef` on subreg reload defs; spiller re-applies it only when the complement is dead. |
| `316d0be77eea` | `CallSites` clobber-site predicate `!isReserved` → `isAllocatable` (stop recording implicit-def scc/vcc ALU ops). |
| `c8c11c10fb03` | RebuildSSA: RMW subreg re-def rename ordering generalized single-block → per-block. |
| `392ccad7379c` | Undef PHI operands sourced as `undef` + lowered to `IMPLICIT_DEF`. |
| `23a326f5ab01` | Test CHECK refresh (`lowerphi-critical-edge-no-split.ll`). |

Net effect this session: **CRASH 224 → 195** on the corpus (no new crashes; local
SSARA+SSASpiller lit suites green: 88 pass).

---

## 6. Known non-crash issues (secondary)

- **No coalescing in the SSA RA** — the biggest structural gap; drives the physreg
  class (§4.1) and much of MIXED/DIFF_COALESCING. ("Pending: PHI coalescer.")
- **Spiller vs RA RP-budget mismatch** — see §4.1 last bullet (gfx90a AGPR-half).
- **31 REGRESSION_OCC_OR_SPILL** — compiles but worse occupancy/scratch than greedy
  (e.g. `attr-amdgpu-num-vgpr.ll`, some `acc-ldst.ll` MFMA kernels). Mostly
  coalescing-quality; a few genuine spill-heuristic gaps.
- **Corpus is the real gate.** Local lit suites (88 tests) are far too narrow —
  this session, 3 changes passed local suites but the corpus caught a net +22
  regression. Please gate RA/spiller changes on a corpus run (ideally per change).
- **CAUTION for partial-def narrowing** (if anyone retries the §4.1 wide-undef
  angle): our attempt regressed `Invalid subregister index` (+10) and
  `even aligned vector regs` (+3). Leading hypothesis: a single-def partial Root's
  frozen interval exposes only the defined lane, so upper-lane REG_SEQUENCE
  rebasing picks illegal/misaligned subregs; and narrowing mutates copy-chain
  vregs whose snapshots go stale.

---

## 7. Suggested places to start (independent, low cross-talk)

Good self-contained first targets (likely localized, low risk of stepping on the
coalescing work):
- **§4.4 Tied use must be colored already (18)** — coloring order for tied operands.
- **§4.5 NewDefMI should have a def operand (18)** — RebuildSSA driver robustness for
  inline-asm / shufflevector partial defs.
- **§4.2 Reading vreg without a def — WMMA subset (28)** — lane-aware repair for wide
  WMMA defs (shares machinery with fixes we already landed).

Larger / coordinate-with-us:
- **Coalescing in the SSA RA** — unlocks §4.1 and improves MIXED/regressions. This is
  the highest-leverage item; worth pairing since it touches coloring + spiller RP.
- **§4.3 incorrect register class (25)** — operand-rewrite/coloring class handling.

Each crash reproduces standalone with:
```bash
build/user-debug/bin/llc <the-test's-RUN-flags> -amdgpu-ssa-regalloc \
    -verify-machineinstrs llvm/test/CodeGen/AMDGPU/<test>.ll -o /dev/null
```
(the exact per-test RUN flags are in the harness `results.jsonl` `ssara_argv` field).

---

## 8. Contacts / artifacts
- Corpus JSON + report: `/tmp/ssara-corpus-run5/` (report.md + results.jsonl).
- Backlog (HIGH PRIORITY items): `ssa-spiller-docs/SSARA/08-Worklog/BACKLOG.md`.
- Cross-session context: `ssa-spiller-docs/SHARED_CONTEXT.md`.
