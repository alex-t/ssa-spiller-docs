#!/usr/bin/env python3
"""SSARA corpus harness.

Runs the llvm/test/CodeGen/AMDGPU corpus through the SSA register-allocation
stack (-amdgpu-ssa-regalloc) by reusing each test's own RUN line, compares
against the default Greedy allocator, and classifies the outcome.

No source files are modified. Output goes under --out (default:
<script_dir>/out/ssara-corpus/<timestamp>).

TODO(harness): the report dedups crash entries by .ll filename, which HIDES that
a single test file with multiple RUN configs / multiple functions can have
SEVERAL DISTINCT crashes (e.g. si-sgpr-spill.ll: fn `main` SGPR-perm-cycle vs fn
`main1` coloring colorfail). This masks fix/regression accounting: a fix to one
crash + an unchanged second crash in the same file shows as "no change". FIX:
key crash entries by (test, mcpu-config, function, crash-signature), not by .ll
name, so the diff between two runs is exact per-crash-site. Until then, when a
count looks flat but the class diff shows a fix, re-run the specific test
manually (per config) to see the real per-function picture.
"""
import argparse
import collections
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LLC = Path(
    "/work/atimofee/sandbox/github/ssara/build/user-debug/bin/llc"
)
DEFAULT_CORPUS = Path(
    "/work/atimofee/sandbox/github/ssara/llvm/test/CodeGen/AMDGPU"
)
SSA_FLAG = "-amdgpu-ssa-regalloc"
# SSARA extra flags appended after -amdgpu-ssa-regalloc. Default reproduces the
# historical config; override wholesale with --ssa-extra on the CLI (no sed, no
# edit/restore of this file). Set ONCE in cmd_run before the thread pool starts,
# then read-only during the run -> thread-safe.
SSA_EXTRA_FLAGS = [
    "-amdgpu-ssa-acl-coloring",
    "-amdgpu-ssa-agpr-rescue",
    "-amdgpu-ssa-virgin-order",
]
VERIFY_FLAG = "-verify-machineinstrs"

# Run-mode globals (set once in cmd_run before the thread pool; read-only during
# the run -> thread-safe). See the run-modes design in the module docstring.
CONFIG_MODE = "all"          # "all" (default) | "first" (one config per file)
CAPTURE_CRASHES = False      # on crash, re-run with DEBUG_FLAGS + save big log
DEBUG_FLAGS = ["-debug"]     # flags injected on the crash-capture re-run
# --forensic: inject -amdgpu-ssa-forensic-json=<per-tag path> into the SSARA run
# so each (test,config) writes its own forensic NDJSON, and retain Greedy output
# for colorfailing functions (incl. the crash path). OFF => byte-identical to the
# historical harness (no flag injected, no forensic dir, no crash-path Greedy).
FORENSIC_ENABLED = False
FORENSIC_FLAG = "-amdgpu-ssa-forensic-json"
# failed.txt lines (exact runnable commands) accumulated across the run; written
# at the end. Guarded by the driver's lock.
FAILED_CMDS = []

RUN_RE = re.compile(r"^\s*(?://|;|#|/\*)\s*RUN:\s*(.*?)\s*(?:\*/)?\s*$")
DISQUALIFY = (
    "-run-pass", "-start-after", "-start-before",
    "-stop-after", "-stop-before", "-passes=",
)
METRIC_RE = re.compile(
    r";\s*(TotalNumSgprs|NumSgprs|NumVgprs|ScratchSize|Occupancy)\s*:\s*(\d+)"
)
# Per-function resource directives, emitted for kernel and non-kernel funcs.
SET_RE = re.compile(
    r"^\s*\.set\s+([\w.$@]+)\.(num_vgpr|numbered_sgpr|private_seg_size),\s*"
    r"(\d+)"
)
SET_MAP = {"num_vgpr": "NumVgprs", "numbered_sgpr": "NumberedSgpr",
           "private_seg_size": "ScratchSize"}
LABEL_RE = re.compile(r"^([A-Za-z_][\w.$@]*):\s*(?:;.*)?$")


def sanit(rel):
    """Turn a relative test path into a flat filename token."""
    return rel.replace("/", "__")

# ----------------------------------------------------------------------------
# RUN-line extraction
# ----------------------------------------------------------------------------

def read_run_lines(path):
    lines, buf = [], ""
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return lines
    for raw in text.splitlines():
        m = RUN_RE.match(raw)
        if not m and not buf:
            continue
        piece = m.group(1) if m else raw.strip()
        if piece.endswith("\\"):
            buf += piece[:-1] + " "
            continue
        buf += piece
        lines.append(buf.strip())
        buf = ""
    return lines


def expand(tok, testpath, tmpbase):
    tok = tok.replace("%s", str(testpath))
    tok = tok.replace("%S", str(testpath.parent))
    tok = tok.replace("%t", tmpbase)
    return tok


def eligible_llc_cmd(run, testpath, tmpbase):
    """Return ((argv, input), None) for an eligible llc invocation, else
    (None, reason)."""
    if "|" in run:
        stages = [s.strip() for s in run.split("|")]
        llc_stages = [s for s in stages if re.search(r"(^|\s)(%?llc)\b", s)]
        upstream_tool = any(
            not re.search(r"(^|\s)(%?llc)\b", s) and "FileCheck" not in s
            and not s.startswith("cat ") for s in stages
        )
        if upstream_tool and not (
            len(llc_stages) == 1 and stages[0].startswith("cat ")
        ):
            return None, "SKIP_PIPELINE"
        run = llc_stages[0] if llc_stages else run
    if not re.search(r"(^|\s)(%?llc)\b", run):
        return None, "SKIP_NO_LLC"
    # Truncate at a shell command separator so a chained command (e.g.
    # `llc ... && llvm-readobj ...` or `llc ...; foo`) does not leak its tail as
    # bogus positional args to llc. Take only the llc command (up to && / ; / |
    # already handled above). Split on the FIRST '&&' or unquoted ';'.
    run = re.split(r"\s&&\s|\s;\s", run)[0]
    # Strip redirections (both attached `2>foo` and spaced `2> foo`, and stdout
    # `>foo` / `> foo`) and normalize stdin '<': bash treats these as
    # metacharacters, shlex does not.
    run = re.sub(r"2>&1", " ", run)
    run = re.sub(r"2>\s*\S+", " ", run)   # 2>foo and 2> foo
    run = re.sub(r"&>\s*\S+", " ", run)
    run = re.sub(r"(^|\s)>\s*\S+", " ", run)  # stdout redirect >foo / > foo
    run = run.replace("<", " < ")
    try:
        toks = shlex.split(run)
    except ValueError:
        return None, "SKIP_UNPARSEABLE"
    if toks and toks[0] == "not":
        return None, "SKIP_EXPECTED_FAIL"
    i = next((k for k, t in enumerate(toks) if t in ("llc", "%llc")), None)
    if i is None:
        return None, "SKIP_NO_LLC"
    toks = toks[i + 1:]
    argv, inp, skip_next = [], None, False
    for j, t in enumerate(toks):
        if skip_next:
            skip_next = False
            continue
        if t == "<":
            continue
        if j > 0 and toks[j - 1] == "<":
            inp = t
            continue
        if t == "-":  # lone stdin marker; input supplied explicitly below
            continue
        if t == "-o":
            skip_next = True
            continue
        if t.startswith("-o=") or t.startswith("-o/") or (
            t.startswith("-o") and len(t) > 2 and not t.startswith("-opt")
            and not t.startswith("-only")
        ):
            continue
        if t.startswith("-filetype"):
            continue
        argv.append(t)
    argv = [expand(t, testpath, tmpbase) for t in argv]
    if inp:
        inp = expand(inp, testpath, tmpbase)
    if inp is None:
        pos = [a for a in argv if not a.startswith("-")
               and (a.endswith(".ll") or a.endswith(".mir")
                    or a == str(testpath))]
        inp = pos[0] if pos else str(testpath)
        argv = [a for a in argv if a != inp]
    if inp != str(testpath) and not Path(inp).exists():
        # e.g. %t.bc produced by a prior `opt` RUN line we do not replay
        return None, "SKIP_GENERATED_INPUT"
    # A leftover NON-flag positional in argv is a second input llc cannot take
    # (it becomes "Too many positional arguments"). This happens when the RUN
    # line's llc input is a generated artifact (e.g. `llc %t.bc`, produced by a
    # prior `opt`/`llvm-as` step we do not replay): %t.bc doesn't match the
    # .ll/.mir/testpath filter above, so it stays in argv while inp falls back to
    # the .ll via stdin -> two inputs. Skip these — they are unrunnable without
    # the omitted pre-step, NOT SSARA crashes.
    stray = [a for a in argv
             if not a.startswith("-") and a != inp and a != str(testpath)]
    if stray:
        return None, "SKIP_GENERATED_INPUT"
    joined = " ".join(argv)
    if "-O0" in argv:
        return None, "SKIP_O0"
    if any(d in joined for d in DISQUALIFY):
        return None, "SKIP_NOT_FULL_PIPELINE"
    if "-regalloc=" in joined or "-regalloc" in argv:
        return None, "SKIP_CUSTOM_REGALLOC"
    if "r600" in joined:
        return None, "SKIP_R600"
    if not re.search(r"(amdgcn|gfx\d|-mcpu=gfx)", joined):
        try:
            if "amdgcn" not in testpath.read_text(errors="replace"):
                return None, "SKIP_NO_AMDGCN_TARGET"
        except Exception:
            return None, "SKIP_NO_AMDGCN_TARGET"
    return (argv, inp), None

# ----------------------------------------------------------------------------
# Running / classification
# ----------------------------------------------------------------------------

def build_argv(llc, base_argv, inp, ssara, verify, forensic_path=None):
    a = [str(llc)] + list(base_argv)
    # Respect an explicit setting from the RUN line. A test that says
    # -verify-machineinstrs=0 does so because it trips a pre-existing verifier
    # failure in the baseline allocator too; appending the bare flag after it
    # wins on the command line and turns that into a phantom CRASH record.
    if verify and not any(x == VERIFY_FLAG or x.startswith(VERIFY_FLAG + "=")
                          for x in a):
        a.append(VERIFY_FLAG)
    if ssara and SSA_FLAG not in a:
        a.append(SSA_FLAG)
        for f in SSA_EXTRA_FLAGS:
            if f not in a:
                a.append(f)
    # Forensic NDJSON path (only when --forensic requested). Appended before -o
    # so llc writes a per-(test,config) file; its parent dir is created by the
    # caller before llc runs. OFF => this branch is skipped -> argv unchanged.
    if ssara and forensic_path is not None:
        a.append(f"{FORENSIC_FLAG}={forensic_path}")
    a += ["-o", "-", inp]
    return a


def run_llc(argv, timeout):
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr, False
    except subprocess.TimeoutExpired:
        return None, "", "", True
    except Exception as e:  # noqa: BLE001
        return -999, "", f"harness-exec-error: {e}", False


def crash_signature(stderr):
    t = stderr or ""
    m = re.search(r"Assertion [`']([^'\n]+)' failed", t)
    if m:
        sig = m.group(1)
    elif "UNREACHABLE executed" in t:
        m = re.search(r"UNREACHABLE executed[^\n]*", t)
        sig = m.group(0)
    elif "Bad machine code" in t:
        m = re.search(r"\*\*\* Bad machine code: ([^\n]+)", t)
        sig = "MachineVerifier: " + (m.group(1) if m else "?")
    elif "without a def" in t.lower() or \
         "reading virtual register" in t.lower():
        sig = "reading virtual register without a def"
    elif "LLVM ERROR:" in t:
        m = re.search(r"LLVM ERROR: ([^\n]+)", t)
        sig = "LLVM ERROR: " + (m.group(1) if m else "?")
    elif "Segmentation fault" in t or "SIGSEGV" in t:
        sig = "SIGSEGV"
    else:
        firstlines = [ln for ln in t.splitlines() if ln.strip()]
        sig = firstlines[0] if firstlines else "unknown-nonzero-exit"
    # Strip a leading "<toolname>: " prefix (e.g. "llc:" or a frozen-copy name
    # like "llc.frozen-webspillfix:") so the SAME error does not get two
    # signatures just because the binary was renamed for a run.
    sig = re.sub(r"^\S+?:\s*", "", sig)
    sig = re.sub(r"/\S+/", "", sig)
    sig = re.sub(r"%\d+", "%N", sig)
    sig = re.sub(r"\b0x[0-9a-fA-F]+\b", "0xADDR", sig)
    sig = re.sub(r"\b\d+\b", "N", sig)
    sig = re.sub(r"\s+", " ", sig).strip()
    return sig[:200]


def parse_metrics(asm):
    funcs, cur = {}, None
    for ln in asm.splitlines():
        sm = SET_RE.match(ln)
        if sm:
            funcs.setdefault(sm.group(1), {})[SET_MAP[sm.group(2)]] = \
                int(sm.group(3))
            continue
        lm = LABEL_RE.match(ln)
        if lm:
            cur = lm.group(1)
            continue
        mm = METRIC_RE.search(ln)
        if mm and cur is not None:
            funcs.setdefault(cur, {})[mm.group(1)] = int(mm.group(2))
    # keep functions that carry at least a vgpr/sgpr resource figure
    return {k: v for k, v in funcs.items()
            if {"NumVgprs", "TotalNumSgprs", "NumberedSgpr"} & set(v)}


def sgpr(d):
    return d.get("TotalNumSgprs", d.get("NumSgprs", d.get("NumberedSgpr", 0)))


def classify_alloc(ssara_asm, greedy_asm):
    a, g = parse_metrics(ssara_asm), parse_metrics(greedy_asm)
    common = sorted(set(a) & set(g))
    detail = {"kernels": {}, "unmatched_ssara": sorted(set(a) - set(g)),
              "unmatched_greedy": sorted(set(g) - set(a))}
    if not common:
        return "NO_METRICS", detail
    worse_occ = new_spill = worse_regs = better = False
    for k in common:
        ak, gk = a[k], g[k]
        docc = ak.get("Occupancy", 0) - gk.get("Occupancy", 0)
        dscr = ak.get("ScratchSize", 0) - gk.get("ScratchSize", 0)
        dv = ak.get("NumVgprs", 0) - gk.get("NumVgprs", 0)
        ds = sgpr(ak) - sgpr(gk)
        detail["kernels"][k] = {"dOcc": docc, "dScratch": dscr,
                                "dVgpr": dv, "dSgpr": ds}
        if docc < 0:
            worse_occ = True
        if dscr > 0:
            new_spill = True
        if dv > 0 or ds > 0:
            worse_regs = True
        if docc > 0 or dscr < 0 or dv < 0 or ds < 0:
            better = True
    if worse_occ or new_spill:
        return "REGRESSION_OCC_OR_SPILL", detail
    if worse_regs and better:
        return "MIXED", detail
    if worse_regs:
        return "DIFF_COALESCING", detail
    if better:
        return "OK_BETTER", detail
    return "OK_EQUAL", detail


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", errors="replace")


TIERPROOF_RE = re.compile(
    r"\[TIERPROOF\] (\w+) (\w+) w(\d+) rank=(\d+) pool=(\d+) "
    r"vregs=(\d+) virgin=(\d+) gap=(\d+) fail=(\d+)\s+(\S+)")

def parse_tierproof(se):
    """Aggregate per-tier TIERPROOF verdicts from stderr into counts + the
    per-test Hack-allocatability class."""
    verd = {"HACK-OK":0,"GAP-RESCUED":0,"COLORER-FAULT":0,"SPILLER-UNDERSPILL":0}
    tiers = 0
    any_gap = any_fail = any_underspill = False
    for m in TIERPROOF_RE.finditer(se or ""):
        v = m.group(10); tiers += 1
        verd[v] = verd.get(v,0)+1
        gap=int(m.group(8)); fail=int(m.group(9))
        rank=int(m.group(4)); pool=int(m.group(5))
        if gap>0: any_gap=True
        if fail>0:
            any_fail=True
            if rank>pool: any_underspill=True
    return verd, tiers, any_gap, any_fail, any_underspill


def forensic_has_colorfail(path):
    """True iff the per-(test,config) forensic JSON at `path` records an
    'attempt-failed' event. The C++ reporter emits one JSON object per function
    (events nested under an "events" array), so we test for the exact quoted
    event-kind token rather than parsing — this is tolerant of both a single
    object and an NDJSON stream, and of a partially-flushed trailing object from
    a crashing run. A missing/empty/unreadable file yields False rather than
    raising (a clean function the reporter chose not to write)."""
    try:
        text = Path(path).read_text(errors="replace")
    except Exception:
        return False
    # '"attempt-failed"' is the distinctive event-kind literal; it does not
    # collide with '"attempt-completed"'/'"attempt-started"'.
    return '"attempt-failed"' in text


def _mcpu_of(base_argv):
    """Short config label from an argv, e.g. 'gfx908' or 'gfx908+gisel'."""
    mcpu = "?"
    gisel = False
    for a in base_argv:
        if a.startswith("-mcpu="):
            mcpu = a.split("=", 1)[1]
        elif a.startswith("mcpu="):
            mcpu = a.split("=", 1)[1]
        elif a in ("-global-isel", "-global-isel=1"):
            gisel = True
    return mcpu + ("+gisel" if gisel else "")


def process(test, corpus, out, llc, timeout, verify):
    """Return a LIST of records, one per ELIGIBLE RUN line (full fidelity: a file
    with N configs contributes N records keyed by (test, config))."""
    rel = str(test.relative_to(corpus))
    tag0 = sanit(rel)
    tmpbase = str(out / "tmp" / tag0)
    (out / "tmp").mkdir(parents=True, exist_ok=True)

    # Collect all ELIGIBLE RUN lines (not just the first). Keep skip reasons only
    # if NONE is eligible, so a file with zero SSARA-eligible configs still emits
    # one SKIP record.
    eligible = []
    last_skip = None
    for run in read_run_lines(test):
        cmd, reason = eligible_llc_cmd(run, test, tmpbase)
        if cmd:
            eligible.append((run, cmd))
        else:
            last_skip = reason
    if not eligible:
        return [{"test": rel, "bucket": last_skip or "SKIP_NO_LLC"}]

    # Config selection: "all" (default, full fidelity) runs every eligible RUN
    # line; "first" restores the old one-config-per-file behavior (comparable /
    # faster). Set by --configs.
    if CONFIG_MODE == "first":
        eligible = eligible[:1]

    recs = []
    for idx, (run, cmd) in enumerate(eligible):
        base_argv, inp = cmd
        cfg = _mcpu_of(base_argv)
        # Per-config tag so saved asm/stderr from different configs don't collide.
        tag = f"{tag0}__cfg{idx}_{sanit(cfg)}"
        recs.append(process_one(rel, cfg, run, base_argv, inp, tag, out, llc,
                                timeout, verify))
    return recs


def _runnable_cmd(sargv, inp):
    """A single copy-paste-runnable shell command string: llc ... < input.
    (build_argv already appended the input positionally; render it as a stdin
    redirect so the line runs as-is and matches how RUN lines feed llc.)"""
    argv = [a for a in sargv if a != inp]
    return " ".join(shlex.quote(a) for a in argv) + " < " + shlex.quote(inp)


def crash_folder(out, tag):
    return out / "crashlogs" / tag


def process_one(rel, cfg, run, base_argv, inp, tag, out, llc, timeout, verify):
    rec = {"test": rel, "config": cfg, "run": run}
    # Per-(test,config) forensic NDJSON path, only when --forensic is set. Create
    # the parent dir BEFORE llc runs (mirrors save()); the same `tag` used for
    # asm/stderr keeps configs from clobbering each other. OFF => forensic_path
    # stays None -> build_argv adds no flag -> behavior byte-identical to today.
    forensic_path = None
    if FORENSIC_ENABLED:
        fp = out / "forensic" / (tag + ".forensic.json")
        fp.parent.mkdir(parents=True, exist_ok=True)
        forensic_path = fp
        rec["forensic_json"] = str(fp)
    sargv = build_argv(llc, base_argv, inp, True, verify, forensic_path)
    rec["ssara_argv"] = " ".join(shlex.quote(x) for x in sargv)
    cmdline = _runnable_cmd(sargv, inp)
    cfolder = crash_folder(out, tag)
    rc, so, se, to = run_llc(sargv, timeout)
    if to:
        rec["bucket"] = "TIMEOUT"
        return rec
    if rc != 0:
        rec["bucket"] = "CRASH"
        rec["crash_sig"] = crash_signature(se)
        rec["ssara_exit"] = rc
        rec["failed_cmd"] = cmdline  # exact runnable line -> failed.txt
        verd, tiers, any_gap, any_fail, any_under = parse_tierproof(se)
        rec["tierproof"] = verd; rec["tiers"] = tiers
        save(out / "stderr" / (tag + ".ssara.err"), se)
        # --capture-crashes: re-run with DEBUG_FLAGS, save the (big) log to a
        # per-crash folder for diagnostics.
        if CAPTURE_CRASHES:
            dbgv = list(sargv) + DEBUG_FLAGS
            _, dso, dse, dto = run_llc(dbgv, timeout)
            cfolder.mkdir(parents=True, exist_ok=True)
            save(cfolder / "cmd.sh", cmdline + "\n")
            save(cfolder / "debug.err", dse or "")
            save(cfolder / "crash.err", se)
        # --forensic: on the CRASH path Greedy does NOT normally run, so a
        # colorfailing-then-crashing function has no paired Greedy result. When
        # the forensic JSON shows a colorfail, run Greedy now and retain its asm
        # (or stderr if Greedy also fails) so the analyst can derive the spilled
        # set + cost bar offline. OFF => this whole block is skipped.
        if FORENSIC_ENABLED and forensic_has_colorfail(forensic_path):
            rec["colorfail"] = True
            gargv = build_argv(llc, base_argv, inp, False, verify)
            grc, go, ge, gto = run_llc(gargv, timeout)
            if gto or grc != 0:
                rec["greedy_exit"] = "timeout" if gto else grc
                save(out / "stderr" / (tag + ".greedy.err"), ge)
                rec["greedy_saved"] = False
            else:
                save(out / "asm" / (tag + ".greedy.s"), go)
                rec["greedy_saved"] = True
        return rec
    # PASS: shed any stale crash folder for this (test,config) — unconditional,
    # so crashlogs/ always reflects the current failing set.
    if cfolder.exists():
        shutil.rmtree(cfolder, ignore_errors=True)
    save(out / "asm" / (tag + ".ssara.s"), so)
    verd, tiers, any_gap, any_fail, any_under = parse_tierproof(se)
    rec["tierproof"] = verd; rec["tiers"] = tiers
    # Hack-allocatability class for a PASSING test:
    #   pure-hack        : every tier HACK-OK, no gap, no late spill
    #   linear-scan      : some tier needed gap-scan but NO late spill (fail==0)
    #   late-spill       : some tier needed a late width-1 spill (fail>0) yet the
    #                      function still completed (recovered)
    if any_fail: rec["hack_class"] = "late-spill-recovered"
    elif any_gap: rec["hack_class"] = "linear-scan-recovered"
    else: rec["hack_class"] = "pure-hack"
    # --forensic: note whether SSARA colorfailed-but-recovered on this PASS. The
    # Greedy .greedy.s below is already saved unconditionally, so a recovered
    # colorfail is paired for free; this key just makes it queryable offline.
    if FORENSIC_ENABLED and forensic_has_colorfail(forensic_path):
        rec["colorfail"] = True
    gargv = build_argv(llc, base_argv, inp, False, verify)
    grc, go, ge, gto = run_llc(gargv, timeout)
    if gto or grc != 0:
        rec["bucket"] = "PREEXISTING_FAIL"
        rec["greedy_exit"] = "timeout" if gto else grc
        save(out / "stderr" / (tag + ".greedy.err"), ge)
        return rec
    save(out / "asm" / (tag + ".greedy.s"), go)
    if FORENSIC_ENABLED:
        rec["greedy_saved"] = True
    bucket, detail = classify_alloc(so, go)
    rec["bucket"] = bucket
    rec["alloc"] = detail
    return rec

# ----------------------------------------------------------------------------
# Driver + report
# ----------------------------------------------------------------------------

def discover(corpus, include_mir, glob):
    if glob:
        return sorted(corpus.glob(glob))
    seen = sorted(corpus.glob("**/*.ll"))
    if include_mir:
        seen += sorted(corpus.glob("**/*.mir"))
    return seen


def rerun_failed(src, out, timeout, jobs):
    """VERBATIM replay of a prior failed.txt (control gate after a rebuild-in-place
    fix). Each non-empty line is a complete shell command (llc ... < input); run it
    as-is via the shell, collect which still crash, rewrite failed.txt with the
    survivors. No RUN-line parsing, no flag injection, no Greedy."""
    if src.is_dir():
        src = src / "failed.txt"
    cmds = [ln.strip() for ln in src.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    out.mkdir(parents=True, exist_ok=True)
    print(f"[harness] rerun-failed: {len(cmds)} commands from {src}", flush=True)
    lock = threading.Lock()
    still, done = [], [0]

    def one(cmd):
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               timeout=timeout)
            crashed = p.returncode != 0
        except subprocess.TimeoutExpired:
            crashed = True
        with lock:
            if crashed:
                still.append(cmd)
            done[0] += 1
            print(f"  {done[0]}/{len(cmds)}  "
                  f"{'CRASH' if crashed else 'ok   '}  {cmd[:90]}", flush=True)

    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        list(ex.map(one, cmds))
    (out / "failed.txt").write_text("\n".join(sorted(still)) +
                                    ("\n" if still else ""))
    fixed = len(cmds) - len(still)
    print(f"[harness] rerun-failed done: {len(still)} still crash, {fixed} fixed "
          f"-> {out}/failed.txt", flush=True)


def cmd_run(args):
    global SSA_EXTRA_FLAGS, CONFIG_MODE, CAPTURE_CRASHES, DEBUG_FLAGS
    global FORENSIC_ENABLED
    llc = Path(args.llc)
    if not llc.exists():
        sys.exit(f"llc not found: {llc}")
    corpus = Path(args.corpus)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # --rerun-failed: pure VERBATIM replay of a prior failed.txt (control gate for
    # a rebuilt-in-place fix). Each line is a complete command; run it as-is, keep
    # the ones that still crash. No RUN-line parsing, no flags, no Greedy.
    if args.rerun_failed:
        rerun_failed(Path(args.rerun_failed), out, args.timeout, args.jobs)
        return

    # Config file (JSON): defaults that CLI overrides. Keys: debug_flags (list or
    # str), capture_crashes (bool), configs ("all"|"first"), tests (list),
    # tests_file (path), ssa_extra (str).
    cfg = {}
    if args.config:
        cfg = json.loads(Path(args.config).read_text())
    def pick(cli, key, default):
        return cli if cli is not None else cfg.get(key, default)

    ssa_extra = pick(args.ssa_extra, "ssa_extra", None)
    if ssa_extra is not None:
        SSA_EXTRA_FLAGS = shlex.split(ssa_extra)
    CONFIG_MODE = pick(args.configs, "configs", "all")
    CAPTURE_CRASHES = bool(pick(True if args.capture_crashes else None,
                                "capture_crashes", False))
    dbg = pick(args.debug_flags, "debug_flags", None)
    if dbg is not None:
        DEBUG_FLAGS = shlex.split(dbg) if isinstance(dbg, str) else list(dbg)
    FORENSIC_ENABLED = bool(pick(True if args.forensic else None,
                                 "forensic", False))

    # Assemble the test list: CLI --tests / -f override the config file's tests.
    test_names = list(args.tests or [])
    tfile = args.tests_file or cfg.get("tests_file")
    if tfile:
        test_names += [ln.strip() for ln in Path(tfile).read_text().splitlines()
                       if ln.strip() and not ln.startswith("#")]
    if not test_names:
        test_names = list(cfg.get("tests", []))

    if test_names:
        # Explicit test list: each entry is a path relative to the corpus (or
        # absolute). Uses the SAME per-test RUN-line extraction as a full run, so
        # triple/mcpu/-global-isel come from the test itself -> no harness-forced
        # target artifacts.
        tests = []
        for name in test_names:
            p = Path(name)
            if not p.is_absolute():
                p = corpus / name
            if not p.exists():
                sys.exit(f"test entry not found: {p}")
            tests.append(p)
    else:
        tests = discover(corpus, args.include_mir, args.glob)
    if args.limit:
        tests = tests[:args.limit]
    print(f"[harness] {len(tests)} tests, jobs={args.jobs}, "
          f"timeout={args.timeout}s, ssa_extra={SSA_EXTRA_FLAGS} -> {out}",
          flush=True)
    # Provenance BEFORE the pool starts, so a run that dies half way still says
    # what it was. Folded into report.json by write_report().
    prov = _write_provenance(out, llc, corpus, tests, args)
    print(f"[harness] llc={prov['llc']} sha={prov['llc_sha256'][:12]} "
          f"head={prov['git_head'][:12]}{'+dirty' if prov['git_dirty'] else ''}",
          flush=True)
    results_path = out / "results.jsonl"
    lock = threading.Lock()
    done = [0]
    t0 = time.time()
    with results_path.open("w") as rf:
        def work(t):
            try:
                rs = process(t, corpus, out, llc, args.timeout,
                             not args.no_verify)
            except Exception as e:  # noqa: BLE001
                rs = [{"test": str(t.relative_to(corpus)),
                       "bucket": "HARNESS_ERROR", "error": repr(e)}]
            with lock:
                for r in rs:  # process() returns one record PER config
                    rf.write(json.dumps(r) + "\n")
                    if r.get("failed_cmd"):
                        FAILED_CMDS.append(r["failed_cmd"])
                rf.flush()
                done[0] += 1
                if done[0] % 50 == 0 or done[0] == len(tests):
                    dt = time.time() - t0
                    print(f"  {done[0]}/{len(tests)}  ({dt:.0f}s)", flush=True)
            return rs
        with cf.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            list(ex.map(work, tests))
    # failed.txt: the single source of truth — exact copy-paste-runnable commands
    # that crashed, written EVERY run. Humans paste a line; --rerun-failed executes
    # each line verbatim.
    (out / "failed.txt").write_text("\n".join(sorted(FAILED_CMDS)) +
                                    ("\n" if FAILED_CMDS else ""))
    write_report(out, args.examples)
    print(f"[harness] done -> {out}/report.md  ({len(FAILED_CMDS)} failed -> "
          f"{out}/failed.txt)", flush=True)


def _write_provenance(out, llc, corpus, tests, args):
    """Record exactly what produced this run: binary identity, the resolved SSARA
    flag set, verifier state, corpus and concurrency. Exists because a run whose
    flag set silently differs from its baseline is worthless, and nothing in the
    output used to say which flags were used."""
    st = Path(llc).stat()
    h = hashlib.sha256()
    with open(llc, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)

    def git_at(where, *a):
        try:
            return subprocess.run(("git", "-C", str(where)) + a,
                                  capture_output=True, text=True,
                                  timeout=15).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    # The recommended flow pins llc to a copy under /tmp so a rebuild cannot
    # swap the binary mid-run, which means the binary's own directory is usually
    # NOT a repo. Fall back to the invoking cwd, and record which tree the
    # revision came from so it can never be misread as the wrong worktree.
    git_src = ""
    for cand in (Path(llc).resolve().parent, Path.cwd()):
        if git_at(cand, "rev-parse", "--git-dir"):
            git_src = git_at(cand, "rev-parse", "--show-toplevel") or str(cand)
            break
    prov = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "llc": str(llc),
        "llc_sha256": h.hexdigest(),
        "llc_size": st.st_size,
        "llc_mtime": time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.localtime(st.st_mtime)),
        "ssa_flag": SSA_FLAG,
        "ssa_extra": list(SSA_EXTRA_FLAGS),
        "verify_machineinstrs": not args.no_verify,
        "configs": CONFIG_MODE,
        "forensic": FORENSIC_ENABLED,
        "corpus": str(corpus),
        "n_tests": len(tests),
        "jobs": args.jobs,
        "timeout": args.timeout,
        "git_src": git_src,
        "git_head": git_at(git_src, "rev-parse", "HEAD") if git_src else "",
        "git_dirty": bool(git_at(git_src, "status", "--porcelain")) if git_src
                     else False,
    }
    (Path(out) / "run.json").write_text(json.dumps(prov, indent=2))
    return prov


def write_report(out, n_examples=5):
    recs = [json.loads(l) for l in (out / "results.jsonl").read_text()
            .splitlines() if l.strip()]
    buckets, crash = {}, {}
    # A record is now one (test, config) pair. Label crashes by "test [config]"
    # so distinct crashes in the same .ll under different RUN configs are visible.
    def label(r):
        c = r.get("config")
        return f"{r['test']} [{c}]" if c else r["test"]
    for r in recs:
        b = r.get("bucket", "UNKNOWN")
        buckets.setdefault(b, []).append(r)
        if b == "CRASH":
            crash.setdefault(r.get("crash_sig", "?"), []).append(label(r))
    n_files = len({r["test"] for r in recs})
    lines = [f"# SSARA corpus report ({out.name})", "",
             f"Records (test x config): {len(recs)} over {n_files} files",
             "", "## Buckets", ""]
    for b in sorted(buckets, key=lambda x: -len(buckets[x])):
        lines.append(f"- **{b}**: {len(buckets[b])}")
    lines += ["", "## Crash classes", ""]
    for sig in sorted(crash, key=lambda x: -len(crash[x])):
        lines.append(f"### ({len(crash[sig])}) {sig}")
        for ex in sorted(crash[sig])[:n_examples]:
            lines.append(f"  - {ex}")
        lines.append("")
    for b in ("REGRESSION_OCC_OR_SPILL", "MIXED", "DIFF_COALESCING",
              "OK_BETTER", "PREEXISTING_FAIL", "TIMEOUT", "HARNESS_ERROR",
              "NO_METRICS"):
        rs = buckets.get(b, [])
        if not rs:
            continue
        lines += [f"## {b} (examples)", ""]
        for r in rs[:n_examples]:
            extra = json.dumps(r.get("alloc", {}).get("kernels", {}))
            lines.append(f"- {label(r)} {extra}")
        lines.append("")
    (out / "report.md").write_text("\n".join(lines))
    # Bucket counts stay top-level (existing readers depend on that shape); the
    # run's provenance rides along under "_run", which cannot collide with a
    # bucket name.
    rep = {b: len(v) for b, v in buckets.items()}
    prov = out / "run.json"
    if prov.exists():
        rep["_run"] = json.loads(prov.read_text())
    (out / "report.json").write_text(json.dumps(rep, indent=2))


def _crash_map(out):
    """(test, config) -> crash_sig for every CRASH record in a run dir's
    results.jsonl. Machine truth — no markdown parsing."""
    m = {}
    for l in (Path(out) / "results.jsonl").read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("bucket") == "CRASH":
            m[(r["test"], r.get("config", ""))] = r.get("crash_sig", "?")
    return m


def _timeout_set(out):
    """(test, config) keys that TIMED OUT in a run dir. A test that was a TIMEOUT
    and later CRASHES was ALREADY failing — it must NOT be counted as a fresh
    regression (a hang becoming a fast crash is not a new failure)."""
    s = set()
    for l in (Path(out) / "results.jsonl").read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("bucket") == "TIMEOUT":
            s.add((r["test"], r.get("config", "")))
    return s


# Flags whose presence changes allocation outcomes, hence comparability.
_PROFILE_FLAG_RE = re.compile(r"^-(amdgpu-ssa[\w-]*|verify-machineinstrs)$")


def _flag_profile(out):
    """Effective flag profile of a finished run, reconstructed from each record's
    ssara_argv rather than from run.json — so it also works on runs made before
    provenance was recorded (every run predating this change).
    Returns (n_compiled_records, flag -> count, binary -> count)."""
    n = 0
    flags = collections.Counter()
    binaries = collections.Counter()
    for l in (Path(out) / "results.jsonl").read_text().splitlines():
        if not l.strip():
            continue
        argv = json.loads(l).get("ssara_argv") or ""
        argv = argv.split() if isinstance(argv, str) else list(argv)
        if not argv:
            continue
        n += 1
        binaries[argv[0]] += 1
        for a in argv[1:]:
            a = a.split("=", 1)[0]
            if _PROFILE_FLAG_RE.match(a):
                flags[a] += 1
    return n, flags, binaries


def _flag_mismatch(base, new, tol=0.02):
    """Flags whose presence RATE differs between two runs by more than tol.
    A rate rather than a raw count because a few configs legitimately drop flags,
    and the arms need not have identical record counts; tol=2% still catches the
    case that matters (a flag on in one arm, off in the other)."""
    nA, fA, binA = _flag_profile(base)
    nB, fB, binB = _flag_profile(new)
    rows = []
    if nA and nB:
        for f in sorted(set(fA) | set(fB)):
            rA, rB = fA[f] / nA, fB[f] / nB
            if abs(rA - rB) > tol:
                rows.append((f, fA[f], nA, rA, fB[f], nB, rB))
    return rows, (nA, binA), (nB, binB)


def cmd_diff(args):
    """Compare two run dirs by (test,config): FIXED (crashed in A, not in B),
    REGRESSED (crashes in B, not in A), SIG-CHANGED (crashes in both, different
    signature). Reads results.jsonl directly — the reliable comparison that
    replaces hand-rolled `comm` over rendered reports (which broke on format
    drift). A = --base (old), B = --out (new)."""
    rows, (nA_rec, binA), (nB_rec, binB) = _flag_mismatch(args.base, args.out)
    if rows:
        print("*** FLAG MISMATCH: these two runs are NOT comparable ***")
        print(f"base={args.base}  ({nA_rec} compiled records)")
        print(f"new ={args.out}  ({nB_rec} compiled records)")
        for f, ca, na, ra, cb, nb, rb in rows:
            print(f"  {f}: base {ca}/{na} ({ra:.0%})   new {cb}/{nb} ({rb:.0%})")
        print("\nOne differing -amdgpu-ssa-* flag changes which tests crash, so the\n"
              "FIXED / REGRESSED accounting below would be meaningless. Re-run the\n"
              "new arm with the base's flag set, or pass --allow-flag-mismatch.")
        if not args.allow_flag_mismatch:
            sys.exit(2)
        print("\n--allow-flag-mismatch given: proceeding anyway.\n")
    A = _crash_map(args.base)
    B = _crash_map(args.out)
    ATimeout = _timeout_set(args.base)
    BTimeout = _timeout_set(args.out)
    fixed = sorted(k for k in A if k not in B)
    # A key that crashes in B but not in A is only a REAL regression if it was
    # NOT already failing (timing out) in A. TIMEOUT->CRASH is a signature change
    # of an already-broken test, reported separately so it never inflates the
    # regression count.
    regressed = sorted(k for k in B if k not in A and k not in ATimeout)
    was_timeout = sorted(k for k in B if k not in A and k in ATimeout)
    changed = sorted(k for k in A if k in B and A[k] != B[k])
    # FIXED that merely became a TIMEOUT is not truly fixed — still failing.
    fixed_real = [k for k in fixed if k not in BTimeout]
    fixed_to_timeout = [k for k in fixed if k in BTimeout]
    def fmt(k):
        return f"{k[0]} [{k[1]}]" if k[1] else k[0]
    print(f"base={args.base}  ({len(A)} crashes)"
          + (f"  llc={binA.most_common(1)[0][0]}" if binA else ""))
    print(f"new ={args.out}  ({len(B)} crashes)"
          + (f"  llc={binB.most_common(1)[0][0]}" if binB else ""))
    print(f"\nFIXED ({len(fixed_real)}):")
    for k in fixed_real:
        print(f"  - {fmt(k)}   was: {A[k]}")
    if fixed_to_timeout:
        print(f"\nFIXED->TIMEOUT (crash gone but now hangs) ({len(fixed_to_timeout)}):")
        for k in fixed_to_timeout:
            print(f"  - {fmt(k)}   was: {A[k]}")
    print(f"\nREGRESSED ({len(regressed)}):")
    for k in regressed:
        print(f"  - {fmt(k)}   now: {B[k]}")
    if was_timeout:
        print(f"\nTIMEOUT->CRASH (already failing in base, not a regression) "
              f"({len(was_timeout)}):")
        for k in was_timeout:
            print(f"  - {fmt(k)}   now: {B[k]}")
    if changed:
        print(f"\nSIGNATURE CHANGED ({len(changed)}):")
        for k in changed:
            print(f"  - {fmt(k)}\n      A: {A[k]}\n      B: {B[k]}")
    net = len(B) - len(A)
    print(f"\nNET crashes: {len(A)} -> {len(B)}  ({net:+d})")
    print(f"REAL regressions: {len(regressed)} | REAL fixes: {len(fixed_real)} | "
          f"timeout->crash: {len(was_timeout)}")


def cmd_report(args):
    write_report(Path(args.out), args.examples)
    print((Path(args.out) / "report.md").read_text())


def main():
    ncpu = os.cpu_count() or 4
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    default_out = SCRIPT_DIR / "out" / "ssara-corpus" / ts
    r = sub.add_parser("run")
    r.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    r.add_argument("--out", default=str(default_out))
    r.add_argument("--llc", default=str(DEFAULT_LLC))
    r.add_argument("--jobs", type=int, default=max(1, ncpu // 2))
    r.add_argument("--timeout", type=int, default=120)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--glob", default="")
    r.add_argument("--include-mir", action="store_true")
    r.add_argument("--no-verify", action="store_true")
    r.add_argument("--examples", type=int, default=5)
    r.add_argument("--ssa-extra", default=None,
                   help="Override SSARA extra flags wholesale, e.g. "
                        "'-amdgpu-ssa-split-live-ranges'. Empty string = no "
                        "extras. Default keeps acl-coloring+agpr-rescue+"
                        "virgin-order.")
    r.add_argument("--tests", nargs="+", default=None,
                   help="Explicit test list (paths relative to --corpus or "
                        "absolute). Uses each test's own RUN line for target/"
                        "mcpu/-global-isel. Bypasses discover().")
    r.add_argument("-f", "--tests-file", default=None,
                   help="File of test paths (one per line, # comments ok) for a "
                        "manual custom run. Merges with --tests.")
    r.add_argument("--configs", choices=("all", "first"), default=None,
                   help="Which RUN configs per file: 'all' (default, full "
                        "fidelity, one record per (test,config)) or 'first' "
                        "(old one-config-per-file, comparable/faster).")
    r.add_argument("--capture-crashes", action="store_true",
                   help="On each crash, re-run with --debug-flags and save the "
                        "full debug log to crashlogs/<test-config>/.")
    r.add_argument("--debug-flags", default=None,
                   help="Flags injected on the --capture-crashes re-run "
                        "(default '-debug').")
    r.add_argument("--forensic", action="store_true",
                   help="Collect forensic data: inject "
                        "-amdgpu-ssa-forensic-json=<per-tag> into each SSARA "
                        "run (writes forensic/<tag>.forensic.json) and retain "
                        "Greedy output for colorfailing functions, incl. the "
                        "crash path. OFF => byte-identical to today.")
    r.add_argument("--config", default=None,
                   help="JSON config file of defaults (debug_flags, "
                        "capture_crashes, configs, tests, tests_file, ssa_extra); "
                        "CLI flags override it.")
    r.add_argument("--rerun-failed", default=None,
                   help="VERBATIM replay of a prior failed.txt (or its --out "
                        "dir): run each crashed command as-is to confirm a "
                        "rebuilt-in-place fix. Rewrites failed.txt with survivors.")
    r.set_defaults(func=cmd_run)
    rp = sub.add_parser("report")
    rp.add_argument("--out", required=True)
    rp.add_argument("--examples", type=int, default=5)
    rp.set_defaults(func=cmd_report)
    dp = sub.add_parser("diff", help="Compare two run dirs by (test,config) "
                                     "crash set: FIXED / REGRESSED / SIG-CHANGED.")
    dp.add_argument("--base", required=True, help="Old run --out dir.")
    dp.add_argument("--out", required=True, help="New run --out dir.")
    dp.add_argument("--allow-flag-mismatch", action="store_true",
                    help="Diff even when the two runs used different SSARA "
                         "flags. Without this, a mismatch exits 2.")
    dp.set_defaults(func=cmd_diff)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
