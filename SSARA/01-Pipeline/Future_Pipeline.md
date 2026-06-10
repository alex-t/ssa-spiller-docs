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

- [[../02-Components/SSA_Spiller|SSA Spiller]]
- [[../02-Components/Next_Use_Analysis|Next Use Analysis]]
- [[../02-Components/MachineLaneSSAUpdater|MachineLaneSSAUpdater]]
- [[../02-Components/SSA_Register_Allocator_Impl|SSA Register Allocator]]
- [[../02-Components/SSA_Destruction|SSA Destruction]]

