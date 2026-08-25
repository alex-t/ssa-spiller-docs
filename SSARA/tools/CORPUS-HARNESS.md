# SSARA Corpus Harness — how to run it (all RUN lines)

The corpus is the real gate for SSARA changes (the lit suite is too narrow). This
document is the single source of truth for running it.

## Where the harness is

```
ssa-spiller-docs/SSARA/tools/harness_rescue.py    <- CANONICAL (git, branch `work`)
github/scripts/corpus/harness_rescue.py           <- working copy + archived runs
/tmp/harness_rescue.py                            <- scratch; DIES AT REBOOT
```

**This is the ONLY correct harness.** Take it from the canonical path; the `/tmp`
copy is a scratch working copy and must never be treated as the source of truth.

> The older `scripts/ssara_corpus_harness.py` was DELETED on 2026-08-25. It only
> ran the FIRST RUN line per file, so its numbers are not comparable with
> anything here. Historical worklogs still reference it; those are records of what
> was run at the time, not instructions. Do not resurrect it.

## The thing that trips people up: `--configs all` runs EVERY RUN line

A single `.ll` test file often has multiple `RUN:` lines (different `-mcpu`,
`-global-isel`, etc.). By default the harness runs **all** of them:

- `--configs all` (DEFAULT) — one record per ELIGIBLE RUN line. A file with N
  configs contributes N records keyed by `(test, config)`, e.g.
  `si-sgpr-spill.ll [tahiti]` and `si-sgpr-spill.ll [tonga]` are separate records.
- `--configs first` — only the first eligible RUN line per file (faster, but LOWER
  fidelity — this is the mode that "runs only the first RUN line"; do NOT use it
  when you want full coverage).

So: **to run all RUN lines, just use the default, or pass `--configs all` explicitly.**

## How to run

```bash
# Pin the binary FIRST: a full run takes ~50-90 min, and any ninja invocation in
# the meantime replaces or deletes bin/llc under the running harness.
cp /work/atimofee/sandbox/github/ssara-wt-widthaware/build/user-debug/bin/llc \
   /tmp/llc.<name>

python3 <canonical>/harness_rescue.py run \
  --llc /tmp/llc.<name> \
  --out /tmp/corpus-<name> \
  --configs all \
  --ssa-extra "-amdgpu-ssa-acl-coloring -amdgpu-ssa-agpr-rescue -amdgpu-ssa-region-rp -amdgpu-ssa-pre-spill-wa -amdgpu-ssa-phi-web-spill -amdgpu-ssa-agpr-first" \
  --jobs 16
```

**`-amdgpu-ssa-agpr-first` is REQUIRED.** It is present in every recorded
baseline (7351/7388 compiled records). Dropping it crashes AGPR-capable targets
with VGPR-file placement failures — `a-v-flat-atomicrmw.ll` and
`a-v-global-atomicrmw.ll` on gfx90a/gfx950, `vni8-across-blocks.ll` and
`buffer-fat-pointers-memcpy.ll` on gfx942 — which read as ~7 false regressions.
An earlier five-flag version of the example above silently invalidated a full
87-minute run (2026-08-25). `diff` now exits 2 on a flag-profile mismatch
instead of printing a meaningless comparison.

- **ALWAYS pass `--llc` explicitly.** The default `--llc` points at the PRIMARY
  `ssara` build (`/work/atimofee/sandbox/github/ssara/build/user-debug/bin/llc`),
  which no longer exists. To test a worktree's changes, point `--llc` at a pinned
  copy of THAT worktree's `build/user-debug/bin/llc`.
- **The binary must be fully built first** (`ninja -C build/user-debug llc` to
  completion — check `${PIPESTATUS[0]}`, not the piped tail). A half-linked llc
  makes EVERY test report "crash".
- `--ssa-extra "<flags>"` overrides the SSARA extra flags WHOLESALE (empty string =
  SSARA with no extras). Use the flag set above unless testing a specific subset.
  The module-level default in the script is STALE (three flags, incl.
  `-amdgpu-ssa-virgin-order`) — never rely on it.
- `--jobs 16` is a good default; 32 finishes a full run in ~50 min. Full run =
  ~3080 files → ~8250 (test×config) records. Each config uses that test's OWN RUN
  line for triple/mcpu/-global-isel — never hardcode those.
- Defaults: `--corpus` =
  `/work/atimofee/sandbox/github/ssara/llvm/test/CodeGen/AMDGPU`, `--timeout` 120s.

### Run it so it survives SSH disconnection

A full run outlives an SSH session, and an agent cannot hold it. Detach it:

```bash
screen -dmS corpus bash -c 'python3 <canonical>/harness_rescue.py run ... \
  > /tmp/corpus-<name>.log 2>&1'
screen -r corpus     # re-attach whenever
```

`setsid nohup ... < /dev/null > log 2>&1 &` works too. Verified on this box:
`KillUserProcesses=no` in `logind.conf`, so the login scope is abandoned rather
than killed and a detached job survives. Confirm with `ps -o pid,ppid,tty` —
`PPID=1` and `TTY=?` mean it is orphaned and terminal-free.

### Run a chosen subset (uses each test's own RUN lines)
```bash
python3 <canonical>/harness_rescue.py run --llc <llc> --out /tmp/sub \
  --tests preserve-wwm-copy-dst-reg.ll spill-agpr.ll --configs all
```
`--tests A B C` (paths rel to `--corpus` or absolute) or `-f <file>`. NEVER
hand-write a runner that hardcodes `-mcpu`/`-global-isel`/triple — that produces
artifact crashes.

## Output (under `--out`)

- `report.md` — buckets, crash classes, regression examples.
- `report.json` — bucket counts at top level, plus provenance under `"_run"`.
- `run.json` — provenance, written BEFORE the run starts so a run that dies half
  way still says what it was: llc path + sha256 + mtime, the resolved flag set,
  verifier state, configs mode, corpus, jobs, timeout, and the git HEAD/dirty of
  the tree it came from (`git_src` names which tree, since a pinned binary in
  `/tmp` has no repo of its own).
- `results.jsonl` — one row per `(test, config)`: `test`, `config`, `run`,
  `bucket`, `crash_sig`, `ssara_argv` (the exact llc command). This is the file to
  grep/parse.
- `failed.txt` — every crashing llc command, self-contained and copy-paste-runnable.

## Compare two runs (the apples-to-apples gate)

```bash
python3 <canonical>/harness_rescue.py diff --base /tmp/corpus-<old> --out /tmp/corpus-<new>
```

Reads each run's `results.jsonl`, keys CRASH records by `(test, config)`, prints
FIXED (in base, not new) / REGRESSED (in new, not base) / SIGNATURE-CHANGED (both
crash, different sig) / TIMEOUT->CRASH (already failing in base, NOT a regression)
+ a `NET: A -> B (+/-N)` line. Do NOT hand-roll `comm`/`sort` — format drift
garbles it.

**Flag-profile guard.** `diff` reconstructs each run's effective flag set from the
per-record `ssara_argv` and **exits 2** if any flag's presence rate differs by
more than 2% between the arms. This works on runs made before provenance existed,
because it reads the records rather than a recorded field. Override with
`--allow-flag-mismatch` only to inspect; the FIXED/REGRESSED accounting across a
mismatch is meaningless (the drift above produced 7 phantom regressions).

## Reference baselines (archived, no longer `/tmp`-only)

Under `github/scripts/corpus/runs/` — `results.jsonl`, `report.*`, `failed.txt`
and the run log for each. The `asm/` and `stderr/` subdirectories (~1.2 GB per
run) were NOT archived; they regenerate.

| run | date | crashes | note |
|---|---|---|---|
| `corpus-regr-fixed` | 2026-08-14 | 24 | the reference baseline; diff new runs against this |
| `corpus-splitacross` | 2026-08-24 | 15 | SelfSplit gate fix, `computeSplitAcross` form |
| `corpus-final-0825` | 2026-08-25 | 15 | same fix, `pickPeelableRun` form; 10 fixes, 0 regressions |
| `corpus-cur-0825` | 2026-08-25 | 20 | **INVALID** — five-flag drift; kept as the case study |

Pinned binaries (`/tmp/llc.*`) were NOT preserved: 2 GB each and rebuildable from
the commits. Rebuild rather than hunting for them.

## Gotchas

- `rm -rf` is shell-guard-blocked; ask the human to delete old `/tmp/corpus-*` dirs.
- Judge a change by the `diff` subcommand (net crash delta per (test,config)), not
  by eyeballing `report.md` counts — the denominator shifts with corpus size.
- Do NOT rebuild while a run is in flight unless the binary was pinned; ninja
  deletes `bin/llc` during relink and every remaining test reports "crash".
- `TIMEOUT` is load-sensitive and not reproducible run to run. A base `TIMEOUT`
  that becomes a `CRASH` was already failing — `diff` reports it separately.
- Verifier settings must match across arms. Both current baselines were recorded
  with `-verify-machineinstrs` on all 7388 compiled records.
