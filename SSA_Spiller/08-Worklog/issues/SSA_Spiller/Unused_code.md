## Spiller
  MachineInstr* splitBlockBeforeReload(MachineInstr *KillMI,  MachineInstr *ReloadMI,         VRegMaskPair SpilledVMP);

  void handleReachableUse(MachineInstr *KillMI, MachineInstr *ReloadMI,
                          VRegMaskPair SpilledVMP);