# Chordal Graphs

## Definition
An undirected graph is **chordal** if every cycle of length \(\ge 4\) has a **chord**
(an edge connecting two non-consecutive vertices in the cycle).

Equivalent characterization:
- A graph is chordal iff it has a [Perfect Elimination Order (PEO)](Perfect_Elimination_Order_%28PEO%29.md).

## Why SSA interference graphs are chordal

In strict SSA form, every virtual register has exactly one definition.
Its live range is therefore a connected subtree of the dominance tree.
The intersection graph of subtrees of a tree is always chordal — this
is a classical graph-theory result (Gavril, 1974), applied to register
allocation by Hack, Grund & Goos (CC'06).

See [the paper](../06-Research/Papers/ssara.pdf) for the full proof.

The key practical consequence:
- chordal graphs admit efficient greedy coloring when processed in a PEO (no NP-hard general graph
  coloring step).

## Consequences
- **Coloring**: optimal coloring is polynomial-time on chordal graphs (greedy in reverse PEO).
- **Cliques**: maximal cliques can be enumerated efficiently; clique number equals chromatic number.

## References
- `06-Research/Papers/register-allocation-for-programs-in-ssa-form.pdf`
- `06-Research/Papers/ssara.pdf`

