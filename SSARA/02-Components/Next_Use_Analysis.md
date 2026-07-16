# Next Use Analysis

Returns distance-to-next-use for every register at a given instruction
(`AMDGPUNextUseAnalysis` / `NextUseResult`).

## Functional Role
- Computes use distances via `getNextUseDistance` (a `DeadDistance` sentinel marks dead/unused registers)
- Supplies MIN/Belady-based ordering for the spiller's victim selection
- Operates at subregister (`LaneBitmask`) granularity
- **Requires SSA** (asserts `MRI->isSSA()`)

## Consumers
- **[SSA_Spiller](SSA_Spiller.md)** — the sole client; requests it via `getAnalysisUsage`
  (`AMDGPUNextUseAnalysisWrapper`), so it is scheduled/recomputed on demand
  rather than being explicitly added to the pipeline.
- **Not** used by the [SSA Register Allocator](SSA_Register_Allocator_Impl.md).

## Test Infrastructure
- 17 MIR LIT tests
- Parameterized unit test reading MIR + CHECKs

## Related
- [NUA_TEST_PATTERNS](../05-Testing/Next_Use_Analysis/NUA_TEST_PATTERNS.md)
- [NextUseAnalysis](../04-Design/NextUseAnalysis.md)
