# Corpus report — undef-only PHI coalescer

**Run:** `/tmp/corpus-undefcoal` (harness `ssara_corpus_harness.py run`, jobs=64, timeout=120s)
**llc:** `ssara/build/user-debug/bin/llc` with `amdgpu-phi-coalescer-undef-only.diff` applied
(undef-aware PHI-operand flagging only; no dominance-based coalescing).
**Baseline:** `/tmp/corpus-superuse` (fixes A–G, no coalescer).
**Total tests:** 3080. **SSARA lit:** 65/65.

## Bucket breakdown

| Bucket | Count | % of total | % of evaluated* |
|---|---:|---:|---:|
| OK_EQUAL | 785 | 25.49% | 35.20% |
| MIXED | 511 | 16.59% | 22.91% |
| DIFF_COALESCING | 403 | 13.08% | 18.07% |
| OK_BETTER | 372 | 12.08% | 16.68% |
| NO_METRICS | 61 | 1.98% | 2.74% |
| CRASH | 58 | 1.88% | 2.60% |
| REGRESSION_OCC_OR_SPILL | 40 | 1.30% | 1.79% |
| **Evaluated subtotal** | **2230** | **72.40%** | **100.00%** |
| SKIP_PIPELINE | 306 | 9.94% | — |
| SKIP_NOT_FULL_PIPELINE | 241 | 7.82% | — |
| SKIP_R600 | 109 | 3.54% | — |
| SKIP_O0 | 91 | 2.95% | — |
| SKIP_EXPECTED_FAIL | 68 | 2.21% | — |
| SKIP_GENERATED_INPUT | 12 | 0.39% | — |
| SKIP_CUSTOM_REGALLOC | 12 | 0.39% | — |
| SKIP_NO_LLC | 11 | 0.36% | — |
| **Skipped subtotal** | **850** | **27.60%** | — |

\* "evaluated" = tests actually compiled through the SSA-RA pipeline (total minus all
`SKIP_*`); percentages in that column are shares of the 2230 evaluated tests.

## Delta vs baseline (fixes A–G, no coalescer)

| Bucket | base | undef-only | Δ |
|---|---:|---:|---:|
| CRASH | 59 | 58 | −1 |
| OK_EQUAL | 775 | 785 | +10 |
| OK_BETTER | 371 | 372 | +1 |
| DIFF_COALESCING | 405 | 403 | −2 |
| MIXED | 511 | 511 | 0 |
| REGRESSION_OCC_OR_SPILL | 40 | 40 | 0 |

- **0 new crashes, 0 PASS→fail regressions, 0 OK_BETTER→worse transitions.**
- Crash recovered: `inline-asm.ll`.
- Contrast with the full dominance-coalescing variant (`corpus-phicoal3`): that was
  −2 CRASH but **OK_BETTER −8** (9 kernels +1..+5 VGPRs). The undef-only slice avoids
  that pressure pessimization entirely (OK_BETTER +1, REGRESSION_OCC_OR_SPILL +0) while
  still moving +10 tests to OK_EQUAL by reclaiming dead IMPLICIT_DEF placeholders.
