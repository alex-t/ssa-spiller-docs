# SSA Region Register Allocation: Minimum-Cost Spill/Split Packing

## Context

We are exploring a region-based SSA register allocator. The allocator operates on a region as a whole rather than making independent per-vreg spill decisions.

The high-level goal is:

> Given the current assignments, uncolored values, physical-register constraints, and legal spill/split transformations, transform the region into a feasible allocation while minimizing the total cost of the solution.

A useful pressure lower bound is:

```text
RP + NumUncolored <= Limit

NumToSpill = RP + NumUncolored - Limit
```

However, this is only a lower bound / necessary capacity condition. Register allocation is not merely about reducing register pressure below a limit. A value must be placed in compatible physical registers throughout the portions of its live range where it is resident, and physical-register constraints can make an apparently low-pressure region impossible to allocate.

## Why SSA Structure Does Not Make the Whole Problem Easy

For ideal SSA on a homogeneous RISC-like register file, the interference graph has useful chordal structure and admits a perfect elimination ordering (PEO). That is the attractive starting point.

Unfortunately, real targets introduce physical-register constraints:

```text
v -> R3
w -> {R0, R1}
x -> compatible register tuple
```

As soon as operands can require particular physical registers or restricted register sets, allocation becomes a precolored-extension / constrained-coloring problem. In general this is NP-hard even though the underlying SSA interference structure is well behaved.

AMDGPU makes this especially relevant because of:

- heterogeneous register classes;
- physical register tuples / different widths;
- subregister constraints;
- already assigned or effectively precolored values;
- operand-specific physical-register requirements;
- fragmentation of the physical register file.

Therefore:

```text
RP <= Limit
```

does **not** imply that the remaining values can actually be assigned.

`RP + NumUncolored - Limit` should be treated as a useful lower bound, not as a feasibility test.

## Core Idea: Complementary Spilling

The desired behavior is not simply:

> Pick a victim and spill that vreg.

Instead, values can share register capacity over different portions of their lifetimes.

Suppose `A` and `B` overlap, but their profitable/necessary register-resident portions differ. We may want:

```text
             segment 0   segment 1   segment 2

A               REG         MEM          REG
B               MEM         REG          MEM
```

In words:

> Spill somebody where they do not need the register, and spill the value being allocated where it can cheaply leave the register.

This can create a mosaic of complementary register-resident fragments rather than choosing one whole live interval as the spill victim.

The operation should therefore conceptually be closer to:

```text
vacate(value, subregion)
```

than:

```text
spill(value)
```

The implementation of `vacate` may require splitting, storing, reloading, reassigning, etc.

## Do Not Assume Convenient Use Clusters

An earlier tempting simplification is to identify large gaps between clusters of uses and spill values in those gaps. This cannot be assumed.

Uses may be distributed almost uniformly:

```text
A: def--u-----u-----u-----u-----u----
B:    def--u-----u-----u-----u------
C:       def--u-----u-----u-----u---
```

There may be no obvious large use-free gap.

Nevertheless, spilling between two neighboring uses may still be profitable:

```text
A: ---- use -------- use ----
              ^^^^^
           spilled here
```

with a store/reload cost paid at the boundaries.

Therefore use clusters can be an optimization heuristic, but they must not be fundamental to the mathematical model.

## Better Abstraction: Residency Paths

For each value, consider its state as execution progresses through the region.

A state can be:

```text
MEM
R0
R1
R2
...
```

A value follows a path through these states:

```text
          R0 ----- R0 ----- R0
         /  \       |
MEM ----     R1 ---- R1 ---- ...
         \  /
          R2
```

Transitions have costs:

```text
REG -> MEM       store/spill cost
MEM -> REG       reload cost
REGa -> REGb     copy/reassignment cost
REG -> same REG  usually zero
```

Operand constraints restrict which states are legal at particular events. For example, an instruction may require a value to be resident in a particular physical register or register class.

For one value in isolation, finding the cheapest residency path resembles a shortest-path problem.

The hard part is that residency paths of different values interact: two interfering values cannot occupy conflicting physical registers simultaneously. This coupling is where the NP-hard constrained allocation problem remains.

## Events and Elementary Segments

Do not require the solver to reason at every machine instruction if unnecessary. Divide a region at points where the allocation problem can change materially, such as:

- definitions;
- uses;
- physical-register constraints;
- regmask/call constraints;
- legal or profitable split points;
- live-range starts/ends;
- other target-specific allocation events.

Between adjacent events, occupancy constraints are stable enough to treat the portion as an elementary segment.

The solver then decides residency and physical placement over these segments.

## Physical Availability Matters, Not Just Pressure

A region can have enough free register *count* but no compatible placement.

Example:

```text
free physregs = {R1, R4}
```

but an uncolored value requires an aligned/consecutive tuple. Numerically there are two free registers, yet the value still cannot be placed.

Therefore solver state needs some representation of physical availability, for example occupancy/availability masks or a derived representation per register class / tuple class.

The important query is not:

```text
Can I free N registers?
```

but:

```text
Can I create a compatible physical hole for value U over the required portion of the region?
```

## Region Solver Formulation

Conceptually, the region solver receives:

```text
Input:
  live ranges / fragments
  current physical assignments
  uncolored values
  allowed physical-register sets / register classes
  operand constraints / precoloring
  legal split points
  spill/reload/copy/reassignment costs
  target register conflicts and tuple constraints
```

and chooses:

```text
Decisions:
  register-resident fragments
  memory-resident fragments
  split points
  spill/reload boundaries
  physical-register assignments
  possible local reassignments / evictions
```

subject to:

```text
Constraints:
  every required operand is available in a legal register
  interfering resident fragments do not use conflicting physical registers
  register-class / tuple / subregister constraints are respected
  transformations preserve correctness
```

while minimizing:

```text
CostOfSolution =
    spill/store costs
  + reload costs
  + split costs
  + copy/reassignment costs
  + eviction costs
  + target-specific penalties
  + optional estimate of downstream allocation damage
```

## Conflict-Driven Search

Since the full constrained problem is NP-hard, a promising production strategy is not to enumerate all possible spill sets. Instead, attempt physical placement and branch only when a real obstruction is encountered.

Sketch:

```text
try place U
    |
    +-- success --> continue
    |
    +-- failure
          |
          +-- identify physical blockers
          |
          +-- generate local transformations
                 - vacate fragment of blocker A
                 - vacate fragment of blocker B
                 - split U
                 - spill U over the expensive/conflicting section
                 - reassign blocker C
                 - split/reassign a blocker
          |
          +-- evaluate/search resulting states
```

For example, suppose the desired path for `U` through `R4` is blocked by:

```text
A on [17,22]   displacement cost = 3
B on [22,28]   displacement cost = 9
C on [28,31]   displacement cost = 2
```

A solution need not spill all blockers. It might choose:

```text
reroute/vacate A       3
spill U on [22,28]     4
reroute/vacate C       2
-------------------------
total                  9
```

This is the complementary-spilling behavior we want the region solver to discover.

## Role of Register Pressure

Register pressure remains useful, but primarily for lower bounds and pruning.

For example:

```text
NumToSpill = max(0, RP + NumUncolored - Limit)
```

can tell us that any solution must create at least some amount of capacity. It can reject search states that cannot possibly free enough capacity.

It must **not** be used as proof that a solution exists once the inequality is satisfied, because physical-register fragmentation and precoloring constraints remain.

## Architectural Direction

Instead of a state machine whose states are narrowly specialized handlers such as:

```text
SpillCrossLiverHandler
SplitAroundHoleHandler
EvictHandler
...
```

consider making spill/split/evict/reassign operations into transformations available to a more general regional solver:

```text
RegionPackingSolver
```

The state machine, if retained, can control search policy rather than hard-code mutually exclusive allocation strategies.

In this model:

```text
spill cross liver
split uncolored
split blocker
reassign
local eviction
```

are operators over solver states.

The solver's contract is essentially:

> Do whatever legal local transformations are necessary to place every required value from beginning to end of the region, minimizing `CostOfSolution`.

## Reference Optimal Solver for Experiments

For small regions, it may be useful to implement an exact reference solver purely as a development oracle.

One possible approach is **Integer Linear Programming (ILP)** — not Instruction-Level Parallelism.

The production allocator does not need to use ILP. The purpose would be to answer:

```text
What is the actual optimum CostOfSolution for this small region?
```

Then compare:

```text
heuristic solver = 37
exact optimum    = 29
```

and inspect what transformation pattern the exact solver found.

This provides ground truth for developing and tuning the production heuristic/search algorithm.

## Main Research Question

The current problem to solve is therefore:

> Design a practical region-level search/optimization algorithm that chooses complementary register-resident and spilled fragments, physical assignments, splits, reloads, and local evictions so that a constrained SSA allocation becomes feasible while approximately minimizing `CostOfSolution`.

Important properties:

1. The underlying SSA live-range structure is highly ordered and should be exploited.
2. We cannot rely on chordal/PEO coloring alone because precolored extension / register constraints make the general problem NP-hard.
3. Register pressure is a lower bound, not a feasibility criterion.
4. Decisions should be made for the region, not independently per vreg.
5. Partial/complementary spilling is fundamental.
6. Uses may be dense or uniformly distributed; the algorithm cannot depend on large use-free gaps.
7. Physical-register compatibility and fragmentation must be represented explicitly enough to detect real placement failures.
8. Search should preferably be driven by actual placement conflicts rather than enumerating arbitrary spill sets.
9. `CostOfSolution` should be the central objective used to compare alternative transformations.

## Candidate Next Step

Prototype a `RegionPackingSolver` on small regions with:

```text
1. Build region events / elementary segments.
2. Attempt physical placement of uncolored values.
3. On failure, extract the minimal/useful set of physical blockers.
4. Generate local actions:
     - vacate blocker fragment
     - spill current value fragment
     - split current value
     - split blocker
     - local reassignment/eviction
5. Assign each action an incremental cost.
6. Search a bounded set of resulting states (branch-and-bound / beam search / A*-like search).
7. Use RP-derived bounds for pruning.
8. Compare small cases against an exact reference solver.
```

The central representation to investigate is a **residency path** for each value through `{MEM, physical registers}`, coupled to other values through physical-register conflict constraints.
