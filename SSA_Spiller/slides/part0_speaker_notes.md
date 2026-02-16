# Part 0 — Speaker Notes

Use these notes on a side screen during the presentation.
Each section corresponds to one slide. Key phrases are **bolded**.

---

## Slide 1: Title

> Good [morning/afternoon]. Today I'm presenting a technical comparison of two Next Use Analysis implementations for the AMDGPU backend. This work is part of the SSA Spiller project, based on the Braun & Hack CC'09 paper on register spilling for SSA-form programs.
>
> The goal: determine which NUA implementation is technically stronger and should be adopted.

---

## Slide 2: Agenda

> Quick roadmap. **Part 0** — the one we're starting now — gives you the punchline first: performance numbers, scaling behavior, and the key architectural insight.
>
> Parts 1 through 4 go deeper: our design, their design, trade-offs, and the final decision. But Part 0 should give you enough to understand the conclusion.

---

## Slide 3: Part 0 Header

> *[Transition slide — brief pause]*
>
> Let's jump into performance at a glance.

---

## Slide 4: Two Algorithms, One Problem

> Both implementations solve the same problem — computing next-use distances for register spilling — but with **fundamentally different architectures**.
>
> **Our approach (ML NUA)**: classical backward dataflow. One upfront pass over the function, O(iter × blocks × instructions). After that, every query is an **O(1) table lookup**. Integer arithmetic, 2 pass dependencies.
>
> **Their approach (Graphics NUA)**: lazy, on-demand. No upfront cost — computation is deferred to query time. Each query runs **Dijkstra + BFS** over the CFG. Floating-point arithmetic, 5 pass dependencies.
>
> Look at the complexity table at the bottom. The key difference: **per spill point**, we do O(Q) lookups while they do O(Q × V × (V+E)) — that's Q Dijkstra runs, each touching the entire CFG.
>
> Important caveat: their implementation **caches** shortest path results per block pair, so repeated queries for the same (From, To) pair are O(1). The worst case only applies to cold cache misses. We'll see the actual numbers next.

---

## Slide 5: Why On-Demand Loses at Spill Points

> This is the key insight. **At every spill point**, the spiller needs distances for **every live register** — it's doing Belady's MIN to pick the best eviction candidate.
>
> On AMDGPU, that's **64 to 256 live registers** at a typical spill point.
>
> For us: 64–256 registers × O(1) lookup = **128 to 512 operations**. That's it.
>
> For them: each register triggers Dijkstra + BFS = roughly 25K operations per register. Multiply by 64–256 registers = **1 million to 1.75 million operations** per spill decision.
>
> That's a **~3,000× difference** per spill point. And a typical function may have dozens or hundreds of spill points.
>
> To be fair — their caching helps with repeated block pairs. The "Repeated spill points" row shows that. But each new unique (From, To) pair still triggers a fresh Dijkstra.

---

## Slide 6: Empirical Benchmark — Full Test Suite (Initial)

> Here are the actual numbers. 20 test cases, ranging from 8K to 664K in size. Debug builds, gfx1200, median of 3 runs.
>
> **ML NUA is faster on all 20 tests.** The speedup ranges from **1.03× to 1.58×**.
>
> The largest test — `nested-loops-side-exits-b` at 664K — shows the biggest gap: 0.204s vs 0.323s, a **1.58× speedup**.
>
> Note the methodology: we run the analysis eagerly (no dump needed), they require the `-dump-distance` flag to force computation. Both measurements are wall-clock time for the analysis pass only.

---

## Slide 7: Updated Benchmark — After GFX Improvement

> This is the second benchmark round, after the Graphics NUA received an implementation update.
>
> Two things to note. First, on the **10 valid tests**, ML NUA is still faster: **1.05× to 1.44× range**. The gap narrowed slightly on some tests but the direction didn't change.
>
> Second — and this is important for context — **9 out of 20 tests crash** the Graphics NUA. All 9 involve loops. These crashes happen in the debug dump path when `printAllDistances()` sends unfiltered use lists to the distance computation. The normal spiller path is protected by `getUses()` which pre-filters unreachable uses.
>
> One test (`test0_ssa`) is invalid SSA — both implementations correctly reject it.

---

## Slide 8: Performance Gap Charts

> Two scatter plots showing the performance gap correlates with input characteristics.
>
> **Left chart**: input size (KB) vs. time delta (GFX minus ML, in seconds). The trend line shows the gap **grows with input size**. The 664K test is the clear outlier on the right.
>
> **Right chart**: subreg operand count vs. time delta. More subregister operands means more complex lane-mask work. Again, **positive correlation** — the more complex the input, the bigger ML NUA's advantage.

---

## Slide 9: Scaling Benchmark Results

> To isolate the scaling behavior, we generated synthetic acyclic MIR tests with controlled BB counts: 16, 32, 64, 128, 256, 512, 1024 basic blocks.
>
> Look at the ratio column. At 16 BBs: **1.18×** — barely noticeable. At 64 BBs: **2×**. At 128 BBs: **12×**. It peaks and then settles around **6–9×** for larger inputs.
>
> The cliff happens around **100 basic blocks** — that's where the quadratic nature of on-demand Dijkstra starts dominating. For real-world AMDGPU shaders, functions with 100+ BBs are common in complex kernels.

---

## Slide 10: Compile-Time Scaling Plot

> Same data as the table, but visualized. The blue line (ML NUA) grows **linearly**. The red line (Graphics NUA) shows **super-linear growth** — it takes off around 100 BBs.
>
> The gray dashed line shows the absolute gap in seconds. It keeps growing — meaning the problem gets worse, not better, with larger inputs.

---

## Slide 11: Empirical vs. Theoretical Growth

> This chart overlays the Graphics NUA empirical data against theoretical O(n·log n) and O(n²) curves.
>
> The red squares (actual measurements) track **between the two bounds**, consistent with the Dijkstra+BFS complexity. It's super-linear but not quite quadratic — which matches our analysis that caching reduces the practical exponent below the worst case.

---

## Slide 12: Blender Cycles GPU Kernel

> The stress test. Blender Cycles GPU kernel — a real production shader. **309 functions, 83K basic blocks, 1.9 million instructions**. The largest single function has 9,743 BBs.
>
> Results: ML NUA finishes in **21 minutes**. Graphics NUA **crashes at 86 minutes** with SIGSEGV.
>
> That's **4× faster** — and the only one that actually completes.
>
> Important context: both were run with `-dump-distance` flag, which means the crash is in the debug dump path — `printAllDistances()` sending unfiltered uses. But even without the crash, the 4× wall-clock difference reflects real computational cost.

---

## Slide 13: Source Code Walkthrough

> Let me show you where the cost comes from in the source code.
>
> **Left side**: the call chain for a single query. `getNextUseDistance()` calls `calcDistanceToUse()` for each use operand, which calls `calcShortestDistance()`, which calls `calcShortestPath()` — that's **Dijkstra**. Inside Dijkstra, for each successor edge, `pathInfoFor()` triggers `mutPathInfoFor()`, which calls `calcIsReachable()` — that's a **full BFS** per block pair.
>
> **The verdict box**: worst case (cold cache) is O(V × (V+E)) per query. But — and this is an important nuance — results are **cached per (From, To) pair**. Cache hit is O(1). So the amortized cost is O(P × V·log V) where P is the number of unique block pairs actually queried. In practice, many registers share the same block pairs, so caching helps significantly.
>
> **Right side**: the actual Dijkstra code with the key detail — `gfxMode()` **skips backedges**, which means loop latches become unreachable from the header. And the BFS reachability check that visits up to V+E nodes per pair.

---

## Slide 14: Debug Dump Path Issues

> This slide addresses the assertion failures we saw in the benchmark.
>
> **Left side, top** (orange): `printAllDistances()` — the debug dump function. It collects ALL register uses via `MRI->use_nodbg_operands()` without calling `getUses()`. This means unreachable uses and backward same-block uses are passed directly to the distance computation, which then asserts.
>
> **Left side, bottom** (green): the normal spiller path through `computeLiveRegUses()`. It calls `getUses()` first, which filters uses via `isDistanceFinite()` (GFX mode, runs Dijkstra) or `isReachable()` (ML mode, runs BFS). Only reachable, correctly-ordered uses reach the distance computation. **No crash**.
>
> **Right side**: the scope table. Normal spiller operation: **not affected**. The `-dump-distance` debug flag: **affected**. The `-dump-distance-as-json` flag: **not affected** (it goes through `computeLiveRegUses`).
>
> Bottom line: this is a **debug-path-only issue**, not a production correctness problem. But it does indicate that the API boundary between `getUses()` and `getNextUseDistance()` is fragile — callers must remember to filter first.

---

## Slide 15: Technical Summary

> Wrapping up Part 0. **The ML NUA is the technically stronger implementation.**
>
> **Architecture**: classical dataflow with provable convergence versus demand-driven Dijkstra with a 7-level call hierarchy.
>
> **Correctness**: the debug dump path has unfiltered-use issues; the normal spiller path is protected. Our implementation has no equivalent issues — analysis is precomputed, queries are table lookups.
>
> **Performance**: faster or equal on all valid tests, 1.05× to 1.44× range. Advantage grows with CFG complexity.
>
> **Maintainability**: 2 pass dependencies vs 5. Single code path vs gfx/ML mode bifurcation. Comprehensive design docs.
>
> **Spiller integration**: native VRegMaskPair API, O(1) snapshots, lane-sorted subreg queries, precomputed block summaries.
>
> This conclusion holds across two benchmark rounds, including after the Graphics NUA received improvements.
>
> *[Pause]* Questions on Part 0 before we dive into the design details?
