# The issue
We run Next use Analysis before spilling.
While spilling we insert reloads before uses of the spilled register.
Each reload defines new SSA variable (new register). Reload starts new Live Interval
which itself can be split again (spill of the earlier reloaded register).
[Machine Lane SSA Updater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md) insert PHI nodes on the reload parent block IDF and also creates new registers.
Since we run NUA statically before the spiller, **new SSA variables have no entry in the NUA map and, hence, considered dead**.


> ❌ Missing image: `Pasted image 20251222122422.png`


This may result in the spilling the register which was just created and defined by the reload.
This **does not decrease the RP** and we later hit an **RP validation error**.
# Proposed solution 
1. Return special value from the NUA designating that no distance was ever computed for the register.
2. Add functional API to compute NUD for the new register on demand.

# Temporary workaround
Keep VregMaskPairSet of the all new VRegs and filter it out from the Active set.
For that we change [Machine Lane SSA Updater](SSA_Spiller/04-Design/MachineLaneSSAUpdater.md)  API method repairSSAForNewDef signature to accept a reference to vector of Machine operands which will be filed with the inserted PHIs result operands.

