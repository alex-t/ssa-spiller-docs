```mermaid 
flowchart TD
  bb0["bb0: def X, Y"]
  bb1["bb1: High RP<br/>spill X  (DG1 header)"]
  bb2["bb2: left path work"]
  bb5["bb5: use X<br/>use Y  (in DG1, outside DG2)"]
  bb6["bb6: exit"]

  subgraph DG1["Dom group 1 (spill X region)"]
    bb1
    bb2

    subgraph DG2["Dom group 2 (nested: spill Y region)"]
      bb3["bb3: spill Y (DG2 header)"]
      bb4["bb4: use Y"]
    end

    bb5
  end

  bb0 --> bb1
  bb1 --> bb2
  bb2 --> bb5

  bb1 --> bb3
  bb3 --> bb4
  bb4 --> bb5

  bb5 --> bb6
