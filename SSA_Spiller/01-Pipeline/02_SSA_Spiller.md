# Pipeline Stage 2: SSA Spiller

*Early spilling to reduce register pressure while preserving SSA*

---

## Input

**SSA-form Machine IR**
- Single definition per virtual register
- Valid LiveIntervals
- May exceed physical register limits

## Function

**Reduce register pressure via spilling**
- Identify high-pressure points using register pressure tracking
- Select spill candidates using MIN/Belady algorithm (next-use distance)
- Store values at definition point (avoids EXEC drift)
- Insert reloads before uses
- Repair SSA form after reload insertion (PHIs at IDF)
- Lane-aware: operates on (VReg, LaneMask) pairs

## Output

**SSA-form Machine IR**
- Register pressure within physical limits
- Spill stores after definitions
- Reload instructions before uses
- SSA form preserved (new PHIs where needed)
- LiveIntervals updated

---

## Component

→ [[../02-Components/SSA_Spiller|SSA Spiller]]



