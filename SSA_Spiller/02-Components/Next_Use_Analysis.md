# Next Use Analysis

Returns distance-to-next-use for every register at a given instruction.

## Functional Role
- Computes use distances
- Supplies MIN-based ordering
- Operates at subregister (LaneMask) granularity

## Test Infrastructure
- 17 MIR LIT tests
- Parameterized unit test reading MIR + CHECKs
- API test for getSortedSubRegs()

## Related
- [NUA_TEST_PATTERNS](../05-Testing/Next_Use_Analysis/NUA_TEST_PATTERNS.md)
- [NextUseAnalysis](../04-Design/NextUseAnalysis.md)
