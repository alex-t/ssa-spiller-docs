# Current Pipeline

**SSA-based register allocation pipeline (work in progress)**

```mermaid
flowchart TD
    subgraph Input["Input"]
        NonSSA["Non-SSA MIR<br/>(post-PHI elimination)"]
    end
    
    NonSSA --> Rebuilder
    
    subgraph Rebuilder["SSA Rebuilder ⚠️ TEMPORARY"]
        R1["Reconstruct SSA form"]
    end
    
    Rebuilder --> Spiller
    NUA["NextUseAnalysis"] -.->|"next-use distances"| Spiller
    
    subgraph Spiller["SSA Spiller ✅"]
        S1["Reduce RP via spilling"]
    end
    
    Spiller <--> SSAUpdater["MachineLaneSSAUpdater"]
    
    Spiller --> RegAlloc
    
    subgraph RegAlloc["SSA Register Allocator ⚠️ Coloring done"]
        RA1["color() — width-descending PEO ✅"]
        RA2["Operand rewrite 📋"]
        RA1 --> RA2
    end
    
    RegAlloc -.-> Destruction
    
    subgraph Destruction["SSA Destruction 📋 NIY"]
        D1["Eliminate PHIs"]
    end
    
    Destruction --> Output
    
    subgraph Output["Output"]
        Final["Non-SSA MIR<br/>(physical registers)"]
    end
    
    style Rebuilder fill:#fff3cd,stroke:#ffc107
    style Spiller fill:#d4edda,stroke:#28a745
    style RegAlloc fill:#fff3cd,stroke:#ffc107
    style Destruction fill:#e2e3e5,stroke:#6c757d,stroke-dasharray: 5 5
```

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented |
| 📋 NIY | Not Implemented Yet |
| ⚠️ TEMPORARY | Will be removed |
| ─── | Data flow |
| - - - | Planned (not connected yet) |

## MIR Format at Each Stage

| Stage | Input | Output |
|-------|-------|--------|
| SSA Rebuilder | Non-SSA (multiple defs/VReg) | SSA (single def/VReg, PHIs at merge) |
| SSA Spiller | SSA, high RP | SSA, RP within limits |
| Register Allocator | SSA, virtual regs | SSA, virtual regs + ColorMap (physreg assignment) |
| SSA Destruction | SSA, physical regs | Non-SSA, no PHIs |

## Components

- [[../02-Components/SSA_Rebuilder|SSA Rebuilder]] ⚠️
- [[../02-Components/SSA_Spiller|SSA Spiller]]
- [[../02-Components/Next_Use_Analysis|Next Use Analysis]]
- [[../02-Components/MachineLaneSSAUpdater|MachineLaneSSAUpdater]]
- [[../02-Components/SSA_Register_Allocator_Impl|SSA Register Allocator]] 📋
- [[../02-Components/SSA_Destruction|SSA Destruction]] 📋

