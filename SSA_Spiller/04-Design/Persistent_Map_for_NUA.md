# Persistent Map for Next-Use Analysis (NUA)

Status: IDEA / RFE candidate  
Scope: Next Use Analysis optimization  
Audience: LLVM backend / SSA RA development  
Origin: internal design note (“Persistent Map Design.pdf”)
PDF source:
[06-Research/Notes/Persistent Map Design.pdf](06-Research/Notes/Persistent_Map_Design.pdf.md) <!-- TODO: file not found -->


---

## 1. Motivation

Current SSA-based Next Use Analysis (NUA) maintains **full per-instruction snapshots**
of `VRegDistances` to provide constant-time queries.

This guarantees correctness but costs:

Θ(I · K̄) memory

Where:
- I = number of instructions
- K̄ = average number of live virtual registers

For large functions this becomes prohibitively expensive.

---

## 2. Core Idea: Persistent Map (Functional Data Structure)

### What "Persistent" means here

Not disk persistence.

A persistent data structure is:

- immutable
- versioned
- structurally shared
- supports branching efficiently

Each update returns a **new version**, sharing most of its internal structure with the previous version.

Old versions remain valid.

---

### Why this helps

Instead of copying the entire map for each instruction:

- Only modified nodes are allocated
- Unchanged structure is reused

Memory usage now becomes proportional to:
> number of updates  
instead of  
> number of instructions × live-set size

---

## 3. LLVM Support

LLVM already provides:

llvm/ADT/ImmutableMap.h 


Properties:

- balanced tree
- structural sharing
- versioned keys
- cheap copy semantics
- well-tested

This is sufficient for implementing versioned NUA states.

---

## 4. Data Model

Two-layer persistent map:

Level 1: VReg -> Map<LaneMask, int64_t>  
Level 2: LaneMask -> Stored distance


Each instruction stores:

InstrVersion[I] = pointer to persistent map root


So:
- snapshot == pointer
- no replay
- no recomputation
- instant access

---

## 5. API Sketch

```cpp
// LaneMask key
struct LaneMaskKey {
  LaneBitmask Mask;
  void Profile(FoldingSetNodeID &ID) const {
    ID.AddInteger((uint64_t)Mask.getAsInteger());
  }
};

// VReg key
struct VRegKey {
  unsigned VReg;
  void Profile(FoldingSetNodeID &ID) const {
    ID.AddInteger(VReg);
  }
};

// Persistent maps
using PM_Lane = ImmutableMap<LaneMaskKey, int64_t>;
using PM_VReg = ImmutableMap<VRegKey, PM_Lane>;

struct PMapFactories {
  ImmutableMapFactory<LaneMaskKey, int64_t> F_Lane;
  ImmutableMapFactory<VRegKey, PM_Lane> F_VReg;
};

class PDist {
  PM_VReg Root;
  PMapFactories *F;

public:
  PDist(PMapFactories &Factories, PM_VReg R = PM_VReg())
    : Root(R), F(&Factories) {}

  // Lookup helpers
  const int64_t *lookupLane(unsigned VReg, LaneBitmask M) const;

  // Update helpers
  PDist insertMin(unsigned VReg, LaneBitmask M, int64_t Stored) const;
  PDist clearLane(unsigned VReg, LaneBitmask M) const;

  // Merge support (for CFG joins)
  PDist mergeRebased(const PDist &Succ,
                     int64_t SuccEntryOff,
                     int64_t EdgeWeight) const;
};```
## 6. Integration Into NUA

Each instruction stores one version:

`InstrVersion[I] = CurrRoot;`

Each operand updates the map functionally:

### Use:

`Curr = Curr.insertMin(VReg, Mask, -Offset);`

### Def:

`Curr = Curr.clearLane(VReg, Mask);`

### Merge:

`Curr = Curr.mergeRebased(SuccRoot, EntryOff[Succ], Weight);`

Each update returns a new root.

Old versions never change.

---

## 7. Complexity Analysis

### Update

O(log K̂) per modification  
(where K̂ is number of distinct live VRegs)

Each operand → one update

---

### Query

- O(1) to get snapshot pointer
    
- O(log K̂) for lookup
    

---

### Memory

Proportional to:

`(#changes) · log(K̂)`

instead of:

`I · K̄`

---

## 8. Trade-offs

### Advantages

✅ large memory reduction (3–10× expected)  
✅ per-instruction versioning  
✅ instant queries  
✅ immutable safety  
✅ SSA-friendly  
✅ no replay/recompute logic

---

### Disadvantages

⚠ higher update cost vs flat DenseMap  
⚠ ImmutableMap integration complexity  
⚠ Factory ownership must be managed carefully

---

## 9. Next Steps

1. Prototype PDist wrapper
    
2. Replace DenseMap snapshots
    
3. Benchmark memory usage
    
4. Benchmark compile-time impact
    
5. Validate merge behavior
    
6. Prepare LLVM RFE
    

---

## 10. Summary

Persistent maps allow:

- full snapshot semantics
    
- scalable memory usage
    
- SSA correctness
    
- minimal runtime complexity
    

This provides a principled improvement path for Next Use Analysis.

---

## Related

- [02-Components/Next Use Analysis](02-Components/Next_Use_Analysis.md) <!-- TODO: file not found -->
    
- [05-Testing/Next Use Analysis Tests](05-Testing/Next_Use_Analysis_Tests.md) <!-- TODO: file not found -->
    
- [04-Design/Architecture](04-Design/Architecture.md) <!-- TODO: file not found -->
    
- [03-Concepts/MIN Algorithm](03-Concepts/MIN_Algorithm.md) <!-- TODO: file not found -->
    
- [10-Backlog/Open problems](10-Backlog/Open_problems.md) <!-- TODO: file not found -->
    

---

## Source

Original draft: `Persistent Map Design.pdf`  
Location in vault: `06-Research/Notes/Persistent Map Design.pdf`


