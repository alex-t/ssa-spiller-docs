# Weekly Plan — SSA Regalloc

## Focus: Stabilize Testing & Theory Structure

This week is about aligning tests with the *actual* design
and creating a clean conceptual layer for the project.

---

## 1. SSA Spiller — Testing Strategy REWORK

### Problem
Current SSA Spiller tests reflect the *old design*:
- WWM-based execution masks
- Split-before-use
- Pre-store transforms

These tests no longer reflect reality.

### Goal
Rewrite testing strategy according to the **physical spill + virtual spill point model**:

- Single store at definition
- Kill-index based virtual spill points
- Reachability-based rewrite of dominated uses
- SSA repair after reload
- No WWM
- No split-before-use logic

### Tasks
- Review:
  - `SSA_SPILLING_TEST_PATTERNS.md`
  - existing MIR tests
- Classify:
  - still valid
  - obsolete
  - misleading
- Redesign patterns:
  - store-once
  - dominated rewrite
  - reload placement
  - subregister behavior

### Output
- Updated: 05-Testing/SSA_Spiller/SSA Spilling Test Patterns.md
- Delete / archive:
- WWM-based patterns
- split-before-use logic
- Write new canonical patterns.

---

## 2. NUA — Testing Strategy REVISION

### Problem
Current MIR naming/annotations lie about CFG structure:
- “loops” that are not loops
- “branches” that are merges
- misleading file names
- unclear dominance

This damages trust in tests.

### Goal
Make NUA tests:
- honest
- structural
- dominance-accurate

### Tasks
- Rename MIR tests to reflect:
- loop vs non-loop
- join vs branch
- backedge vs merge
- Revise annotations:
- CFG diagrams
- dominance notes
- Remove misleading comments
- Align naming with:
- semantic meaning
- LoopTag contract
- DeadTag logic

### Output
- Cleaned MIR test set
- Updated documentation: 05-Testing/Next_Use_Analysis/Test Patterns.md
- Clean matches between graph shape and file names.

---

## 3. Generate Concept Stubs

### Goal
Create canonical concept pages to make SSA RA explainable,
reviewable, and navigable.

### Required stubs

Create files under: 03-Concepts/

#### Primary
- SSA Deconstruction
- PHI Copies & Permutations
- MIN Algorithm (Belady)
- Next Use Analysis
- LoopTag
- Live Range Splitting
- Virtual Spill Point

#### Optional
- Perfect Elimination Order
- Chordal graphs
- SSA Interference
- Dominance vs Interference
- Subregister Liveness

### Content template
Each stub should contain:
- Definition
- Rationale
- Consequences
- References
- Link to paper
- Link to pipeline stage

### Output
- Clean `03-Concepts/`
- No theory hidden inside NOTES.md or PDFs.

---
## 4. Review AI-Generated Documents

### Problem
Documents extracted from `NOTES.md` by AI may contain:
- outdated conclusions
- design mismatches
- historical artifacts
- misclassification
- speculative wording

They must not silently become “truth”.

### Goal
Validate every generated document manually and turn:
> extracted text → canonical design

### Tasks
- Review all markdown files generated from NOTES:
  - confirm correctness
  - delete obsolete content
  - rewrite unclear sections
  - add missing implementation details
- Compare against:
  - current code
  - weekly decisions
  - true architecture
- Explicitly mark:
  - historical sections
  - rejected ideas
  - current design
- Clean false assumptions.
### Output
- All `.md` files reflect:
  ✅ actual implementation  
  ✅ confirmed architecture  
  ✅ agreed direction  
- No AI guesswork remains unverified.

---

## 5. NOTES Auto-Sync (Server → Obsidian)

### Problem
NOTES is updated on the server by AI and Cursor,  
Obsidian runs locally.

Manual sync is error-prone and breaks continuity.

### Goal
Make Obsidian mirror NOTES in near-real-time.

---

## Implementation

### Strategy
Laptop periodically pulls from server over SSH.

---

### Option A — Manual sync command
One-shot update when needed:

```scp user@server:/path/to/NOTES.md ~/Obsidian/Vault/08-Worklog/History.md```

---
### Option B — Background autosync loop (recommended)

```
while true; do
  scp user@server:/path/to/NOTES.md \
      ~/Obsidian/Vault/08-Worklog/History.md
  sleep 30
done
```

---
### Optional: Optimized via rsync

```
while true; do
  rsync -az user@server:/path/to/NOTES.md \
           ~/Obsidian/Vault/08-Worklog/History.md
  sleep 30
done
```


---
## Result

✅ Obsidian always shows the latest log
✅ No desync
✅ No manual copying
✅ AI memory becomes visible live
✅ Obsidian becomes your memory mirror

## Status

- [ ] SSA Spiller tests rewritten
- [ ] NUA tests cleaned & renamed
- [ ] Concept stubs created
- [ ]  AI-generated docs reviewed
- [ ] Auto-sync script installed

---

## Notes

This week is about:
> Making the system reviewable  
> Making tests truthful  
> Making theory explicit  
> Killing legacy artifacts  



