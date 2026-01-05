# Chordal Graphs

## Definition
An undirected graph is **chordal** if every cycle of length \(\ge 4\) has a **chord**
(an edge connecting two non-consecutive vertices in the cycle).

Equivalent characterization:
- A graph is chordal iff it has a [[03-Concepts/Perfect Elimination Order (PEO)|Perfect Elimination Order (PEO)]].

## Why chordal graphs show up in SSA regalloc
SSA form + dominance-shaped liveness tends to produce interference structures that are chordal (or
close enough to treat as chordal in the theoretical model).

The key practical takeaway:
- chordal graphs admit efficient greedy coloring when processed in a PEO (no NP-hard general graph
  coloring step).

## Consequences
- **Coloring**: optimal coloring is polynomial-time on chordal graphs (greedy in reverse PEO).
- **Cliques**: maximal cliques can be enumerated efficiently; clique number equals chromatic number.

## References
- `06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`
- `06-Research/Papers/ssara.pdf`

