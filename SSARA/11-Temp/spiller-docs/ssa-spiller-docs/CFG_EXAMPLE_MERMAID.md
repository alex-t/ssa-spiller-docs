# CFG from Your JSON - Converted to Mermaid

```mermaid
graph TD
    BB0["BB0<br/>x = def"] --> BB1["BB1<br/>slot0 = spill(x)"]
    BB0 --> BB2["BB2<br/>use(x)"]
    BB1 --> BB3["BB3<br/>(JOIN)"]
    BB2 --> BB3
    BB3 --> BB4["BB4"]
    BB4 --> BB5["BB5<br/>(LOOP HEADER)"]
    BB5 --> BB6["BB6"]
    BB5 --> BB9["BB9"]
    BB6 --> BB7["BB7<br/>(JOIN)"]
    BB9 --> BB7
    BB7 --> BB8["BB8"]
    BB7 -.->|back-edge| BB5
    
    style BB0 fill:#e1f5ff,stroke:#2196F3,stroke-width:2px
    style BB1 fill:#ffe1e1,stroke:#f44336,stroke-width:2px
    style BB2 fill:#e1ffe1,stroke:#4CAF50,stroke-width:2px
    style BB3 fill:#fff4e1,stroke:#ff9800,stroke-width:3px
    style BB5 fill:#f3e5f5,stroke:#9c27b0,stroke-width:2px
    style BB7 fill:#fff4e1,stroke:#ff9800,stroke-width:3px
```

**CFG Analysis:**
- **BB0**: Entry, defines x
- **BB1**: Spill path (spills x to slot0)
- **BB2**: Clean path (uses x directly)
- **BB3**: **JOIN** - paths merge here
- **BB5**: Loop header
- **BB7**: **JOIN** - BB6 and BB9 merge
- **BB7 → BB5**: Back-edge (loop)

This is a perfect example for spill analysis:
- BB0 → BB1 (spill) and BB0 → BB2 (clean) diverge
- They join at BB3
- BB3 → BB5 → ... → BB7 → BB5 forms a loop






