# Mail Report Format — company mailing list

Rules for generating a concise contribution report for posting to the company mailing
list. This is the **trimmed, external** form. Use these rules whenever asked to "generate a
report for posting in mail".

## Relationship to the internal report
- The **detailed biweekly stays in the worklog** (`08-Worklog/NOTES.md` + the dated
  `YYYY-MM-DD-..-biweekly.md`). It keeps the full design discussion, root causes, file/commit
  detail, and next steps.
- The **mail report is a trimmed, ready-to-paste derivative** for the mailing list — generated on
  demand, not a replacement for the internal one. Always keep both: internal = detailed,
  external = concise.

## Audience & tone
- Audience: the broader engineering org, not just the SSA RA team.
- Reader-friendly technical prose: each item states **what changed** and **why it matters**
  in 1–3 sentences.
- Name key functions/APIs inline (e.g. `lowerPHIs`, `getRegSplitParts`, `SILowerSGPRSpills`)
  but in prose — no code blocks.
- Report only **landed / completed** work, phrased as accomplishments.

## Structure (outline bullets, ≤ 3 levels)
- Top line: `Contributions from <Name>`
- **Level 1** — component area: e.g. *SSA Register Allocator*, *SSA Spiller*,
  *Pipeline Integration*, *Test Suite*.
- **Level 2** — a fix/feature: a short title, then a 1–3 sentence what+why.
- **Level 3** — when a Level-2 item groups several sub-fixes, list them as named one-line
  sub-bullets (e.g. the post-RA property/liveness fixes).

## Per-item phrasing
- Lead with the outcome/title, then the rationale:
  "*Short title*: \<what was wrong\> → \<what now happens / why it matters\>."
- Prefer concrete, verifiable results, e.g. "kernarg pointer now assigned `sgpr4_5` (no overlap
  with the wide-load result)", or "diamond kernel with `amdgpu-num-vgpr=2` produces
  `buffer_store_dword` + `buffer_load_dword` + `NumVgprs: 2`".

## Test Suite summary (optional)
- Include a test-suite table **only when it communicates progress or a regression** — e.g. a new
  suite, a meaningful jump in test count, or a regression fixed/introduced. It is **not** a
  mandatory section; omit it when counts are just a static snapshot.
- When included: **Suite | Pass | XFail | Fail** (+ **Total**); suites such as *SSARA (Register
  Allocator)*, *Next Use Analysis*, *SSA Spiller*. Prefer phrasing that shows the delta (e.g.
  "+10 e2e tests", "2 XFAILs flipped to passing") over a bare snapshot.

## Omit (vs the internal biweekly)
- Commit hashes, file paths / line numbers, branch & worktree names.
- Design discussion, alternatives considered, "discarded approaches".
- Pending / Next Steps (unless explicitly requested).
- WIP / uncommitted / "XFAIL-as-known-bug" detail — only what's done; XFAIL counts live in the table.

## Producing a paste-ready DOCX / email fragment
Author the report in Markdown (nested `-` bullets + a Markdown table), then convert with
**pandoc** (installed at `/usr/bin/pandoc`):

- **DOCX file (primary):** `pandoc report.md -o report.docx` — maps nested `-` bullets to Word
  list levels and the pipe table to a Word table; open and copy into the email, or attach.
- **Direct Outlook/Word paste:** `pandoc report.md -t html -o report.html`, open in a browser,
  select-all → copy → paste into the message body (outline + table preserved).
- Keep nesting to the `-`-bullet depth that maps to Word list levels (≤ 3).
