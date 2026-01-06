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
- [MachineLaneSSAUpdater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md)
- [Next Use Analysis](SSA_Spiller/02-Components/Next_Use_Analysis.md)
