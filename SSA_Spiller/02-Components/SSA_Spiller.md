# SSA Spiller

SSA-aware spiller operating on Machine IR.

## Entry Point
spillAndReload()

## Core Functions
- spillAtDefinition()
- emitReloadsAndRepairSSA()
- tryHoistSpillToNCD()
- splitBlockBeforeReload()
- handleReachableUse() [currently disabled]

## Working Features
✅ Dominated use grouping  
✅ Store-at-definition  
✅ LiveInterval kept valid through reload placement  
✅ Single-store design  
✅ Subregister handling via VRegMaskPair  
✅ Reachability filtering  
✅ SSA repair via MachineLaneSSAUpdater

## Disabled
⚠️ split-before-use (requires cost model)

## Related
- [[02-Components/MachineLaneSSAUpdater]]
- [[02-Components/Next Use Analysis]]
