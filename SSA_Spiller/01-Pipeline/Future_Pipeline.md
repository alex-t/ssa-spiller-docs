# Future Pipeline

**Target SSA-based register allocation (all upstream passes SSA-clean)**

```mermaid
flowchart TD
    subgraph Input["Input"]
        SSA["SSA MIR<br/>(preserved from IR lowering)"]
    end
    
    SSA --> Spiller
    NUA["NextUseAnalysis"] -.->|"next-use distances"| Spiller
    
    subgraph Spiller["SSA Spiller"]
        S1["Reduce RP via spilling"]
    end
    
    Spiller <--> SSAUpdater["MachineLaneSSAUpdater"]
    
    Spiller --> RegAlloc
    
    subgraph RegAlloc["SSA Register Allocator"]
        RA1["Assign physical registers"]
    end
    
    RegAlloc --> Destruction
    
    subgraph Destruction["SSA Destruction"]
        D1["Eliminate PHIs"]
    end
    
    Destruction --> Output
    
    subgraph Output["Output"]
        Final["Non-SSA MIR<br/>(physical registers)"]
    end
```

## Key Difference from Current

**No SSA Rebuilder** — SSA form is preserved naturally from IR lowering through all MIR passes until register allocation.

## Prerequisites

- All MIR passes before RA must be SSA-clean
- PHI Elimination must move after register allocation
- SSA form survives through instruction selection

## Components

- [SSA Spiller](../02-Components/SSA_Spiller.md)
- [Next Use Analysis](../02-Components/Next_Use_Analysis.md)
- [MachineLaneSSAUpdater](../04-Design/MachineLaneSSAUpdater.md)
- [SSA Register Allocator](../02-Components/SSA_Register_Allocator_Impl.md)
- [SSA Destruction](../02-Components/SSA_Destruction.md)

