### General observations.
  1. Works with uses/reloads dominated by the spill point.
          - that means all uses have NCD.
   2. Runs after all MBBs are processed to make possible RP change modeling.
### Algorithm:
- set Uses to all uses dominated by the current spill point.
- set best reload point to NCD(Uses)
- model RP change
     - if in limit - we are done
     - if not:
        - choose which use to evict from Uses and try model RP change.
             - if in limit - remove all uses whose NCD is the best reload point 
       - repeat until Uses empty.
#### How to choose which uses to evict: 
those on which path to NCD RP is out of limit.
#### How to model RP change?
1. Create temporary RPTracker and walk up to NCD from each use. Break if RP out of limit. 
     - Pro: no extra memory consumed.
     - Contra: Compile time demanding.
2. Record RP for each instruction while processing
     - Pro: fast in compile time
     - Contra: requires memory to save RP O(InstrNum * sizeof(unsigned short))
        - Better idea to store only max RP for each MBB.
#### What is still bad
1. we need DFS from the use to NCD for each use.

