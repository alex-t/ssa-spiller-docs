# SSA Register Allocator Impl

Implementation-mapping note for the SSA register allocator described in:
[[01-Pipeline/SSA Register Allocator]].

This is intentionally “symbolic mapping” (like your spiller docs): it names *expected* LLVM/AMDGPU
integration points and the responsibilities of each component.

## Scope
- Allocate physical registers for MachineIR SSA values in AMDGPU.
- When constrained, perform SSA-aware spills/reloads while keeping IR in SSA.
- Defer SSA destruction to the final lowering stage.

## Expected LLVM integration points (symbolic)
- **Pass placement (target pipeline)**: after SSA repair/rebuilder, before SSA destruction.
- **Core dependencies**:
  - `MachineRegisterInfo` (vreg graph, defs/uses)
  - `MachineDominatorTree` (dom traversal + dominance queries)
  - Target register info (`SIRegisterInfo`, `SIInstrInfo`)
  - Next-use queries: [[02-Components/Next Use Analysis]]
  - SSA repair utilities: MachineLaneSSAUpdater (see SSA spiller docs)

## Proposed internal structure

### (A) Traversal / driver
Responsibilities:
- Choose dom-tree traversal strategy.
- Maintain an active set of live values (lane-aware).
- Invoke allocation for each def when entering its live region.

### (B) Allocation policy
Responsibilities:
- Find a free physical register compatible with the value’s register class / tuple constraints.
- If none is available:
  - select a victim using next-use (Belady-like) information
  - trigger spill/eviction

### (C) Spill/evict mechanism (reuse SSA spiller model)
Do *not* invent a second spilling model. Reuse the existing model:
- store-at-definition
- virtual spill point
- reload placement
- SSA repair

Links:
- [[02-Components/SSA Spiller]]
- `04-Design/Architecture.md` (“where stored” vs “when freed”)

### (D) Lane/subregister handling
AMDGPU requires lane-aware reasoning:
- represent live/allocated items as (VReg, LaneMask)
- allow partial eviction/spill if the value is larger than needed (when legal)

## Data structures (doc-level)
- **Active set**: lane-aware set of currently-live assigned values.
- **Assignment map**: vreg (or vreg+mask) → physreg/tuple.
- **Free lists**: per reg class, track available registers (and tuple availability).
- **Next-use interface**: query “distance” for candidate selection.

## Failure modes / invariants
- Must not violate MachineIR SSA invariants during on-demand spills/reloads.
- Must keep EXEC-related correctness: prefer store-at-definition when spilling.
- Must keep lane masks consistent across repair (delegate to MachineLaneSSAUpdater).

## Open questions (implementation planning)
- Exact boundary between “allocator” and “spiller” code:
  - embed spiller logic vs call out to a shared utility.
- How to measure “next use” in a dom-tree traversal:
  - instruction-distance is linear; dom-order is not.
- Whether to rely on LiveIntervals for validation/consistency or go SSA-native.

