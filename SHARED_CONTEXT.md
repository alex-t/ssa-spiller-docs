# Shared Context — SSA RA Project

Cross-worktree knowledge base. Updated after significant sessions.
Last updated: 2026-07-14

## 2026-07-14 — ssara synced to ff16 baseline (affinity + fold), PHI pass renamed, 3 commits pushed

**Spiller allocatable-budget cap COMMITTED fc16 (`fc1614731504`).** `AMDGPUSSARegisterSpiller`:
`VGPRLimit/SGPRLimit = min(getMaxNum*, TRI->getAllocatableSet(&VGPR_32/&SGPR_32RegClass).count())`
BEFORE the 10% margin. `getMaxNumVGPRs` = occupancy target over the whole vector budget (gfx90a =
VGPR+AGPR = 128) but the allocator colors into VGPR_32 only (64); the spiller over-budgeted ~2x,
under-spilled, `color()` aborted "Failed to find free physreg". Corpus CRASH -10, 0 new. (Reconciles
the long-open "spiller vs RA budget differ" item.)

**PHI pass renamed `AMDGPUPHICoalescer` → `AMDGPUSimplifyUndefPHI`** (file/class/symbols;
DEBUG_TYPE `amdgpu-simplify-undef-phi`; flags `-amdgpu-simplify-undef-phi[-flag|-fold]`; stats
`NumUndefFlagged`, `NumPHIsFolded`). Two rewrites: (a) flag fully-undef PHI operands undef; (b) fold a
single-real undef-PHI onto its operand when its def dominates the PHI (whole-reg only; MDT test;
declines loop-carried back-edge). **Kept STANDALONE (load-bearing):** it mutates undef flags →
invalidates LiveIntervals + AMDGPUNextUseAnalysis, which the pass manager recomputes for the spiller
(pass only preserves CFG/MDT). Folding it into the spiller would strand a STALE NUA (spiller acquires
`AMDGPUNextUseAnalysisWrapper` up front) — that is the concrete reason a pre-spiller pass boundary is
required, not overkill.

**ssara vs ssara-claude (both fc16) — the baseline gap.** `corpus-ff16` (47 crashes, /tmp/corpus-ff16)
was run on **ssara-claude**, which has three behavioral features ssara lacked: (1) spiller
reload-lane-narrowing — **POST-baseline, OUT OF SCOPE**; (2) φ-affinity coloring (promote patch 02);
(3) PHI fold (b). ssara alone = 50 crashes; +3 vs ff16 = `urem.ll`, `wave32.ll` ("Segment is not
entirely in range!"), `amdgcn.bitcast.576bit.ll` ("Failed to find free physreg"). Proven NOT the
rename via A/B: `urem.ll` asserts identically with the PHI pass on AND off (pass-independent). Fix =
port affinity(2) + restore fold(3).

**Result:** after the sync, corpus `uptodate` (jobs=32/timeout=180) = **CRASH 47, IDENTICAL set to
ff16, all buckets match** (the one REGRESSION delta `a-v-flat-atomicrmw` is ff16's flaky TIMEOUT(1)
resolving). Three commits pushed: `da78e671` (metric, stats-only), `3deb087e` (phi-affinity coloring),
`80fc7d8d` (AMDGPUSimplifyUndefPHI pass). Report: `SSARA/08-Worklog/corpuse/corpus-14-07-2026.md`.

### Reusable techniques (this session)
- **Non-interactive hunk-split for separate commits:** classify each `git diff` hunk by content
  marker, emit a subset patch, `git apply --cached` it (commit 1), then a whole-file `git add` stages
  the residual after commit 1 lands (commit 2). Verify with `git diff --cached`.
- **Upstream formatting checks:** local `git-clang-format` can be MORE LENIENT than CI — apply CI's
  proposed diff verbatim. A push rejected with "fetch first" after remote merged main → `git pull
  --rebase` then push (rebases your isolated commit on top).
- **Corpus harness:** jobs=32/timeout=180 avoids the tail-overload timeout→CRASH misclassification
  that jobs=64 produces (some tail tests ballooned to ~700s).

## 2026-07-11 (evening) — guard-test campaign COMPLETE (11 tests) + shell-guard finalized

**11 guard tests committed+pushed** in `llvm/test/CodeGen/AMDGPU/SSARA/`, each REVERT-PROVEN
(crash/incorrect-class when the fix is reverted in the ssara-guard sandbox, clean with it):
rebuildssa-bitcast-oversized-padding (36154bd), rebuildssa-wmma-early-clobber-tied-use (75b82e),
rebuildssa-newdef-among-all-operands (400c67), ra-undef-self-tied-def (030d4d),
rebuildssa-undef-phi-operand (392cc), ra-color-by-operand-flag (4cb21),
ra-dying-use-early-clobber (60727; test_load_mfma_store16), rebuildssa-rmw-subreg-reorder (c8c11;
subreg-coalescer-crash @foo), rebuildssa-loop-carried-phi-self-ref (fad0;
loop-live-out-copy-undef-subrange), spill-phi-def-insertion-point (the previously-UNCOMMITTED
spiller PHI-insert fix — now COMMITTED e138cc9 WITH its test), ra-swap-16bit-permutation (effb6;
v_swap_b16.ll @swap). Commits 50bef5c, 402d82a, 528cbc5, e138cc9, 938f117, 804652.

DEFERRED (precise reasons): #9 partial reload (90a2) is a MISCOMPILE fix, not a crash — reverting
it causes ZERO corpus crashes (partial reload marks un-spilled lanes undef -> wrong code, no
verifier abort); a guard needs a hand-crafted spill+partial-reload correctness CHECK, not an .ll
crash repro. 867d/b293c/c100e do NOT cleanly `git revert` (later commits rewrote the code); covered
by #1/#2/#3 machinery. 316d (CallSites isAllocatable) is perf-only.

### Repro-discovery technique (reusable, reliable)
Revert ONE fix in `ssara-guard` (`git reset --hard HEAD && git revert -n <c> && ninja -C build/guard
llc`), run the harness `--llc /work/atimofee/sandbox/github/ssara-guard/build/guard/bin/llc`, then
diff the CRASH set vs the fixed 103 baseline (`/tmp/corpus-postfix/results.jsonl`) -> the NEW crashes
are that fix's repros; extract the crashing function and verify crash-reverted/clean-fixed. This
found effb6 (v_swap_b16.ll) and c8c11 (subreg-coalescer-crash) where guessing failed. Single-function
extraction sometimes doesn't reproduce (needs the file's pressure) — always confirm.

### Prompt-free tooling (kernel 5.15 = no sandbox; hooks can't auto-approve)
Bare-tool PATH: `export PATH=/tmp/ssara-pin:$PATH` -> bare `llc`/`FileCheck`/`llvm-extract` = fixed
(pinned HEAD) binaries; symlinks `gllc`/`gextract` in /tmp/ssara-pin = the ssara-guard SANDBOX
(reverted) binaries. Cursor Auto-Run Mode = "Use Allowlist" with these first-token chips + BARE tool
invocation (allowlist matches FIRST TOKEN only; `$SG/llc`/`cd &&` never match). External-File
Protection turned OFF (writes to /tmp + ssara-guard are outside the ssara workspace). shell-guard hook
is DENY-ONLY (shlex/quote-aware) — hooks cannot auto-approve, only deny/ask.

## 2026-07-11 — shell approval hardening (stop the once-a-minute "Allow" prompts)

Root cause of the per-command approval pain during autonomous work: on this remote host
Cursor's execution-sandbox never engages (`sandbox:true` = 0 in the hook audit log
`.cursor/hooks/state/shell-guard.log`), so every non-allowlisted command prompts.
Fix (committed to the ssara worktree, `.cursor/hooks/shell-guard.sh`, an APPROVED safety change):
upgraded the audit-only `beforeShellExecution` hook into a DECISION hook that hard-DENYs
destructive carve-outs of otherwise-safe tools and otherwise ABSTAINS (never auto-allows).
Per-segment analysis (split on `| ; &` backtick/newline; peel env/sudo/xargs wrappers; strip
quotes/backslash/path to basename) so a flag on a piped command or a tool name as an argument
never misfires. Blocks: find `-delete/-exec/-fprint*`; every sed `-i` variant + sed `w`/`s///w`
writes; perl `-i`; awk `-i inplace`/`system(`/`print>file`; `tee FILE`; `dd of=`; `truncate FILE`;
`ex`/`ed`. This makes it SAFE to add to Cursor's UI Command Allowlist for auto-run:
`ninja cmake llc FileCheck llvm-extract git cp mkdir find sed perl awk python3` (user adds these
in Settings; hook is the safety net). Test the hook by reading payloads from a FILE — inlining
destructive strings makes the LIVE hook block your own test command.

## 2026-07-10 (evening) — padding fix committed; corpus 195→103; guard-test backlog + infra

**All prior 2026-07-09/10 crash-cluster work is now COMMITTED** (the risky RebuildSSA narrowing #7 was
dropped; safe set + self-tied/V_SWAP_B16/NewDefMI/WMMA-EC fixes landed: git series fad0fc8..75b82eb).

### New fix committed (36154bd): oversized-padding super-use (`MachineLaneSSAUpdater::buildRSForSuperUse`)
A value in an oversized register class (e.g. a 384/448-bit bitcast held in sgpr_512) makes
LiveIntervalCalc fabricate a subrange over never-defined PADDING lanes whose only values are undef (`@x`
== `VNInfo::isUnused()`, confirmed LiveInterval.cpp:1001) joined into a PHI-def. The reaching-VNI query
returned that PHI-def → padding lanes emitted as a live OrigVReg placeholder never patched → dangling
use + illegal subreg index. Fix: (a) restrict the query to lanes with a REAL establishing def
(`!isUnused() && !isPHIDef()`), routing padding to the undef NoSub piece; (b) gate the direct-subreg
fast path on `TRI.getSubClassWithSubReg(RC, Idx)`, else decompose via `getCoveringSubRegsForLaneMask`
(sgpr_512 has no single sub12_..._sub15 / sub14_sub15 index). Repro amdgcn.bitcast.{384,448}bit.ll.

### Corpus: CRASH 195 → 103 (`/tmp/corpus-postfix/`, 3060 tests, no new crash-class regressions)
Top remaining: (30) Failed to find free physreg [cross-call, needs coalescing]; (10) Operand incorrect
register class; (10) Found PHI after non-PHI [amdgcn.bitcast.320/512/640/704/1024bit]; (7) Invalid
Object Idx; (6) Register class not set [GISel]; (6) VOP const bus; (6) Remaining vreg [GWS]; (5)
Multiple vreg defs SSA; (4) v_div_scale; + singletons.

### Guard tests (dev-rule: each fix needs a guarding LIT test). 6 COMMITTED, all revert-PROVEN.
`llvm/test/CodeGen/AMDGPU/SSARA/`: rebuildssa-bitcast-oversized-padding.ll (36154bd),
rebuildssa-wmma-early-clobber-tied-use.ll (75b82e), rebuildssa-newdef-among-all-operands.ll (400c67),
ra-undef-self-tied-def.ll (030d4d), rebuildssa-undef-phi-operand.ll (392cc), ra-color-by-operand-flag.ll
(4cb21). Test commits 50bef5c + 402d82a.
DEFERRED (reasons in NOTES 2026-07-10 evening): V_SWAP_B16 effb63 (needs MIR — 16-bit PHI permutation
cycle), c8c11 RMW ordering (no repro found), fad0 loop-PHI (repro elusive), 90a2 partial reload (noisy
free-physreg signature), 867d/b293c/c100e (don't cleanly revert — code rewritten), 60727 dying-use.
316d CallSites isAllocatable = perf-only, no functional test.

### Reusable guard-test infra (on disk)
Isolated detached worktree `/work/atimofee/sandbox/github/ssara-guard` + minimal `build/guard`
(llc/FileCheck/llvm-extract only; ~10G), built path-independently by reusing the warm ccache via
`CCACHE_BASEDIR=/work/atimofee/sandbox/github CCACHE_NOHASHDIR=true` (this ccache REJECTS
CCACHE_HASHDIR=no/false). Pinned fixed binaries `/tmp/ssara-pin` (HEAD 36154bd). Scratch authoring
`/tmp/ssara-tests`. Revert-proof: in ssara-guard `git reset --hard HEAD && git revert -n <c> && ninja
-C build/guard llc`, run repro (~2min). Bulk repro discovery: revert several, run harness `--llc
ssara-guard/.../llc`, diff crash classes vs 103.

### UNCOMMITTED (user's — commit TOMORROW with a guard test): PHI-after-non-PHI spiller fix
`AMDGPUSSARegisterSpiller::spillAtDefinition` (~1441): when the spilled value's def is a PHI, store was
inserted at `std::next(PHI)` (between PHIs → verifier "Found PHI after non-PHI"). Fix:
`InsertAfter = DefMI->isPHI() ? DefMBB->getFirstNonPHI() : std::next(DefMI->getIterator())`. Diff saved
at `ssa-spiller-docs/SSARA/08-Worklog/UNCOMMITTED_phi-after-nonphi-spiller-fix_2026-07-10.patch`.
Guard-test candidate repro: amdgcn.bitcast.320bit.ll (currently in that class).

## 2026-07-09/10 (late) — crash-cluster fixes; corpus 224→195 (good) then +22 regression from 3 risky changes

**ALL WORK THIS SESSION IS UNCOMMITTED (working tree, `ssara`).** 7 files modified:
`MachineLaneSSAUpdater.cpp`, `AMDGPURebuildSSA.cpp`, `AMDGPUSSARegisterAllocator.{cpp,h}`,
`AMDGPUSSARegisterSpiller.cpp`, `SIInstrInfo.cpp`, test `SSARA/lowerphi-critical-edge-no-split.ll`.

### Corpus trajectory (harness `scripts/ssara_corpus_harness.py`, 3060 tests, gfx-per-test RUN lines)
- Committed baseline (2026-07-08 `b293c794`): CRASH **224**.
- **run1** (this session, GOOD changes only): CRASH **195** (−29). Changes: loop-PHI self-ref fix +
  partial-reload `undef` fix + `CallSites` isAllocatable precision + stale `v_swap` CHECK update.
- **run2** (added 3 RISKY changes): CRASH **217** (+22 vs run1 = NET REGRESSION). Deltas:
  `Invalid subregister index` 17→27 (+10), `even aligned vector regs` 0→3 (+3) [both from RebuildSSA
  narrowing], `SGPR permutation cycle scratch` 0→5, `Using undefined physreg` 1→5 [RA bias/spiller],
  `Failed to find free physreg` 29→**26** (−3, the intended win). `/tmp/ssara-corpus-run` (195) and
  `/tmp/ssara-corpus-run2` (217) hold the JSON.

### CORPUS-SAFE fixes (KEEP — net −29):
1. **Loop-carried PHI self-reference** (`MachineLaneSSAUpdater.cpp` `rewriteDominatedUses`): guard was
   `if (UseMI==DefMI) continue;` — this skipped a loop-header PHI's OWN back-edge operand (the PHI is
   both def of NewSSA and, via the self-edge, a use of OrigVReg), leaving `%X.subN` with no reaching def
   → "reading vreg without a def" at the interval recompute. Fix: `if (UseMI==DefMI && !DefMI->isPHI())`
   — let the PHI's incoming operands flow into `rewriteUseReaching` (reaching-VNI match rewrites the
   self-edge to the PHI result). Repro `loop-live-out-copy-undef-subrange.ll` (gfx906).
2. **Partial reload-as-redef must preserve un-spilled lanes** (`SIInstrInfo::loadRegFromStackSlot` +
   `AMDGPUSSARegisterSpiller::getOrCreateReloadInBlock`): the `SubRegIdx!=0` reload overload stamped
   `RegState::Undef` on the partial def (correct for a FRESH-vreg reload, WRONG for Option-3
   reload-as-redef of a live OrigVReg — it made LiveIntervals treat the reload as a fresh whole-reg def,
   killing the un-spilled lanes → reconstruction sourced them `undef` in the REG_SEQUENCE, dropping live
   data). Fix: drop the unconditional `Undef` in `loadRegFromStackSlot` (`SubRegIdx!=0`, spiller-only
   path — the only non-default caller); spiller re-applies `undef` ONLY when the complement is dead
   across the reload (`S.liveAt(RIdx.getRegSlot())`). Fixed 3 SSASpiller tests (multi-path-independent,
   use-before-spill, sgpr-wide).
3. **`CallSites` over-capture** (`AMDGPUSSARegisterAllocator.cpp`): the implicit-physdef clobber-site
   predicate used `!MRI->isReserved(reg)`, catching every `implicit-def $scc/$vcc` ALU op (S_CMP etc.).
   Not a correctness bug (`modifiesRegister` is exact so no false rejects) but bloats CallSites + slows
   pickFreePhysReg. Fix: `MRI->isAllocatable(reg)` (only regs a value could be colored onto matter).
4. Stale `v_swap_b32` CHECK in `lowerphi-critical-edge-no-split.ll` regenerated (coloring aligned the
   per-lane accumulator PHI results with the atomic result → no swap needed; verified correct vs greedy).

### RISKY fixes (REVERT or rework — run2 net +22):
5. **Spiller call-clobber pressure charge** (`AMDGPUSSARegisterSpiller.cpp` `processFunction` +
   `findRegMask`): at a call, charge `Shortfall = max(0, RPLimit − #callee-saved-allocatable)` against
   the live-after set so cross-call values spill to the callee-saved budget. Principle correct (only
   fires when cross-call > callee-saved, i.e. when greedy would also spill), but see regressions.
6. **RA call-clobber color-choice bias** (`AMDGPUSSARegisterAllocator.{cpp,h}` `pickFreePhysReg` +
   `CallerSavedReg` BitVector): non-cross-call values prefer caller-saved regs (leave callee-saved for
   cross-call). Dominance-order preserved (Hack-safe — biases CHOICE not ORDER; do NOT reorder to color
   cross-call first, that violates the PEO completeness proof).
7. **RebuildSSA single-partial-def narrowing** (`AMDGPURebuildSSA.cpp`): don't skip a `getNumValNums==1`
   vreg when its sole def is a PARTIAL (subreg) def — route through the existing Root-narrowing so a
   `undef %x.sub0:vreg_128` (only sub0 live, used whole via COPY) narrows to the defined lanes' class.
   Fixed `undef-handling-crash-in-ra.ll` (spill-free, matches greedy) BUT is the main regressor
   (+10 Invalid subregister index, +3 even-aligned) — narrowing produces illegal subreg indices /
   violates align2. **Likely revert this one first and re-measure.**
   **LEADING HYPOTHESIS for the #7 regression (user, 2026-07-10):** rewriting a single-def partial Root
   loses/mis-uses the pre-repair frozen snapshot. Two candidate mechanisms: (a) single-def vs multi-def
   freeze content differs — multi-def freezes on the FIRST repairSSAForNewDef call (full original
   interval, all lane subranges) and narrows Root LAST using it; the new single-def path freezes an
   interval with ONLY sub0 defined (upper lanes have no subrange), so `buildRSForSuperUse`/
   `collectReachingVNIs` rebases the upper lanes onto an illegal subreg index / non-align2 slice; OR
   (b) narrowing `%137` mutates `%128 = COPY %137` into a REG_SEQUENCE, making already-frozen/processed
   `%128/%159` snapshots stale → the align2/subreg errors land on the copy chain. TEST: revert #7 →
   corpus ~195; re-apply #7 alone; on an `Invalid subregister index` repro break in `buildRSForSuperUse`
   and compare FrozenOrigLI upper-lane subranges for a single-def Root vs a multi-def Root.

### KEY FINDINGS for tomorrow (recorded in `08-Worklog/BACKLOG.md` HIGH PRIORITY):
- **"Failed to find free physreg" class is a CROSS-CALL COLORING problem, NOT under-spilling** — greedy
  compiles these with `ScratchSize:0` (no spill). A value live across a call may only take callee-saved
  regs; the SSA one-shot coloring can't pack them (esp. wide *aligned* `vreg_128_align2`) where greedy
  succeeds via EVICTION. `undef-handling-crash-in-ra.ll`: `%137:vreg_128_align2` has only sub0 live
  (ISel wide-undef) + uncoalesced `COPY %137→%128/%159` chains → inflated demand on the 4 aligned
  callee-saved tuples. Real lever = **coalescing** (already "Pending: PHI coalescer") + the narrowing.
- **Spiller vs RA size RPLimit differently (HIGH PRIORITY, unresolved):** spiller uses
  `getMaxNumVGPRs(MF)` (gfx90a=128, −10%→116, INCLUDES the AGPR half); RA uses the allocatable count of
  the exact class (`RegClassInfo.getNumAllocatableRegs(VGPR_32)`=64). Spiller over-budgets ~2×. Which is
  correct + can they be reconciled? Likely spiller should query `getNumAllocatableRegs`. NOT changed yet
  (recorded only).

### NEXT SESSION plan:
1. Revert change #7 (RebuildSSA narrowing) → re-run corpus → confirm back to ~195/198. Then decide if #5/#6 net-help or also revert.
2. Commit the corpus-SAFE set (#1–#4) — they're net −29 and regression-free.
3. Attack "free physreg" via coalescing (the real fix) + revisit narrowing safely (legal-subreg/align2-aware).

---

## 2026-07-08 (eve) — 3 fixes committed+pushed; CRASH 275→224; free-physreg reclassified; spiller design docs

- **COMMITTED + PUSHED (ssara), 3 fixes this session:**
  - `c100e9a8` [AMDGPU] SSA RA: reject clobbered registers for values live across calls and inline asm —
    the CallSites clobber-interference mechanism (`.cpp` + `.h`): pickFreePhysReg rejects any candidate a
    live value crosses that a call regmask OR an instruction implicit physreg-def clobbers; PLUS fold each
    call regmask into MRI via `addPhysRegsUsedFromRegMask` so PEI's `findUnusedRegister` stops picking a
    call-clobbered SGPR as the whole-function FP-save reg. (Predicate = implicit non-reserved physdef;
    explicit defs excluded to avoid ~71-test coalescing churn + a bf16 occ/spill regression.)
  - `b293c794` [CodeGen][MachineLaneSSAUpdater] Source reconstructed old lanes by reaching VNInfo — fixes
    `Reading virtual register without a def` on RMW partial-def chains. Root cause (found via gdb, NOT the
    earlier iteration/ordering guesses): `buildRSForSuperUse` decided old-lane undef-vs-defined by the
    GLOBAL "does OrigVReg own a subrange" test; a lane that owns a subrange but is DEAD at the use (poison
    buffer-descriptor base read whole by a later store) was sourced as a live def-less read. Fix: decide
    per lane group from the reaching VNInfo at the use (`collectReachingVNIs`/`getVNInfoBefore`): null →
    undef; renamed-this-session → renamed vreg (build-time, order-independent); live non-renamed →
    OrigVReg placeholder. Surviving partial defs untouched.
  - (Also earlier in the day: the two clobber fixes were validated then squashed into `c100e9a8`.)
- **Corpus trajectory (harness `scripts/ssara_corpus_harness.py`, 3060 tests):** postfix12 CRASH 255 →
  postfix14 (clobber fix) 250 → **postfix15 (reaching-VNI) CRASH 224**. Every step 0 OK→CRASH; the few new
  REGRESSION_OCC_OR_SPILL all came FROM crash (net improvement). Undefined-physreg 9→1; reading-vreg 43→28.
- **[CORRECTED CLASSIFICATION] `Failed to find free physreg` (27) is NOT one cause** (user challenged the
  blanket "defer to spiller redesign"; only 2/27 have the inline-asm fragmentation signature). Clusters:
  AV/AGPR pinned-wide (7: a-v-*-atomicrmw, ds_*_a_v, rewrite/unspill-vgpr-mfma), GlobalISel div/rem i64
  (6), whole-wave/WWM (3), fragmentation-deferred (2: spill-scavenge-offset, spill-alloc-sgpr-init-bug),
  misc (9). gdb triage of `global_atomic_xchg_i32_ret_av_av_no_agprs` (gfx90a): two live `vreg_1024_align2`
  pin v0-v63, no slot for a `vreg_64` REG_SEQUENCE; greedy compiles at NumVgprs=64 + Scratch=132 (greedy
  SPILLS) → our spiller UNDER-spills. So AV cluster = genuine high-pressure spiller-planning, NOT trivial
  bugs (an earlier "greedy uses 11 VGPRs" read was the WRONG function in the file).
- **[NEW SKILL] `gdb-debugging`** (`~/.cursor/skills/gdb-debugging/SKILL.md`, drives persistent gdb via
  `scripts/gdbctl.sh`) — validated this session; pinpointed the AV failing MI + pinned-1024 pressure in a
  few commands. (Cursor fact: a newly added skill is only visible in NEW chats, not the creating one.)
- **[MEETING DIRECTION → design docs created]** Implement the fragmentation-aware spiller by augmenting
  `GCNUpwardRPTracker` with a precolored-unit BitVector + per-register-class `getClassCapacity(RC)` API
  (naive `⌊(N-|O|)/K⌋` first, run-based `Σ⌊Li/K⌋` later), replacing the ad-hoc scalar `LivePhysRP` (+ its
  dead-clobber over-count). Two new Design docs (mermaid + KaTeX):
  `SSARA/04-Design/GCNUpwardRPTracker_PerClassRP.md` and `SSARA/04-Design/Spiller_Redesign.md`.
  OPEN Q for tomorrow: `NumAvail/K` arithmetic — VReg_64 is 2 RU (so `/2`), meeting note said `/4`
  (=VReg_128); confirm per-class-K vs fixed-4-RU-slot granularity.
- **Next-session agenda:** (1) build the per-class RP tracker (milestone 1-2 in Spiller_Redesign.md),
  target the AV cluster; (2) continue crash triage — largest fixable = `Found PHI with NoPHIs` (43,
  SSA-destruct leftover PHIs, bitcast/Flow-block subreg-source PHIs) and remaining `Reading vreg` (28,
  wmma family); (3) port `b293c794` reaching-VNI fix to the `mssa-updater` worktree copy + gtests.

## 2026-07-08 — Two clobber fixes committed-ready + FULL spiller-redesign design recorded

- **Two APPROVED fixes in working tree (`AMDGPUSSARegisterAllocator.cpp`), corpus-validated (postfix14 vs
  baseline postfix12, 3060 tests):** (1) fold call regmask clobbers into `MRI` via
  `addPhysRegsUsedFromRegMask` in the clobber-site pre-scan → fixes PEI picking a call-clobbered SGPR as the
  whole-function FP save (`getVGPRSpillLaneOrTempRegister`→`findUnusedRegister` gated on
  `MRI.isPhysRegUsed`, which the RA framework normally populates and we bypassed). (2) generalize
  `CallSites` collection to also record instructions with an IMPLICIT non-reserved physical def (inline-asm
  `implicit-def dead early-clobber $vgprN`), so values live across inline-asm clobbers aren't colored onto
  clobbered regs. Predicate narrowed to `isImplicit()` after the broad version caused ~71-test
  OK→MIXED/DIFF_COALESCING churn + a `bf16.ll` occ/spill regression. **Result: `Using an undefined physical
  register` 9→1, CRASH 255→250, 0 OK→CRASH, churn eliminated, bf16 regression gone.** Remaining undefined-1
  = `indirect-addressing-si-gfx9` (distinct: real call/wide-tuple).
- **[DESIGN RECORDED — see NOTES.md 2026-07-08 "[DESIGN] Fragmentation-aware spiller + greedy fallback"]**
  Full multi-turn design for the `Failed to find free physreg` bucket, to consult WHEN the spiller redesign
  starts. Key conclusions: (a) root cause is the spiller's SCALAR 32-bit-slot pressure metric being blind
  to tuple ALIGNMENT/FRAGMENTATION from scattered pre-colored inline-asm clobbers (NOT occupancy, NOT
  "spiller ignores clobbers"); greedy survives only via spill-on-placement-failure. (b) This is the
  aliasing + pre-coloring NP-hard fringe — `MAXLIVE<=k` in slots is necessary-not-sufficient; the SSA
  colorability theorem's preconditions (uniform regs, no pre-color) are violated. (c) HARD INVARIANT:
  coloring MUST NEVER insert instructions — spill/reload need `EXEC(spill)==EXEC(reload)` or WWM, tractable
  only in the dedicated early spiller; this is THE reason SSA RA exists, so greedy-style spill-at-color is
  FORBIDDEN → coloring must be guaranteed to succeed before it starts (no in-flight recovery). (d) Plan:
  fragmentation-aware early spiller (per-width capacity `F(defRC, demand_W from LIS, preColored(P)
  arrangement, widerFootprint_W)`; pre-color state = LIS reg-unit ranges + regmask index; width-descending
  charge) + a CONSERVATIVE early (pre-RebuildSSA) whole-function greedy-fallback gate for the residual
  fringe. Per-function routing = flag + guarded dual pass-chains (in-allocator split RULED OUT).

## 2026-07-07 (PM) — Corpus crash reduction: 10 fixes total; CRASH 852 -> 275

- **Continuation of the corpus-driven triage (harness `scripts/ssara_corpus_harness.py`).** Regression
  gate = per-test bucket TRANSITION vs baseline run `scripts/out/ssara-corpus/full-run2` (852 CRASH).
  **Net: CRASH 852 -> 275 (-577, -68%), 577 files fixed, 0 compiled->crash and 0 compiled->worse-alloc
  regressions; SSARA+SSASpiller lit 87 pass + 1 XFAIL throughout.**
- **Commits (manual):** `9b30c8ab` (the 6 morning fixes; amended from mangled-subject `656baf05` then
  force-pushed `--force-with-lease` — content identical), `4cb211e6` (#7), `867d2e17` (#8), `60727a8a`
  (#9). **#10 UNCOMMITTED** — held until the call-site `undefined physical register` class is fully
  resolved (working tree: `AMDGPUSSARegisterAllocator.{cpp,h}`).
- **#7 color defs/uses by operand FLAG not position** (`color()`): `MI.defs()/uses()` key off operand
  position (`getNumExplicitDefs()==0` for INLINEASM), so inline-asm-defined vregs went uncolored.
  Iterate `MI.operands()` by `isDef`/`isUse`; EXCLUDE implicit defs (`|| MO.isImplicit()`) since they are
  call/instr clobbers `MI.defs()` also skipped (marking them occupied exhausts the file). INLINEASM
  constraint defs are explicit; only clobbers implicit. `Virtual register not colored` 286 -> 1.
- **#8 source undef lanes as undef** (`buildRSForSuperUse`): whole-reg use of a partially-undef wide
  value (poison buffer-descriptor base ptr) decomposed to a REG_SEQUENCE read the undef lanes plainly ->
  `Reading vreg without a def`. Split `LanesFromOld` into defined (union of OldVR subrange lanemasks; NO
  `liveAt` - too strict) vs undef (no subrange), source undef with `RegState::Undef`. 85 -> 43.
- **#9 no dying-use reuse for early-clobber defs** (`color()`): kills-before-defs freed a dying source
  that an early-clobber def then reused (`early-clobber $sgpr0_sgpr1 = S_LOAD_ec $sgpr0_sgpr1`) -> read a
  clobbered value. When the MI has an early-clobber def, defer freeing dying uses until after the def
  loop (DeferredUnits for physreg per-unit resets vs DeferredFree for colored-vreg markFree - different
  granularity: physreg units are independently live, colored vregs die atomically).
- **#10 (UNCOMMITTED, INCOMPLETE) call-clobber-aware coloring** (`color()`+`pickFreePhysReg`, member
  `CallSites`): a vreg live across a call was colored to a reg the call destroys (csr_amdgpu regmask OR
  explicit call def like return-addr `$sgpr30_sgpr31`) -> `undefined physical register`. Reject a
  candidate if the vreg is `liveAt(callSlot)` and `CallMI->modifiesRegister(PR)` or a regmask clobbers
  it. 64 -> 30. REMAINING 30 = a DIFFERENT sub-cause: CSR save/restore in the frame prologue/epilogue
  (`$sgpr33 = frame-destroy COPY $sgpr6`) - finish that before committing #10.
- **NEXT:** finish the call-site class (CSR save/restore undefined-physreg) then commit #10; then by
  impact `Reading vreg without a def` (43), `Invalid subregister index` (26), `Operand has incorrect
  register class` (25), `DefOp NewDefMI should have a def operand` (18). `Found PHI with NoPHIs` (43) is
  mostly fatal-path MF.verify collateral and should shrink as real errors are fixed.

## 2026-07-07 — Corpus-driven SSA-RA crash reduction: 6 fixes (COMMITTED+PUSHED 656baf05)

- **[TOOL] `scripts/ssara_corpus_harness.py`** (in `github/scripts/`, NOT llvm-project). Runs the whole
  `llvm/test/CodeGen/AMDGPU` corpus through the SSA stack: reuses each test's own RUN line, strips
  `|FileCheck`/`-o`, injects `-amdgpu-ssa-regalloc` (+`-verify-machineinstrs`), and on success diffs
  per-function VGPR/AGPR/scratch/occupancy vs Greedy (same cmd minus the flag). Buckets: CRASH(by
  normalized signature), OK_EQUAL/OK_BETTER, DIFF_COALESCING, MIXED, REGRESSION_OCC_OR_SPILL,
  PREEXISTING_FAIL, TIMEOUT, NO_METRICS, SKIP_*. `run`/`report` subcommands; parallel `--jobs`
  (default ncpu/2); resumable `results.jsonl`. **The regression gate is the per-test bucket TRANSITION
  vs a baseline run dir (compiled-at-baseline -> crash-now), NOT net class counts.** Baseline run
  `out/ssara-corpus/full-run2`, final `postfix6`. Metric caveat: `.set *.num_vgpr` omits AGPRs;
  occupancy can drop with VGPR unchanged on MFMA — check `.num_agpr` too.
- **[RESULT] Clean Pareto improvement: CRASH 852 -> 490 (-362), 362 files fixed, 0 compiled->crash AND
  0 compiled->worse-alloc regressions; SSARA+SSASpiller lit 87 pass + 1 XFAIL.**
- **[6 FIXES] one commit 656baf05** (`AMDGPURebuildSSA.cpp`, `MachineLaneSSAUpdater.cpp`,
  `AMDGPUSSARegisterAllocator.{cpp,h}`):
  1. RebuildSSA **single-block RMW partial-def chains**: a non-`undef` subreg def read-modify-writes the
     super-reg, so a wide value built from a chain where only the first def has `undef` must keep the
     establishing (earliest-slot) def as Root and rename re-defs in REVERSE dominance order (Root
     narrowed last). Gated `SingleBlock && HasRMWRedef`. Killed `Use not jointly dominated by defs`
     117->0 + its verifier twin `Reading vreg without a def`.
  2. MachineLaneSSAUpdater `rewriteUseReaching`: derive REG_SEQUENCE result class from the base-0
     **rebased** lane mask (`rebaseLaneMask(OpMask,OpMask)`), since unaligned super-reg subregs
     (sub1_sub2_sub3 of sgpr_128) have no `getSubRegisterClass`.
  3. `eliminateRegSequences`: an unaligned dest subreg slice (`getSubReg(Dst,Sub)==NoRegister`, because
     SGPR tuples >=64b exist only at aligned bases — SGPR_64 stride 2, SGPR_96/128 stride 4) is lowered
     as per-dword 32-bit copies via `getChannelFromSubReg`+`getSubRegFromChannel`.
  4. `rewriteOperands`: assign `RegClassInfo.getOrder(RC).front()` to undef-only operands (no value to
     color; undef flag preserved). Fixed `Virtual register not colored` 286->111.
  5. `resolvePermutation`: AGPR is a THIRD file (no swap/xor) — break AGPR cycles with an AGPR scratch,
     not the SGPR path (which emitted illegal `$sgpr=COPY $agpr`). New `MaxAGPRIdx`, high-water tracked
     by the CHOSEN physreg file (also fixes latent av_*->VGPR undercount).
  6. RebuildSSA `flattenRegSequences`: collapse nested REG_SEQUENCE towers (areg_64->96->...->384) the
     lane-by-lane rebuild produced; absent a coalescer they inflate pressure (bf16 MFMA 43 AGPR/occ5 ->
     32/occ8 == greedy). Inline single-use whole-read child RS, composing lanes via
     `composeSubRegIndexLaneMask` (NOT `composeSubRegIndices`, which silently mis-handles compositions
     missing a defined subreg index).
- **[LEARNINGS]** (a) a test that ABORTS has NOT passed — never accept "the crash moved to another pass";
  (b) grep the component for existing helpers (`rebaseLaneMask`, `getSubRegIndexForLaneMask`,
  `composeSubRegIndexLaneMask`, `getCoveringSubRegsForLaneMask`) BEFORE theorizing from stack traces;
  (c) `composeSubRegIndices(a,b)` = b within a AND silently returns garbage for illegal compositions ->
  use lane-mask composition; (d) `SmallPtrSet<Register>` does not compile -> `DenseSet<Register>`.
- **[NEXT]** top remaining crash buckets (postfix6): `Virtual register not colored` 111 (non-undef
  sub-cause), `Using an undefined physical register` ~87, `Reading vreg without a def` ~98, `PHI with
  NoPHIs` ~47 (largely fatal-path MF.verify collateral). Attack `not colored` 111 + `undefined physical
  register` 87 next by impact. Still open from prior agenda: deeper spiller redesign (#1b), design-doc
  refresh (SSA_RA_Coloring), SSARA kickoff deck (needs 3 workstream areas).

## 2026-07-08 (housekeeping) — workspace-layout rule, AGENTS drift fix, gdb debugging tooling

Meta/workflow session (no SSARA compiler code changed).

- **[RULE] `.cursor/rules/workspace-layout.mdc`** (always-apply): canonical worktree layout under `github/` (ssara [primary/integration], next-use-analysis [NUA], early-ssa-spiller [SSA Spiller], mssa-updater [+gtest harness], llvm-project [clean upstream], scripts [permanent tools], ssa-spiller-docs [the "docs" repo: design docs + NOTES + SHARED_CONTEXT]) + script placement: permanent/multi-session → `scripts/`, throwaway/one-off → `/tmp`.
- **[AGENTS DRIFT — root cause + fix]** The corpus harness (built 07-06, used through 07-07) had NO reference in AGENTS.md although richly recorded in SHARED_CONTEXT/NOTES. Root cause: AGENTS is fed ONLY by `agents-memory-updater`, whose transcript index was stale/divergent — two files, `ssara/.cursor/hooks/state/continual-learning-index.json` (@2026-07-04, key `last_updated`) vs `~/.cursor/projects/…/…` (@2026-07-06T18:01, key `updated_at`) — and it never processed the 07-07 sessions. "Save context" reliably updates NOTES/SHARED_CONTEXT, but the AGENTS promotion step didn't run. Fixed: recorded the harness as a durable AGENTS fact, marked agenda item (2) DONE, corrected the stale worktree bullet. LESSON: on "save context", promote durable tools/facts DIRECTLY into AGENTS — do not rely solely on the updater. (Open: reconcile the two divergent index files / run agents-memory-updater to catch up 07-07.)
- **[TOOL] `scripts/gdbctl.sh`** — persistent, agent-driven gdb across separate tool calls (background gdb reads a FIFO; sentinel-synced; `start`/`send`/`log`/`status`/`stop`; state persists). Verified controlling the 1.8 GB debug `llc` (first symbol-resolving break ~1-2 min, then fast; `GDBCTL_TIMEOUT`, `GDBCTL_DIR`).
- **[SKILL] `~/.cursor/skills/gdb-debugging/SKILL.md`** (personal) — wraps gdbctl + a 6-step "debug the test crash" algorithm chaining the triage/evidence/regression/approval rules; auto-invokes on "debug the test crash". CURSOR FACT: skills are discovered at startup/chat-start → available only in NEW chats (not already-open ones); rules differ (re-scanned per message, reach open chats next turn).

## 2026-07-07 — Workflow/interface housekeeping (rules + Cursor auto-run allowlist + audit hook)

Meta session (no SSARA compiler code changed). Tuned the human↔AI interface and Cursor guardrails.

- **[RULES] Two new always-apply `.cursor/rules/`** (join `investigate-dont-rationalize` as the epistemics/regression cluster):
  - `evidence-over-memory.mdc` — no claims about root cause/behavior/fix from memory or theory; ground every claim in real-execution evidence (dumps, logs, a reproducing run, verifier). Memory/NOTES/SHARED_CONTEXT are leads, not verdicts. Prefix unverified statements with **HYPOTHESIS:**.
  - `regression-baseline-is-truth.mdc` — the known-good baseline is the sole arbiter of a behavior change; a failure that merely MOVES/changes shape (different pass, different error, different test) is still an unresolved regression, never "progress"; only baseline-or-better = done.
- **[CURSOR AUTO-RUN — verified empirically, Cursor 3.2.16, Windows client + Linux remote]** Auto-Run Mode = "Use Allowlist". The authoritative gate is the **Settings-UI Command Allowlist**, stored CLIENT-SIDE (Windows `AppData\Roaming\Cursor`), NOT editable from the Linux box → user adds entries via UI. Matching is command-string **PREFIX**-based; it **governs background subagents too** (non-allowlisted subagent command → View/Allow prompt in parent UI, blocks the subagent until clicked). `ninja -C build/user-debug` as an entry scopes builds to the correct folder. Prefix matching can't carve exceptions → bare `sed`/`find` also allow `sed -i`/`find -delete`; scoped `sed`→`sed -n`, left `find` OFF (OPEN ITEM: find is agent-critical — revisit via subagent hook-DENY test or Cursor 3.6+ Auto-review).
- **[HOOK]** `beforeShellExecution` hook fires for subagents but its `allow` is NOT honored there (they fall back to the UI allowlist); a logging-only hook (read stdin, write nothing, exit 0) safely ABSTAINS (verified — does not default to allow). Installed audit hook: `.cursor/hooks.json` → `.cursor/hooks/shell-guard.sh` → log at `.cursor/hooks/state/shell-guard.log`. Subagent discriminator in hook input: `transcript_path == null`.
- **[OPEN ITEM]** `find` read-only auto-run without permitting `-delete`/`-exec`: (a) empirically test whether hook-DENY is honored inside subagents (then allowlist `find` + deny mutating forms), or (b) upgrade to Cursor 3.6+ Auto-review. User: "get back to this soon."

## 2026-07-06 (PM) — AMDGPU corpus harness + single-block RMW fix (applied, uncommitted, DECISION PENDING)

- **[TOOL] `scripts/ssara_corpus_harness.py`** (in `github/scripts/`, NOT llvm-project). Runs the whole
  `llvm/test/CodeGen/AMDGPU` corpus through the SSARA stack: reuses each test's OWN RUN line, strips
  `| FileCheck`/`-o`, injects `-amdgpu-ssa-regalloc` (+`-verify-machineinstrs` correctness gate), runs
  our stack; on success re-runs the same cmd minus the flag (Greedy) and diffs per-function
  `; TotalNumSgprs/NumVgprs/ScratchSize/Occupancy` + `.set *.num_vgpr/.numbered_sgpr/.private_seg_size`.
  Buckets: CRASH (normalized sig), OK_EQUAL/OK_BETTER, DIFF_COALESCING, MIXED, REGRESSION_OCC_OR_SPILL,
  PREEXISTING_FAIL, TIMEOUT, NO_METRICS, SKIP_*. Parallel `--jobs` (default ncpu/2), resumable
  `results.jsonl`, `run`/`report` subcommands. Parser handles bash `<` metachar, `2>&1`, lone `-`
  (stdin), `%t.bc` generated inputs. Runs: `scripts/out/ssara-corpus/{full-run2 (baseline), postfix}`.
- **[TRIAGE baseline `full-run2`]** 3060 .ll; 850 skipped; 2210 attempted -> 852 CRASH (38.6%), 1357
  compiled. Allocation quality ~= Greedy (only 9 REGRESSION_OCC_OR_SPILL; rest equal/better/coalescing).
  **Headline: crashes are the problem, not allocation quality.** 852 crashes = 26 classes; top6 = 87%.
  By owner: SSA-RECON 257 (117 `Use not jointly dominated`, 85 `Reading vreg without a def`, 47 `PHI
  with NoPHIs`=collateral of the fatal-path MF.verify), RA-COLORING 319 (286 `Virtual register not
  colored`, 17 tied-use, 11 failed-physreg), OP-REWRITE 259 (119 `use operand subreg has no register
  class`, 85 `undefined physical register`, ...). Full report + prioritized plan:
  `scripts/out/ssara-corpus/full-run2/TRIAGE_PLAN.md`.
- **[ROOT CAUSE #1 — RMW partial-def chains]** `add.ll -mcpu=verde` (@s_add_v8i32, single straight-line
  block). Wide vreg built by a chain of partial subreg defs where only the FIRST has `undef`; later
  subreg defs without `undef` READ-MODIFY-WRITE (implicitly read unwritten lanes). Old RebuildSSA split
  them as independent re-defs; renaming the establishing (undef) def stripped lanes later RMW defs read
  -> `createAndComputeVirtRegInterval` aborts `Use not jointly dominated`. Same root as the 85 `Reading
  vreg without a def` (verified: same `RebuildSSA -> repairSSAForNewDef -> performSSARepair ->
  createAndComputeVirtRegInterval -> LiveRangeCalc::findReachingDefs` path; the two strings are the same
  failure via report_fatal_error vs the forced MF.verify dump). ~202 crashes, one root.
- **[FIX APPLIED, UNCOMMITTED — `AMDGPURebuildSSA.cpp`]** For a vreg whose defs are ALL in one block and
  include a non-`undef` subreg def (`SingleBlock && HasRMWRedef`): Root = establishing (earliest-slot)
  def via `(DomPreorder, slot)` tie-break; re-defs renamed in REVERSE order (latest first) so each
  still-present def reads only dominating, not-yet-renamed lanes; Root processed last and narrowed
  normally (pressure-neutral, no wide leftover). Multi-block/loop vregs keep byte-identical old behavior
  (reverse-order is only dominance-safe intra-block; loop back-edge reads are not from dominators).
- **[RESULT — NOT A CLEAN WIN; user must decide next session]** SSARA+SSASpiller lit = 87 pass + 1 XFAIL
  (0 CURATED regressions). Harness `postfix` vs `full-run2`: `Use not jointly dominated` 117->0
  (eliminated), Two-address 13->1, net CRASH 852->785 (-67). BUT per-test transitions: **192 fixed
  (CRASH->compile), 125 REGRESSED (compiled-before -> CRASH-now)**; 123/125 = `UseRC && "use operand
  subreg has no register class"`, overwhelmingly WIDE-DESCRIPTOR intrinsics (image/buffer, dwordx3=96b).
  Root of regression: reverse-order reconstruction changes which def owns which lanes at a use, pushing
  wide uses out of `rewriteUseReaching`'s whole-operand early-return (MachineLaneSSAUpdater.cpp:448)
  into the partial-REG_SEQUENCE path (line 465-468), where `TRI.getSubRegisterClass(OpRC, subreg)`
  returns NULL for those widths -> assert. LATENT reconstruction weakness the reorder exposes.
- **[DECISION PENDING — resume here tomorrow]** Options (asked user, unanswered): (a) REVERT to clean
  baseline (loses 192 fixes, reintroduces 117); (b) KEEP + add COUPLED fix = handle null `UseRC` in
  `rewriteUseReaching` (derive REG_SEQUENCE result class for the lanemask when `getSubRegisterClass` is
  null; read `buildRSForSuperUse` + class-derivation APIs first), then re-run harness to confirm 0
  compile->crash regressions. RECOMMENDATION: (b) if UseRC-null handling is small, else revert +
  scoped follow-up. Repro: `llc -mtriple=amdgcn -mcpu=tonga -amdgpu-ssa-regalloc
  llvm.amdgcn.buffer.store.dwordx3.ll` (@raw_buffer_store_format_immoffs_x3). Working tree has the
  uncommitted `AMDGPURebuildSSA.cpp` edit (user commits manually — DO NOT commit).
- **[Remaining agenda unchanged]** #1b deeper spiller redesign; #3 design-doc refresh (SSA_RA_Coloring +
  reaching-VNI/Option-3); #4 SSARA kickoff deck (needs 3 workstream areas from user). Next crash target
  after RMW: `Virtual register not colored` (286, coloring) and `use operand subreg has no register
  class` (base 119, now the #1 blocker on wide builds).

## 2026-07-06 — Legacy dominance/IDF SSA-repair path removed (ssara, committed+pushed)

- **[CLEANUP]** Single commit (-967/+54). Design is now unified on reload-as-redef + inline
  reaching-VNI repair, so the old dominance/dom-group/IDF path was deleted:
  - **Spiller** (`AMDGPUSSARegisterSpiller.{cpp,h}`): removed orphaned legacy reload cluster
    (`emitReload`, `emitReloadToReg`, `reloadBefore`, `reloadAtEnd`, `repairSSAForReload`,
    `processPIdfBlock`, `processKillDominatedGroups(WithList)`, `fixPathologicalPHIs`) + unused
    `getRegNameForDebug`. Live path: `emitReloadsAndRepairSSA` →
    `getOrCreateReloadInBlock`/`insertReloadForUse` + `optimizeReloadPlacing` + `canHoistReloadTo`.
  - **MachineLaneSSAUpdater** (`llvm/lib/CodeGen/MachineLaneSSAUpdater.cpp` + header): removed the
    `UseReachingOracle` flag (only ever set false in the now-callerless `repairSSAForReload`, so it was
    always true); collapsed both guarded branches to the reaching path. Deleted `repairSSAForReload`,
    `createPHIInBlock`, `findRenamedReachingDef`, `insertPHIAtBlock`, `getPrunedIDF`, `incomingOnEdge`,
    and the write-only `RenamedLaneDefs` map (superseded by `DefInstrToRenamed`, MachineInstr*-keyed).
    `insertLaneAwarePHI(Register OrigVReg, LaneBitmask DefMask)` now places PHIs solely from OrigVReg's
    frozen isPHIDef VNInfos; `rewriteDominatedUses` always calls `rewriteUseReaching`.
  - NOTE: this was done ONLY in the ssara worktree. No port to `mssa-updater`/`early-ssa-spiller` has
    been done or planned in this session.
- **[DESIGN] IDF fully removed (2026-07-06, COMMITTED+PUSHED as 839660b).** No IDF anywhere in
  MachineLaneSSAUpdater/spiller. PHI placement (reconstruction) reads the isPHIDef VNInfos
  LiveIntervalCalc materializes in OrigVReg's frozen interval when it is recomputed after reload
  re-defs (reload-as-redef keeps the value live through merges via the still-attached original uses).
  The spiller's `isUseReachableFromDef` only asked whether a use is downstream of the kill — for SSA
  that is exactly plain CFG reachability (the pruned-IDF slow path was set-equivalent). Now it is a
  successor-closure BFS from the kill block to the use target block (PHI use → predecessor block),
  same-block by slot order + `MDT.dominates` fast path; DefMask param dropped. DELETED: `computePrunedIDF`,
  `IDFCache`/`IDFCacheKey`(+DenseMapInfo), `clearIDFCache`, `defDominatesUse`, `defReachesUse`, the
  MachineOperand overload of `isUseReachableFromDef`, and the GenericIteratedDominanceFrontier.h include.
  Kept DenseMapInfo<LaneBitmask> (used by LanePHIs). Behavior-preserving (test counts == baseline); the
  only DF work left is inside core LiveIntervalCalc. Deferred follow-up (1b): reload only kill-dominated
  uses + let reconstruction absorb parallel-path merges → would remove `isUseReachableFromDef` entirely.
- **[TEST STATE]** SSASpiller+SSARA lit: 86 pass + 1 legit XFAIL (`spill-loop-skip-def-inside.mir` —
  unimplemented loop-aware spill-candidate fallback; keep). MachineLaneSSAUpdater dir: 3 real-pipeline
  `.ll` pass; 4 `.mir` harness tests fail because `-run-pass=test-machine-lane-ssa-updater` is not
  registered in the ssara build (pre-existing infra, not correctness).
- **[BUILD/TEST]** `ninja -C build/user-debug LLVMCodeGen LLVMAMDGPUCodeGen` (libs); `ninja -C
  build/user-debug llc FileCheck` (tools; no llvm-lit ninja target). Lit: `python3
  build/user-debug/bin/llvm-lit -sv <dirs>`.
- **[NEXT SESSION]** (1) DONE — IDF eliminated + machinery deleted (staged); optional 1b = deeper
  spiller-planning redesign to drop `isUseReachableFromDef`. (2) `scripts/` AMDGPU e2e harness → bucket
  failures → triage/fix plan; (3) update `SSARA/04-Design/SSA_RA_Coloring.md`; (4) SSARA team kickoff
  deck (3 engineers, split TBD).

## Worktree Layout

| Worktree | Branch | Purpose |
|----------|--------|---------|
| `ssara` | ssara | SSA Register Allocator (main development) |
| `early-ssa-spiller` | early-ssa-spiller | SSA Spiller (synced with ssara) |
| `next-use-analysis` | next-use-analysis | Next Use Analysis pass |
| `mssa-updater` | mssa-updater | MachineLaneSSAUpdater |
| `ssa-rebuilder` | ssa-rebuilder | AMDGPURebuildSSA refactoring |

## SSA Register Allocator — Current State

### Implemented
- Pass skeleton: `AMDGPUSSARegisterAllocator.{h,cpp}` (~485 LOC)
- Width classification: `std::set<unsigned, std::greater<unsigned>> ColoringOrder`
- PEO coloring: width-descending MDT pre-order walk, greedy smallest-free
- Tied operand handling via `MI.isRegTiedToUseOperand()`
- Physical live-in tracking
- PHI kill-tracking fix: `if (MI.isPHI()) continue;` — PHI source operands
  are live only to predecessor block boundaries (LiveIntervalCalc.cpp:175),
  not inside the PHI block. Kill tracking would double-free physregs shared
  with PHI results.
- SSA Destruction + Operand Rewrite (combined pass):
  - `lowerPHIs()`: worklist-based chain/cycle permutation decomposition
  - Three-tier cycle breaking: (1) scratch reg matching cycle width if
    occupancy preserved, (2) V_SWAP_B32 per subreg on GFX9+, (3) XOR triplet
  - Critical edge splitting on demand via `SplitCriticalEdge`
  - `rewriteOperands()`: vreg→physreg replacement with subreg composition
  - Precondition: SI control-flow pseudos must be lowered first
  - MaxHWLimit respects `amdgpu-num-vgpr` via `ST->getMaxNumVGPRs(MF)`
- Kill-before-def ordering in colorByWidth: uses freed before defs colored,
  allowing def to reuse dying source's physreg. PHI kills still skipped.
- Physical register tracking in coloring: physreg defs call markOccupied,
  physreg uses check liveAt per reg unit and free dead units.
- Spiller physreg pressure: LivePhysRP counter seeded from MBB->liveins(),
  per-instruction kills-before-defs. Pressure in 32-bit slots; wide physregs
  via getRegSplitParts. Reserved regs (EXEC etc.) filtered via isReserved.
  Key: VGPR_32 has 2 reg units but 1 pressure unit — use sizeInBits/32.
- `countSGPRSpillVGPRs()` (2026-06-11): pure frame-size accounting; `ceil(Σ
  objectSize(FI)/4 / WaveSize)` over distinct SGPRSpill FIs. Replaces old
  `lowerSGPRSpills()` which crashed by calling `getPhysRegBaseClass(virtual_reg)`
  pre-coloring. `VGPRLimit -= N` between Pass 1 and Pass 2. No physreg side
  effects in the spiller.
- MIR test pattern (2026-06-11): physical liveins in spiller tests replaced with
  `IMPLICIT_DEF` + `COPY` to avoid physreg-in-vreg assertion. Hand-maintained
  CHECK lines for `SI_VIRTUAL_SPILL_MARKER` placement. XFAIL for tests exercising
  unimplemented fallbacks (loop-filter not implemented).
- Partial subreg spill fix (2026-06-11): `getVMPsToSpill` "too-large" branch now uses
  `getRegSplitParts(SubRC, 4)` to take only the needed 32-bit parts. `SIInstrInfo::
  storeRegToStackSlot` SGPR path now passes `SubRegIdx` to `addReg` and guards
  `constrainRegClass` with `SubRegIdx == 0`. Wide vregs (e.g. `sreg_64`, `vreg_128`)
  now spill only the needed sub-slot; SSA repair inserts `REG_SEQUENCE` at restore.
  Tests added: `spill-sgpr-linear-basic.mir` (32-bit SGPR), `spill-sgpr-wide.mir`
  (64-bit SGPR, one writelane lane). Autogenerated tests regenerated.
- 61 PASS + 3 XFAIL across RA+Spiller suites (spill-loop-skip-def-inside.mir
  and spill-loop-reload-inside-fallback.mir XFAIL; one balanced-use-before XFAIL)
- End-to-end RA pipeline fully functional (coloring → SSA destruction → operand rewrite)
- RebuildSSA pass ported and registered (9 fixes applied)

### Pipeline Integration (COMPLETE, 2026-06-11)
- AMDGPURebuildSSA ported from PR #156049 into ssara worktree (9 bug fixes applied)
- `-amdgpu-ssa-regalloc` flag wired in `addRegAssignAndRewriteOptimized()`;
  replaces entire greedy SGPR/WWM/VGPR chain with: RebuildSSA → SSA Spiller → SSA RA
- Pre-RA sequence unchanged (PHIElim + TwoAddress + RegCoalescer + RenameIndependentSubregs)
- RebuildSSA is temporary bridge: converts post-PHIElim non-SSA MIR back to SSA
- Three post-RA property fixes in AMDGPUSSARegisterAllocator (we skip VirtRegRewriter):
  - `finalizeProperties()`: sets NoPHIs + NoVRegs; preserves TracksLiveness
  - `eliminateRegSequences()`: lowers REG_SEQUENCE pseudos to COPYs or deletes trivial ones
- Smoke tests pass: basic-loop.ll, spill-cfg-position.ll, rewrite-vgpr-mfma-to-agpr-phi.ll

### Removed
- LR splitter removed 2026-05-26. Width-descending coloring already reuses freed slots.
- PHI false-interference fix loop removed 2026-06-05. PHI sources are live only
  to predecessor boundaries in LLVM's LiveIntervals — no false interference exists.

### Not Started
- SGPR lowering tests: one-by-one (CFG + liveness → approval → create → run). Priority
  for next session.
- VGPR spill lowering: `SIRegisterInfo::eliminateFrameIndex` handles `SI_SPILL_V*_SAVE/RESTORE`
  via PEI; requires physical regs (SSA RA delivers) + `ScratchRSrcReg` reserved by
  `SIFrameLowering` prologue. Mechanism identified; E2E smoke tests are the proof.
- Full pipeline flag (`-amdgpu-ssa-regalloc`) wire-up and `.ll` smoke tests
- PHI coalescer (paper section 4.3)
- Spiller tied-operand RP fix

## Key Design Decisions

- **Width-descending coloring** solves mixed-width fragmentation
- **Splitter removed**: coloring already reuses freed slots at def points
- **No per-file separation**: SGPR/VGPR/AGPR reg units don't overlap
- **Tied operands**: inherit use's physreg via MI.isRegTiedToUseOperand()
- **SSA = one segment per vreg**: no LiveInterval segment iteration needed
- **Reg units for interference**: BitVector indexed by MCRegUnit handles all overlap cases
- **PHI sources live to predecessor boundary only**: LiveIntervalCalc extends PHI uses to getMBBEndIdx(PredMBB), not into the PHI block. No false interference — kill tracking skip is sufficient.
- **Scratch reg width-matched**: cycle-breaking scratch tuple matches the cycle's register width, not always 32-bit
- **MaxHWLimit from function attribute**: `ST->getMaxNumVGPRs(MF)` respects `amdgpu-num-vgpr`
- **DynVGPRBlockSize**: all occupancy queries use subtarget's dynamic VGPR block size

See [[SSARA/04-Design/SSA_RA_Coloring|SSA RA Coloring Design]] for coloring documentation.
See [[SSARA/05-Testing/SSA_RA/SSA_RA_TEST_PATTERNS|SSA RA Test Patterns]] for test documentation.

## Key APIs

- `SIRegisterInfo::getHWRegIndex(MCRegister)` = encoding & REG_IDX_MASK
- `AMDGPU::VGPR0 + idx` = contiguous VGPR_32 physreg enum
- `TRI->getMatchingSuperReg(BaseReg, AMDGPU::sub0, RC)` = tuple from base
- `GCNSubtarget::getOccupancyWithNumVGPRs(VGPRs, DynBlockSize)` = occupancy
- `GCNSubtarget::getMaxNumVGPRs(Occ, DynBlockSize)` = max VGPRs for occupancy
- gfx900: 256 VGPRs, granule=4, MaxWaves=10. Thresholds: ≤24→10w, 28→9w, 32→8w

## Build Configuration
- CMakePresets: upstream + shared CMakeUserPresets.json symlink
- Build preset: user-debug, dir: build/user-debug

## Tools & Docs
- md2pdf.py: `ssa-spiller-docs/SSARA/tools/md2pdf.py` (mermaid 9.4.3 + KaTeX + highlight.js;
  auto-discovers cursor-server node/chromium; `~~~` invisible-link syntax unsupported)
- publish_public.sh: INCLUDE_PATHS updated 2026-06-11 (SSA_Spiller → SSARA + SHARED_CONTEXT.md)
- Design doc: `ssa-spiller-docs/SSARA/04-Design/SSA_RA_Coloring.md`
  (Operand Rewrite + SSA Destruction marked ✅ 2026-06-11)
- Architecture.md rewritten 2026-06-11 with full pipeline diagram (SILowerSGPRSpills box)
- Worklog: `08-Worklog/NOTES.md` diary; `08-Worklog/BACKLOG.md` + `08-Worklog/FUTURE_IMPROVEMENTS.md`
  added 2026-06-11

## Future Optimizations

Design considerations identified but not yet implemented. Each entry notes
the component, the idea, and when it might become relevant.

- **[SPILLER] Threshold-guarded SGPR→VGPR lowering**: Instead of lowering all
  SGPR spills to VGPR lanes unconditionally, cap allocation so
  `VGPRLimit - SpillVGPRs >= Threshold`. Excess SGPR spills go to memory.
  Relevant when real programs show SGPR spill VGPRs starving VGPR budget.

- **[SPILLER] Per-program-point SGPR routing**: At each SGPR spill point,
  use local VGPR pressure (known from Pass 1 forward walk) to decide:
  VGPR-lane if slack exists, memory if tight. Hybrid lowering — some
  spills go to lanes, others to memory, per-instruction.

- **[SPILLER] Narrow spill-VGPR liveness**: Spill VGPRs are live only
  in [first_writelane, last_readlane], not the entire function. Integrate
  their liveness into LivePhysRP tracking in Pass 2's forward walk for
  tighter budget accounting (Phase 2 of lowerSGPRSpills).

## RebuildSSA → MachineLaneSSAUpdater refactor

### Phase 1: AMDGPURebuildSSA refactor — COMPLETE AND COMMITTED (2026-06-18)

**Bug fixed (Q1)**: inline RebuildSSA left partial wide defs (`undef %r.sub0:vreg_64`) for the
first subreg def, splitting only re-defs. Result: `%r` is a `vreg_64` carrying ONE live lane;
RA allocates the full tuple → register-pressure inflation → loop-coloring abort / v128 verifier
"undefined physical register".

**Implementation** (AMDGPURebuildSSA.cpp):
- Replaced ~250 lines of inline SSA repair (`buildRealPHI`, `splitNonPhiValue`, `rewriteUses`,
  `buildRSForSuperUse`, `extendAt`, `reachedByThisVNI`, `operandLaneMask`) with
  `MachineLaneSSAUpdater::repairSSAForNewDef`.
- Removed `MachineLoopInfo` dependency; replaced `MachineLoopInfo.h` with `MachineLaneSSAUpdater.h`.
- New `runOnMachineFunction` loop: find Root (earliest non-PHI VNInfo in dom-preorder), build
  WorkList of non-Root non-PHI VNInfos sorted dom-preorder + Root appended last, single loop
  calling `repairSSAForNewDef`. Root handled only if it has a subreg def operand (Q1 fix).
- LI reference scoped before the repair loop with comment: "repairSSAForNewDef replaces
  OrigVReg's interval object, invalidating any reference held across calls".
- `RenumberValues()` removed (updater recomputes via `removeInterval` +
  `createAndComputeVirtRegInterval`; `shrinkToUses` explicitly avoided for PHI-operand
  correctness). `MF.verify()` runs in debug builds.

**Validation**: previously XFAIL `pipeline-spill-loop.ll` and `pipeline-wide-v128.ll` both now
pass. Full SSARA suite 36/36; 78 tests total (36 SSARA + 42 SSASpiller), 0 unexpected failures.

### fixPathologicalPHIs dead-PHI bug — FIXED AND COMMITTED (2026-06-18)

**Context**: `fixPathologicalPHIs` in `AMDGPUSSARegisterSpiller.cpp` finds PHIs still
referencing spilled vregs and replaces them with `SI_SPILL_V32_RESTORE`. KillMI = the
`SI_VIRTUAL_SPILL_MARKER` placed at the end of bb.0 (entry). For a loop-invariant spilled
value, `repairSSAForNewDef` inserts a PHI at loop header (bb.1) but rewrites all dominated
uses directly to the closer reload def. The PHI result becomes unused.

**Bug**: `fixPathologicalPHIs` unconditionally replaced the unused PHI with
`SI_SPILL_V32_RESTORE` at the loop header's first non-PHI position. That restore was also
dead but consumed a VGPR slot, pushing the loop's live count over budget → `color()` abort.

**Fix** (~line 1205 in `AMDGPUSSARegisterSpiller.cpp`): before inserting restore, check
`MRI->use_nodbg_empty(PHIDest)`. If true, delete PHI silently (no restore inserted), continue.

### Loop spill analysis findings

- `getNumCoveredRegs(LaneBitmask)`: AMDGPU-specific, counts 32-bit VGPR slots. sub0
  mask=0x3 → 1 slot (lo16=bit0, hi16=bit1 of one VGPR_32). Full vreg_64 mask=0xF → 2 slots.
- `adjustReloadForLoop`: checks if reload can be hoisted to loop preheader. "Cannot hoist
  reload to preheader: RP exceeds limit on path" → in-loop reload. In-loop reload does NOT
  reduce loop peak pressure (the restore adds back the slot it freed).
- Greedy spills loop-invariant values BEFORE the loop (buffer_store before entry, buffer_load
  inside loop). Our spiller places the virtual kill point (SI_VIRTUAL_SPILL_MARKER) near the
  def in bb.0 but actual reload stays in-loop when preheader hoist fails.
- Loop-filter fallback (`getVMPsToSpill` ~line 623): still open — "pick best invalid candidate
  and use loop exit sinking".

### Phase status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Full E2E test batch | COMMITTED (2026-06-18, 05fcd64) |
| Phase 1 | RebuildSSA → MachineLaneSSAUpdater | COMPLETE AND COMMITTED (2026-06-18) |
| Phase 2 | Function-wide width-descending RA coloring | NOT STARTED |

**Open work**: PHI coalescer, spiller tied-operand RP fix, loop-filter fallback (`getVMPsToSpill`
~line 623), reg-unit vs pressure-unit mismatch fix.

### Colleague-fix review campaign (2026-07-13, base HEAD b1f8539069e0, corpus CRASH 96)
- **Fix A (tied-def subreg color)**: `AMDGPUSSARegisterAllocator::color()` ~line 391 — a two-address
  def inheriting its tied use's color must inherit `TRI->getSubReg(color, UseSubIdx)` when the tied
  use reads a sub-register lane (V_WRITELANE_B32 / V_MOV_B32_dpp tied to one 32-bit lane of a wider
  value), not the whole super-register. Fixes the "Operand has incorrect register class" (10) cluster
  (7/8; permlane also needs Fix B = undef tied source). Reviewed: minimal + correct. APPLIED+built;
  cluster verify 7/8 pass.
- **Fix B (undef tied-def rewrite)**: `AMDGPUSSARegisterAllocator::rewriteOperands()` undef branch —
  an undef USE tied to a def (DPP/PERMLANE `undef %N.subX(tied-def)` old source) must be rewritten to
  the def's already-assigned physreg (`MO.setSubReg(0); MO.setReg(DefPhys)`), not an arbitrary
  `Order.front()`, else "Tied physical registers must match" / "Two-address operands must be
  identical". Fixes corpus class (1); with Fix A unblocks permlane. Reviewed: minimal + correct.
- **Fix C (spiller isSpill/isReload by TSFlag)**: `AMDGPUSSARegisterSpiller.cpp` `isSpillInstr`/
  `isReloadInstr` replaced hand-maintained S+V opcode lists (omitted AGPR/AV) with
  `SIInstrInfo::isSpill(MI->getDesc()) && mayStore()/mayLoad()`. On gfx90a+ an `SI_SPILL_AV*_RESTORE`
  reload was unrecognized → redef not renamed in SSA repair → vreg multi-defined → `getVRegDef`
  assert. TSFlag covers all files/widths. Fixes corpus class `getVRegDef assumes at most one
  definition`. Reviewed: correct + robustness improvement.
- **CORPUS A+B+C (2026-07-13, /tmp/corpus-abc-run, 3072 tests, ssara real-tree llc):** CRASH 96->86,
  0 PASS->fail regressions. Classes eliminated: incorrect-register-class 10->0 (A), tied-physregs 1->0
  (B), getVRegDef-multi-def 1->0 (C); bonus Multiple-vreg-defs 5->2 (C). Residual advanced into the
  postponed coalescer-lack class "Failed to find free physreg" 32->36. Top remaining crash class = (36)
  Failed to find free physreg = COALESCER-LACK (postpone; e.g. bitcast diamond, see report-D). Plan:
  green all non-coalescer classes, then build coalescer on a green tree.
- **Colleague-fix review campaign (2026-07-13): COMMITTED, CRASH 96 -> 59, 0 PASS->fail regressions.**
  7 fixes committed to `ssara` (each with a revert-proven SSARA guard test; corpus-gated per fix):
    * b312be01daa9 A - SSA RA inherit sub-register of tied use's color (ra-tied-use-subreg-color.ll)
    * 00bd2589097c B - SSA RA rewrite undef tied use to tied def physreg (ra-undef-tied-def-rewrite.ll)
    * 7d93452def3f F - SSA RA rewrite operands inside BUNDLEs (ra-bundle-operand-rewrite.ll)
    * 0521322a38e8 C - spiller classify spill/reload by Spill TSFlag (spill-av-reload-ssa-repair.ll)
    * 5c027bd3b1e4 D - spiller clear per-function stack-slot maps (spill-cross-function-stackslot.ll)
    * 733b6066a85e E - spiller ignore undef uses in physreg RP + getLiveRegs hasInterval-before-
      getRegKind (spill-undef-physreg-pressure.ll + spill-classless-vreg-liveregs.ll)
    * 9fef2ffac407 G - MachineLaneSSAUpdater share super-use REG_SEQUENCE per instruction, keyed
      {UseMI,OpMask}, session-scoped (rebuildssa-superuse-shared-regseq.ll)
  Class-by-class eliminated: incorrect-reg-class 10->0, tied-physregs 1->0, getVRegDef 1->0,
  Invalid-Object-Idx 9->0, Register-class-not-set 6->0, Remaining-virtual-register(GWS) 6->0,
  VOP-constant-bus 6->0, v_div_scale 4->0; Multiple-vreg-defs 5->2 (bonus from C).
  Campaign tally: 96(dead-def) -> 86(A+B+C) -> 81(D) -> 75(E) -> 69(F) -> 59(G). SSARA lit 65/65.
- **UPSTREAM (llvm-project worktree, 2026-07-13):** (1) branch `GCNRPTracker_fix` = the getLiveRegs
  hasInterval-before-getRegKind reorder ported to upstream GCNRegPressure.cpp (same bug exists in
  main); `ninja -C build/Debug check-llvm` = 46096 passed, only the 4 pre-existing MCJIT-EH failures
  (baseline match), 0 new regressions. (2) branch `fix-splitcriticaledge-subrange-vninfo` =
  MachineBasicBlock.cpp SplitCriticalEdge comment simplified per reviewer (perlfu): 4-line comment ->
  "// New segment VNI must be from the subrange.".
- **REMAINING crash classes @ CRASH 59 (postponed/deferred):** (37) Failed to find free physreg =
  COALESCER-LACK (full categorized list in /tmp/ssara-reports/failed-to-find-free-physreg-crashes.md:
  9 wide-bitcast diamonds, 10 AGPR/AV+MFMA, 9 spill-heavy/scavenge, 4 WWM, 5 other; see report-D for
  the diamond root cause). Non-coalescer remainders needing dedicated per-class work: undefined physreg
  (3: $scc-after-spill x2 + call-physreg x1), Multiple-vreg-defs (2: INLINEASM AV_32 subreg outputs -
  RebuildSSA detects 2 VNs, renames def op, but 2 defs persist), MachineCopyPropagation (2),
  containsInterval (2), + singletons. Plan: green all non-coalescer classes, then build coalescer.
  Colleague fix reports live in /tmp/ssara-reports/ (report-A..D + failed-to-find-free-physreg).
- **Fix D (spiller cross-function state leak, Invalid Object Idx)** [applied 2026-07-13]:
  `AMDGPUSSARegisterSpiller::runOnMachineFunction` now clears `Virt2StackSlotMap` and
  `StoredAtDefinition` per function. They are keyed by `VRegMaskPair` (per-function vreg numbers) but
  were never cleared, so a colliding {vreg,mask} in a later function returned a stale frame index
  (out of range for that function's FrameInfo -> getObjectAlign "Invalid Object Idx") and a dangling
  store MI. Fixes corpus class (9). Verified across all 9 repros.

## User Preferences
- No source changes without APPROVED: line
- User commits manually (no AI commits, no trailers)
- Patches shown as unified diffs
- Never update tests to match output — tests define expected behavior
- Always verify user claims independently
- Minimal code, no over-engineering
