
# SSA Spiller Test: Dominated Uses in Diamond CFG (Dom-Group Pitfall)

## Goal

Create a MIR test that exercises **dominated-use group building** and demonstrates why a spill placed in the **nearest common dominator (NCD)** can still lead to **incorrect SSA repair** if dominated uses are processed in the “wrong” order (DFS / RPO artifact), causing `MachineLaneSSAUpdater` to synthesize an illegal PHI that merges `{reloaded_value, original_spilled_value}`.

We want the test to model the following situation:

- `x` is spilled in the dominator block.
- There are **multiple uses of `x` dominated by that spill**:
  - one use inside one branch of a diamond
  - another use in the join block
- If the dominated use in the branch is processed first and SSA repair is performed immediately, SSAUpdater may create a PHI in the join that merges:
  - `y` (reloaded on the processed path) and
  - `x` (original value on the other path)
- But `x` **is already spilled in the dominator**, so that merge is invalid.

## CFG (intended)

```mermaid
flowchart TD
  S["bb0: NCD / spill x"] -->|cond| U1["bb1: use x (dominated)"]
  S -->|!cond| B2["bb2: no use"]
  U1 --> J["bb3: join / use x (dominated)"]
  B2 --> J
```




```mermaid
graph TD
  entry((Def X,Y,Z)) -->|cond0| dg1_spillx
  entry((Def X,Y,Z)) -->|!cond0| dg3_spillz
  dg1_spillx -->|cond1| dg2_spilly
  dg1_spillx -->|!cond1| dg1_side
  dg2_spilly --> dg2_usey
  dg2_usey --> dg1_usexy
  dg1_side --> dg1_usexy
  dg1_usexy --> merge
  dg3_spillz --> dg3_usez
  dg3_usez --> merge
  merge --> final

  subgraph "Dom group 1"
    dg1_spillx[High RP → spill X]
    dg1_side[side path]
    dg1_usexy[Use X and Use Y]
    subgraph "Dom group 2 (nested in DG1)"
      dg2_spilly[spill Y]
      dg2_usey[Use Y]
    end
  end

  subgraph "Dom group 3"
    dg3_spillz[High RP → spill Z]
    dg3_usez[Use Z]
  end
```