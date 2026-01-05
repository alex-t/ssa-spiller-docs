
```mermaid 
graph TD
  entry((Def X,Y,Z)) -->|cond0| dg1_spillx[DG1: High RP → spill X]
  entry((Def X,Y,Z)) -->|!cond0| dg3_spillz[DG3: High RP → spill Z]

  dg1_spillx -->|cond1| dg2_spilly[DG2: spill Y]
  dg1_spillx -->|!cond1| dg1_side[DG1: side path]

  dg2_spilly --> dg2_usey[DG2: Use Y]
  dg2_usey --> dg1_usexy[DG1: Use X and Use Y]

  dg1_side --> dg1_usexy[DG1: Use X and Use Y]
  dg1_usexy --> merge((merge))

  dg3_spillz --> dg3_usez[DG3: Use Z]
  dg3_usez --> merge((merge))

  merge --> final[Final: Use X,Y,Z]
