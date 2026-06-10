x dominates its group.
to make it spilled at the group dominator we need:
x is active
x is used last in dom group
all regs having D > D(x) data dependent on x and defined after x's group
therefore all regs after x's group aren't yet defined

all live regs in x's group before use x last used before use x

Hence:  instruction uses x should compute the final result value computed in group
all values after the group need x to be defined

def x

HIGH RP  :  a1, b1 not yet defined, a0, b0, d0 have closer uses => spill x

a1 = a0 + b0              here is the same for y
b1 = a1 + d0
.....
fin_x = x + b1               fin_y = y + g1
         \                     /
           \                 /
           some_value = fin_x + fin_y
           
```mermaid
flowchart TD
  bb0[bb0: entry] --> bb1[bb1: dg1_header<br/>define x, high RP]
  bb1 -->|uniform branch| bb2[bb2: dg1_pathA<br/>use a0.., keep pressure]
  bb1 -->|uniform branch| bb3[bb3: dg1_pathB<br/>use a0.., keep pressure]
  bb2 --> bb4[bb4: dg1_join <br/>compute fin_x = x + b1;<br/>use of x]
  bb3 --> bb4

  bb4 --> bb5[bb5: dg2_header <br/>define y, high RP]
  bb5 -->|uniform branch| bb6[bb6: dg2_pathA<br/>use g0..]
  bb5 -->|uniform branch| bb7[bb7: dg2_pathB<br/>use g0..]
  bb6 --> bb8[bb8: dg2_join<br/>compute fin_y = y + g1;<br/>use of y]
  bb7 --> bb8

  bb8 --> bb9[bb9: exit<br/>some_value = fin_x + fin_y;<br/>store]

