# Next Use Analysis Test Pattern Classification

This document classifies all CFG patterns tested by the AMDGPU Next Use Analysis (NUA), organized by control flow complexity and loop structure.

## Overview

**Next Use Analysis** computes the distance (in instructions) from each program point to the next use of each virtual register. This information is critical for register spilling decisions.

### Key Concepts

1. **Finite Distances**: Direct instruction count to next use (0 to ~10^12)
2. **LoopTag Distances**: Applied to uses outside the current loop context (`LoopTag + offset`, where `LoopTag = 2^40`). This makes registers with distant uses (outside the loop) more attractive for spilling when register pressure is high inside the loop.
3. **DeadTag Distances**: No reachable next use (`DeadTag + offset`, where `DeadTag = 2^60`)
4. **Subregister Tracking**: Per-lane distance tracking using `LaneBitmask`

### Three-Tier Ranking System

```
Tier 1: Finite distances (0 to LoopTag-1)     → Immediate priority
Tier 2: Loop-exit distances (LoopTag to DeadTag-1) → Medium priority  
Tier 3: Dead registers (DeadTag+)             → Lowest priority (spill candidates)
```

---

## Pattern Classification Hierarchy

```
1. Linear Control Flow
   ├── 1.1 Simple Linear (basic block sequence)
   └── 1.2 Linear with Branches (diamond CFG, no loops)

2. Single Loop Patterns
   ├── 2.1 Simple Loop (3 blocks)
   ├── 2.2 Loop with Internal CFG
   ├── 2.3 Loop with Multiple Exits
   └── 2.4 Loop with Multiple Latches

3. Nested Loop Patterns
   ├── 3.1 Double-Nested Loops
   ├── 3.2 Triple-Nested Loops
   └── 3.3 Nested Loops with Side Exits

4. Sequential Loop Patterns
   ├── 4.1 Two Sequential Loops
   └── 4.2 Three Sequential Loops in Outer Loop

5. Complex Control Flow
   ├── 5.1 Diamond with Multiple Joins (11+ blocks)
   └── 5.2 Complex Nested Structure (14+ blocks)
```

---

## 1. Linear Control Flow

### Pattern 1.1: Acyclic CFG with PHI Merge Points

**Test File:** `acyclic-phi-merge-distances.mir`

**Description:** Acyclic CFG with two merge points (bb.1 and bb.4). Tests distance calculation through multiple paths and PHI node handling.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0<br/>Entry"]
    BB1["bb.1<br/>PHI merge"]
    BB2["bb.2<br/>Computation"]
    BB3["bb.3<br/>Alternative path"]
    BB4["bb.4<br/>Exit PHI merge"]
    
    BB0 --> BB3
    BB0 --> BB1
    BB3 --> BB1
    BB1 --> BB2
    BB1 --> BB4
    BB2 --> BB4
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB4 fill:#ffe6e6
```

**Key Validation Points:**
- bb.1 is first merge point: PHI merges values from bb.0 and bb.3
- bb.4 is second merge point: PHI merges values from bb.1 and bb.2
- Distances propagate correctly through multiple paths
- Minimum distance taken at merge points

**Test Priority:** ✅ **HIGH** (baseline case)

---

### Pattern 1.2: Complex Control Flow (11 Blocks)

**Test File:** `complex-control-flow-11blocks.mir`

**Description:** Acyclic CFG with multiple join points and nested conditionals. No loops.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0"]
    BB1["bb.1"]
    BB2["bb.2"]
    BB3["bb.3"]
    BB4["bb.4"]
    BB5["bb.5"]
    BB6["bb.6"]
    BB7["bb.7"]
    BB8["bb.8"]
    BB9["bb.9"]
    BB10["bb.10<br/>exit"]
    
    BB0 --> BB3
    BB0 --> BB8
    BB1 --> BB8
    BB2 --> BB6
    BB3 --> BB9
    BB3 --> BB1
    BB4 --> BB5
    BB4 --> BB10
    BB5 --> BB10
    BB6 --> BB7
    BB6 --> BB4
    BB7 --> BB4
    BB8 --> BB2
    BB8 --> BB6
    BB9 --> BB1
    
    style BB0 fill:#e6f3ff
    style BB10 fill:#ffe6e6
```

**Key Validation Points:**
- Multiple merge points (bb.1, bb.4, bb.6, bb.8)
- Distance computed as minimum across all paths
- No LoopTag - purely acyclic

**Test Priority:** 🟡 **MEDIUM** (complex acyclic CFG)

---

### Pattern 1.3: Complex Control Flow (15 Blocks)

**Test File:** `complex-control-flow-15blocks.mir`

**Description:** Deep nested acyclic CFG (bb.0-bb.14). Tests distance propagation through many merge points.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0"]
    BB1["bb.1"]
    BB2["bb.2"]
    BB3["bb.3"]
    BB4["bb.4"]
    BB5["bb.5"]
    BB6["bb.6"]
    BB7["bb.7"]
    BB8["bb.8"]
    BB9["bb.9"]
    BB10["bb.10"]
    BB11["bb.11"]
    BB12["bb.12"]
    BB13["bb.13"]
    BB14["bb.14<br/>exit"]
    
    BB0 --> BB1
    BB0 --> BB2
    BB1 --> BB2
    BB2 --> BB5
    BB2 --> BB3
    BB3 --> BB4
    BB3 --> BB6
    BB4 --> BB6
    BB5 --> BB3
    BB6 --> BB12
    BB6 --> BB7
    BB7 --> BB8
    BB7 --> BB14
    BB8 --> BB11
    BB8 --> BB9
    BB9 --> BB10
    BB9 --> BB13
    BB10 --> BB13
    BB11 --> BB9
    BB12 --> BB7
    BB13 --> BB14
    
    style BB0 fill:#e6f3ff
    style BB14 fill:#ffe6e6
```

**Key Validation Points:**
- Deep nesting of conditional blocks
- Multiple merge points at various levels
- No LoopTag - purely acyclic

**Test Priority:** 🟡 **MEDIUM** (stress test for acyclic CFG)

---

## 2. Single Loop Patterns

### Pattern 2.1: Simple Loop (3 Blocks)

**Test File:** `simple-loop-3blocks.mir`

**Description:** Minimal loop structure: preheader → header → latch → exit.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry<br/>def %8, %9, %10, %11"]
    BB1["bb.1.loop.header<br/>PHI nodes<br/>loop body"]
    BB2["bb.2.exit<br/>use registers"]
    
    BB0 --> BB1
    BB1 -->|"loop back"| BB1
    BB1 -->|"exit"| BB2
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB2 fill:#ffe6e6
```

**Key Validation Points:**
- **LoopTag applied** on loop-exiting edges during backward analysis
- When querying next-use distances from inside a loop, registers whose next use is *outside* the loop receive a `LoopTag` penalty, making them more attractive spill candidates
- PHI nodes at loop header merge initial and back-edge values

**Expected Distance Patterns:**
```
Query from inside loop:
  Use inside loop:   %x[ finite_distance ]      → keep in register
  Use outside loop:  %x[ LoopTag + distance ]   → good spill candidate
```

**Test Priority:** ✅ **HIGH** (fundamental loop case)

---

### Pattern 2.2: Complex Single Loop (Internal CFG)

**Test File:** `complex-single-loop.mir`

**Description:** Single loop with internal conditional branches (Flow blocks).

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop.header"]
    BB2["bb.2.bb1"]
    BB3["bb.3.Flow1"]
    BB4["bb.4.bb2"]
    BB5["bb.5.Flow"]
    BB6["bb.6.bb3"]
    BB7["bb.7.loop.latch"]
    BB8["bb.8.exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB1 --> BB5
    BB2 --> BB5
    BB5 --> BB6
    BB5 --> BB3
    BB6 --> BB3
    BB3 --> BB4
    BB3 --> BB7
    BB4 --> BB7
    BB7 -->|"back"| BB1
    BB7 --> BB8
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB7 fill:#fff3cd
    style BB8 fill:#ffe6e6
```

**Key Validation Points:**
- Internal branches don't affect LoopTag
- Distance calculation through multiple internal paths
- Correct minimum distance at join points within loop

**Test Priority:** 🟡 **MEDIUM** (loop with internal complexity)

---

### Pattern 2.3: Complex Single Loop (Variant A)

**Test File:** `complex-single-loop-a.mir`

**Description:** Loop with multiple internal conditional paths and multiple back edges.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.Flow"]
    BB3["bb.3.Flow2"]
    BB4["bb.4.bb1"]
    BB5["bb.5.bb2"]
    BB6["bb.6.loop1.latch2"]
    BB7["bb.7.exit"]
    
    BB0 --> BB1
    BB1 --> BB5
    BB1 --> BB2
    BB5 --> BB2
    BB2 -->|"back"| BB1
    BB2 --> BB3
    BB3 --> BB4
    BB3 --> BB6
    BB4 --> BB6
    BB6 -->|"back"| BB1
    BB6 --> BB7
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB6 fill:#fff3cd
    style BB7 fill:#ffe6e6
```

**Key Validation Points:**
- Single loop with 2 latches (bb.2, bb.6) and 2 back-edges to single header (bb.1)
- LoopTag NOT applied on internal latch edges (bb.2→bb.1) - iteration count is independent of which back-edge is taken
- LoopTag applied ONLY on true loop exit (bb.6→bb.7)

**Test Priority:** 🟡 **MEDIUM** (multi-latch loop)

---

### Pattern 2.4: Complex Single Loop (Variant B)

**Test File:** `acyclic-cfg-with-self-loop.mir`

**Description:** Complex acyclic CFG with simple self-loop (bb.3) on "then" path, no loop on "else" path.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop.preheader"]
    BB2["bb.2.Flow3"]
    BB3["bb.3.loop"]
    BB4["bb.4.bb1"]
    BB5["bb.5.bb2"]
    BB6["bb.6.Flow2"]
    BB7["bb.7.bb3"]
    BB8["bb.8.Flow"]
    BB9["bb.9.bb4"]
    BB10["bb.10.bb5"]
    BB11["bb.11.bb6"]
    BB12["bb.12.Flow1"]
    BB13["bb.13.exit"]
    
    BB0 --> BB4
    BB0 --> BB6
    BB4 --> BB5
    BB4 --> BB7
    BB5 --> BB7
    BB7 --> BB10
    BB7 --> BB8
    BB10 --> BB8
    BB8 --> BB9
    BB8 --> BB11
    BB9 --> BB11
    BB11 --> BB6
    BB6 --> BB1
    BB6 --> BB2
    BB1 --> BB3
    BB3 -->|"back"| BB3
    BB3 --> BB12
    BB12 --> BB2
    BB2 --> BB13
    
    style BB0 fill:#e6f3ff
    style BB3 fill:#fff3cd
    style BB13 fill:#ffe6e6
```

**Key Validation Points:**
- Self-loop (bb.3→bb.3) with LoopTag on exit edge
- Complex acyclic CFG with merge points surrounding the loop
- Tests distance propagation through branching without nested loops

**Test Priority:** 🟡 **MEDIUM** (acyclic with self-loop)

---

### Pattern 2.5: Two Sequential Loops

**Test File:** `two-sequential-loops.mir`

**Description:** Two sequential loops: first has internal Flow structure, second is self-loop. Tests independent LoopTag contexts.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.Flow"]
    BB3["bb.3.loop1.latch1"]
    BB4["bb.4.loop1.latch2"]
    BB5["bb.5.Flow1"]
    BB6["bb.6.bb"]
    BB7["bb.7.loop2"]
    BB8["bb.8.exit"]
    
    BB0 --> BB1
    BB1 --> BB4
    BB1 --> BB2
    BB4 --> BB2
    BB2 --> BB3
    BB2 --> BB5
    BB3 --> BB5
    BB5 -->|"back"| BB1
    BB5 --> BB6
    BB6 --> BB7
    BB7 -->|"back"| BB7
    BB7 --> BB8
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB7 fill:#d4edda
    style BB8 fill:#ffe6e6
```

**Key Validation Points:**
- Independent LoopTag contexts for each loop
- First loop has internal conditional structure (Flow blocks)
- Distance computation transitions correctly between loop boundaries

**Test Priority:** 🟡 **MEDIUM** (sequential loop independence)

---

## 3. Nested Loop Patterns

### Pattern 3.1: Double-Nested Loops (Inner CFG)

**Test File:** `inner_cfg_in_2_nested_loops.mir`

**Description:** Two-level nested loops with internal conditional CFG in inner loop.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0"]
    BB1["bb.1<br/>outer header"]
    BB2["bb.2<br/>inner header"]
    BB3["bb.3"]
    BB4["bb.4"]
    BB5["bb.5"]
    BB6["bb.6<br/>inner latch"]
    BB7["bb.7<br/>outer latch"]
    BB8["bb.8<br/>exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB2 --> BB5
    BB2 --> BB3
    BB3 --> BB4
    BB3 --> BB6
    BB4 --> BB6
    BB5 --> BB3
    BB6 -->|"inner back"| BB2
    BB6 --> BB7
    BB7 -->|"outer back"| BB1
    BB7 --> BB8
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB2 fill:#ffd699
    style BB8 fill:#ffe6e6
```

**Key Validation Points:**
- **Double LoopTag** for uses crossing both loop boundaries
- Inner loop uses: `LoopTag + D` from outer loop perspective
- Outer loop uses: `LoopTag + D` from exit perspective

**Test Priority:** ✅ **HIGH** (fundamental nested loop case)

---

### Pattern 3.2: Triple-Nested Loops

**Test File:** `triple-nested-loops.mir`

**Description:** Three-level nested loops testing LoopTag accumulation.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.loop2.header"]
    BB3["bb.3.loop3"]
    BB4["bb.4.loop2.latch"]
    BB5["bb.5.loop1.latch"]
    BB6["bb.6.exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB2 --> BB3
    BB3 -->|"L3 back"| BB3
    BB3 --> BB4
    BB4 -->|"L2 back"| BB2
    BB4 --> BB5
    BB5 -->|"L1 back"| BB1
    BB5 --> BB6
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB2 fill:#ffd699
    style BB3 fill:#ffb366
    style BB6 fill:#ffe6e6
```

**Key Validation Points:**
- **Triple LoopTag accumulation** for innermost uses viewed from exit
- Each loop boundary adds one LoopTag
- Correct distance calculation at each nesting level

**Expected Distance Patterns:**
```
From exit perspective:
  Inner loop use:  LoopTag*3 + D
  Middle loop use: LoopTag*2 + D  
  Outer loop use:  LoopTag*1 + D
```

**Test Priority:** ✅ **HIGH** (validates LoopTag accumulation)

---

### Pattern 3.3: Nested Loops with Side Exits (Variant A)

**Test File:** `nested-loops-with-side-exits-a.mir`

**Description:** Nested loops where inner loop can exit directly to outer loop exit.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.loop2.preheader"]
    BB3["bb.3.Flow12"]
    BB4["bb.4.loop2.header"]
    BB5["bb.5.bb1"]
    BB6["bb.6.Flow10"]
    BB7["bb.7.loop2.latch"]
    BB8["bb.8.loop1.latch"]
    BB9["bb.9.Flow9"]
    BB10["bb.10.exit"]
    BB11["bb.11.side.exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB1 --> BB3
    BB2 --> BB4
    BB4 --> BB5
    BB5 --> BB7
    BB5 --> BB11
    BB7 --> BB6
    BB6 -->|"inner back"| BB4
    BB6 --> BB8
    BB8 --> BB3
    BB3 -->|"outer back"| BB1
    BB3 --> BB9
    BB11 --> BB9
    BB9 --> BB10
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB4 fill:#ffd699
    style BB10 fill:#ffe6e6
    style BB11 fill:#ffcccc
```

**Key Validation Points:**
- Side exit from inner loop bypasses outer loop
- Different LoopTag levels for different exit paths
- Minimum distance across all exit paths

**Test Priority:** 🟡 **MEDIUM** (side exit complexity)

---

### Pattern 3.4: Double Nested Loops with Complex Inner CFG

**Test File:** `double-nested-loops-complex-cfg.mir`

**Description:** Two-level nested loops with complex internal CFG. Outer loop: bb.1 header, bb.3→bb.1 back-edge. Inner loop: bb.4 header, bb.37→bb.4 back-edge. No side exits.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1<br/>outer header"]
    BB2["bb.2"]
    BB3["bb.3<br/>outer latch"]
    BB4["bb.4<br/>inner header"]
    BB37["bb.37<br/>inner latch"]
    BB34["bb.34"]
    BB38["bb.38"]
    EXIT["exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB1 --> BB3
    BB2 --> BB4
    BB4 --> |"...complex CFG..."| BB37
    BB37 -->|"inner back"| BB4
    BB37 --> BB38
    BB38 --> BB3
    BB3 -->|"outer back"| BB1
    BB3 --> BB34
    BB34 --> EXIT
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB4 fill:#ffd699
    style EXIT fill:#ffe6e6
```

**Key Validation Points:**
- Double LoopTag for uses crossing both loop boundaries
- Complex internal CFG within inner loop (many Flow blocks)
- Correct distance propagation through nested structure

**Test Priority:** 🔵 **LOW** (stress test, many blocks)

---

## 4. Sequential Loop Patterns

### Pattern 4.1: Two Sequential Loops

**Test File:** `sequence_2_loops.mir`

**Description:** Two independent loops in sequence.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry<br/>def registers"]
    BB1["bb.1.loop1"]
    BB2["bb.2.bb<br/>between loops"]
    BB3["bb.3.loop2"]
    BB4["bb.4.exit<br/>use registers"]
    
    BB0 --> BB1
    BB1 -->|"back"| BB1
    BB1 --> BB2
    BB2 --> BB3
    BB3 -->|"back"| BB3
    BB3 --> BB4
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB3 fill:#d4edda
    style BB4 fill:#ffe6e6
```

**Key Validation Points:**
- Each loop has independent LoopTag context
- Register defined before loop1, used after loop2: crosses both
- Correct LoopTag when "exiting" analysis enters each loop

**Expected Distance Patterns:**
```
From bb.4 (exit):
  Use in loop2: LoopTag + D
  Use in loop1: LoopTag + D (from loop2's perspective it's outside)
```

**Test Priority:** 🟡 **MEDIUM** (sequential loop independence)

---

### Pattern 4.2: Complex Acyclic CFG with 4 Self-Loops

**Test File:** `complex-acyclic-cfg-with-4-self-loops.mir`

**Description:** Outer self-loop (bb.1) followed by acyclic CFG containing three sequential inner self-loops. Inner loops are NOT nested inside outer loop.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1<br/>(outer)"]
    BB2["bb.2.bb"]
    BB3["bb.3.loop3.preheader"]
    BB4["bb.4.loop2.preheader"]
    BB5["bb.5.Flow12"]
    BB6["bb.6.loop2"]
    BB7["bb.7.Flow"]
    BB8["bb.8.loop3"]
    BB9["bb.9.loop4.preheader"]
    BB10["bb.10.loop4"]
    BB11["bb.11.exit.loopexit"]
    BB12["bb.12.exit.loopexit1"]
    BB13["bb.13.exit"]
    
    BB0 --> BB1
    BB1 -->|"L1 back"| BB1
    BB1 --> BB2
    BB2 --> BB3
    BB2 --> BB7
    BB3 --> BB8
    BB8 -->|"L3 back"| BB8
    BB8 --> BB9
    BB9 --> BB10
    BB10 -->|"L4 back"| BB10
    BB10 --> BB12
    BB12 --> BB7
    BB7 --> BB4
    BB7 --> BB5
    BB4 --> BB6
    BB6 -->|"L2 back"| BB6
    BB6 --> BB11
    BB11 --> BB5
    BB5 --> BB13
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB6 fill:#d4edda
    style BB8 fill:#d4edda
    style BB10 fill:#d4edda
    style BB13 fill:#ffe6e6
```

**Key Validation Points:**
- Four independent self-loops (bb.1, bb.6, bb.8, bb.10)
- Inner loops are NOT nested inside outer loop - separate LoopTag contexts
- Complex acyclic CFG structure between loops

**Test Priority:** 🟡 **MEDIUM** (multiple independent self-loops)

---

## 5. Complex Nested Structures

### Pattern 5.1: Loop with 4 Nesting Levels

**Test File:** `loop_nested_in_3_outer_loops_complex_cfg.mir`

**Description:** Four-level nesting with internal CFG at innermost level.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.loop2.header"]
    BB3["bb.3.loop3.header"]
    BB4["bb.4.Flow"]
    BB5["bb.5.bb1"]
    BB6["bb.6.Flow4"]
    BB7["bb.7.loop4"]
    BB8["bb.8.bb2"]
    BB9["bb.9.bb3.loopexit"]
    BB10["bb.10.bb3"]
    BB11["bb.11.bb4"]
    BB12["bb.12.loop3.latch"]
    BB13["bb.13.loop2.latch"]
    BB14["bb.14.loop1.latch"]
    BB15["bb.15.exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB2 --> BB3
    BB3 --> BB8
    BB3 --> BB4
    BB8 --> BB4
    BB4 --> BB5
    BB4 --> BB6
    BB5 --> BB7
    BB7 -->|"L4 back"| BB7
    BB7 --> BB9
    BB9 --> BB6
    BB6 --> BB10
    BB10 --> BB11
    BB10 --> BB12
    BB11 --> BB12
    BB12 -->|"L3 back"| BB3
    BB12 --> BB13
    BB13 -->|"L2 back"| BB2
    BB13 --> BB14
    BB14 -->|"L1 back"| BB1
    BB14 --> BB15
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB2 fill:#ffd699
    style BB3 fill:#ffb366
    style BB7 fill:#ff9933
    style BB15 fill:#ffe6e6
```

**Key Validation Points:**
- Four levels of LoopTag accumulation
- Internal CFG (Flow blocks) at loop3 level
- Self-loop (loop4) at deepest level

**Test Priority:** 🟡 **MEDIUM** (deep nesting stress test)

---

### Pattern 5.2: If-Else with Nested Loops

**Test File:** `if_else_with_loops_nested_in_2_outer_loops.mir`

**Description:** Conditional branches selecting between different nested loop structures.

**CFG Diagram:**

```mermaid
graph TD
    BB0["bb.0.entry"]
    BB1["bb.1.loop1.header"]
    BB2["bb.2.loop2.header"]
    BB3["bb.3.loop4.preheader"]
    BB4["bb.4.loop3.header.preheader"]
    BB5["bb.5.Flow15"]
    BB6["bb.6.loop3.header"]
    BB11["bb.11.Flow14"]
    BB12["bb.12.loop4"]
    BB13["bb.13.Flow"]
    BB15["bb.15.bb4"]
    BB17["bb.17.loop2.latch"]
    BB18["bb.18.loop1.latch"]
    BB19["bb.19.exit"]
    
    BB0 --> BB1
    BB1 --> BB2
    BB2 --> BB3
    BB2 --> BB11
    BB3 --> BB12
    BB12 -->|"L4 back"| BB12
    BB12 --> BB13
    BB13 --> BB11
    BB11 --> BB4
    BB11 --> BB5
    BB4 --> BB6
    BB6 -->|"L3 back"| BB6
    BB6 --> BB5
    BB5 --> BB15
    BB15 --> BB17
    BB17 -->|"L2 back"| BB2
    BB17 --> BB18
    BB18 -->|"L1 back"| BB1
    BB18 --> BB19
    
    style BB0 fill:#e6f3ff
    style BB1 fill:#fff3cd
    style BB2 fill:#ffd699
    style BB6 fill:#d4edda
    style BB12 fill:#d4edda
    style BB19 fill:#ffe6e6
```

**Key Validation Points:**
- Conditional selection between loop3 and loop4 paths
- Both inner loops nested in loop1+loop2
- Correct LoopTag regardless of which inner loop executes

**Test Priority:** 🔵 **LOW** (complex conditional + loops)

---

## 6. Three-Tier Ranking Validation

### Pattern 6.1: Three-Tier Distance Ranking

**Test File:** `three-tier-ranking-nested-loops.mir`

**Description:** Specifically validates the three-tier ranking system.

**Key Concepts Tested:**

```mermaid
graph LR
    subgraph "Tier 1: Finite"
        F["0 to ~10^12"]
    end
    subgraph "Tier 2: LoopTag"
        L["LoopTag + offset<br/>(2^40 + D)"]
    end
    subgraph "Tier 3: DeadTag"
        D["DeadTag + offset<br/>(2^60 + D)"]
    end
    
    F -->|"<"| L
    L -->|"<"| D
```

**Validation Points:**
- Finite distances sort correctly (smaller = closer)
- LoopTag distances sort correctly (smaller offset = closer)
- DeadTag distances are always "furthest"
- Mixed comparisons work: `finite < LoopTag < DeadTag`

**Test Priority:** ✅ **HIGH** (validates core ranking algorithm)

---

## Summary: Test Case Priority Matrix

| **Pattern ID** | **Test File** | **Priority** | **Complexity** | **Key Feature** |
|----------------|---------------|--------------|----------------|-----------------|
| 1.1 | acyclic-phi-merge-distances | ✅ HIGH | Low | Basic distance calculation |
| 1.2 | complex-control-flow-11blocks | 🟡 MEDIUM | Medium | Multi-path join |
| 1.3 | complex-control-flow-15blocks | 🟡 MEDIUM | Medium | Deep branching |
| 2.1 | simple-loop-3blocks | ✅ HIGH | Low | Basic LoopTag |
| 2.2 | complex-single-loop | 🟡 MEDIUM | Medium | Internal CFG |
| 2.3 | complex-single-loop-a | 🟡 MEDIUM | Medium | Multi-latch |
| 2.4 | acyclic-cfg-with-self-loop | 🟡 MEDIUM | Medium | Acyclic + self-loop |
| 2.5 | two-sequential-loops | 🟡 MEDIUM | Medium | Sequential loop independence |
| 3.1 | inner_cfg_in_2_nested_loops | ✅ HIGH | High | Double LoopTag |
| 3.2 | triple-nested-loops | ✅ HIGH | High | Triple LoopTag |
| 3.3 | nested-loops-with-side-exits-a | 🟡 MEDIUM | High | Side exits |
| 3.4 | double-nested-loops-complex-cfg | 🔵 LOW | Very High | Double nested + complex CFG |
| 4.1 | sequence_2_loops | 🟡 MEDIUM | Medium | Sequential independence |
| 4.2 | complex-acyclic-cfg-with-4-self-loops | 🟡 MEDIUM | High | 4 independent self-loops |
| 5.1 | loop_nested_in_3_outer_loops_complex_cfg | 🟡 MEDIUM | Very High | 4-level nesting |
| 5.2 | if_else_with_loops_nested_in_2_outer_loops | 🔵 LOW | Very High | Conditional + nested |
| 6.1 | three-tier-ranking-nested-loops | ✅ HIGH | Medium | Ranking validation |

---

## Running the Tests

### Unit Tests (Recommended)

```bash
cd build/Debug
./unittests/Target/AMDGPU/AMDGPUTests --gtest_filter="*AllMirFiles*"
```

### Individual File via llc

```bash
./bin/llc -mtriple=amdgcn -mcpu=gfx1200 \
  -run-pass=amdgpu-next-use \
  -debug-only=amdgpu-next-use \
  path/to/test.mir -o /dev/null 2>&1 | grep -E "(Vreg:|Instr:|Block End)"
```

### Regenerate CHECK Patterns

```bash
python3 scripts/regenerate_nua_checks.py
```

---

## Key Implementation Details

### Distance Storage Convention

- **Negative stored values**: Finite distances (larger = closer)
- **Non-negative stored values**: LoopTag/DeadTag distances (smaller = closer)
- **`isCloserOrEqual(A, B)`**: Handles mixed-sign comparisons correctly

### Loop Boundary Detection

```cpp
// Loop-exiting edge adds LoopTag
if (LoopExits.contains(MBB->getNumber())) {
  EdgeWeight = LoopTag;
}

// Loop-entering edge (analysis direction) subtracts LoopTag
if (LI->getLoopDepth(MBB) < LI->getLoopDepth(Succ)) {
  // Transform distances for loop entry
}
```

### Subregister Handling

- Each `VRegMaskPair` tracks `(Register, LaneBitmask)`
- Overlap queries find minimum distance among overlapping masks
- Full register use covers all subregister queries

---

## Future Enhancements

1. **Subregister-specific tests**: Add tests with explicit sub0/sub1 tracking
2. **DeadTag validation**: Add tests where registers become truly dead
3. **PHI operand filtering**: Validate PHI operands only live on their incoming edge
4. **Performance benchmarks**: Track analysis time for large CFGs

---

*Document created: 2024-12-05*  
*Last updated: 2025-12-11*  
*Based on: llvm/test/CodeGen/AMDGPU/NextUseAnalysis/*.mir*

