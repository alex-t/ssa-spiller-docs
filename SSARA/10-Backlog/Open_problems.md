# Open Problems

The whole SSA-RA pipeline runs only behind the hidden `-amdgpu-ssa-regalloc`
option (default OFF) and only in the legacy pass manager. The items below are
verified still-open against the current code.

## High Priority

- **SI control-flow-pseudo SSA destruction gap.** `destroySSAAndRewrite`
  bails out (skips PHI lowering / operand rewrite) when a function still
  contains SI control-flow pseudos (`SI_IF`/`SI_ELSE`/`SI_IF_BREAK`/`SI_LOOP`/
  `SI_END_CF`), detected by `hasCFPseudos`. Such functions are not handled by
  the SSA allocator's destruction stage.
- [[Static_NUA_limitation]] — static next-use distance limitation.

## Medium

- **Full PHI coalescer.** Not implemented. Only phi-affinity coloring hints, a
  PHI-copy metric, and the standalone `SimplifyUndefPHI` pass exist today.
- **Remove the temporary RebuildSSA bridge.** One RebuildSSA pass currently
  runs first to re-establish SSA; it should disappear once upstream passes
  remain SSA-clean.
- **New pass manager support.** The pipeline is wired only into the legacy PM.
- Cost model for reload hoisting.

## Low

- **Replace `SI_VIRTUAL_SPILL_MARKER`** (test-only pseudo, emitted only under
  `-amdgpu-ssa-spill-markers`) with `SIMachineFunctionInfo` metadata.
- Loop optimizations.
