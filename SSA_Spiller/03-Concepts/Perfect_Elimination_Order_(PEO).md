# Perfect Elimination Order (PEO)

## Definition
A **perfect elimination order (PEO)** of an undirected graph is an ordering of vertices
\(v_1, v_2, \dots, v_n\) such that for every vertex \(v_i\), the set of **later neighbors**
\(\{ v_j \mid j>i \ \wedge\ (v_i,v_j)\in E\}\) forms a **clique**.

Graphs that admit a PEO are exactly the **chordal graphs**.

See: [Chordal Graphs](Chordal_Graphs.md).

## Why it matters for register allocation
If the (value) interference graph is chordal, then:
- greedy coloring in **reverse PEO** produces an **optimal coloring** (minimum number of colors),
  under the assumptions of the model.

This is one of the theoretical pillars behind SSA-based regalloc approaches that avoid general graph
coloring.

## Connection to SSA
For programs in SSA form, the structure of liveness and dominance often yields chordal (or nearly
chordal) interference graphs, enabling efficient allocation strategies.

Practical allocators may not explicitly build the interference graph; they may instead exploit the
same property via dominator-based traversals and local greedy decisions.

## How to get a PEO (conceptually)
Classical chordal-graph algorithms compute a PEO via:
- Maximum Cardinality Search (MCS), or
- Lexicographic BFS (LexBFS).

In SSA regalloc literature, the “PEO” may be realized implicitly by:
- choosing an elimination order derived from dominance/liveness structure, rather than running MCS.

## Consequences / gotchas (practical)
- If the interference graph is **not** chordal (e.g., due to target constraints, tuples, subregister
  interactions), greedy coloring is no longer guaranteed optimal.
- Even with chordality, real backends need:
  - register classes,
  - reserved/fixed regs,
  - coalescing/copies,
  - spill costs,
  which can dominate the “pure” theory.

## References
- `06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`
- `06-Research/Papers/ssara.pdf`

