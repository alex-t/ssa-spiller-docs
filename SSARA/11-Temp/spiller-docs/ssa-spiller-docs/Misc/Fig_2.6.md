```plantuml
@startuml
title Register sets explained

skinparam shadowing false
skinparam rectangle {
  FixedSize true
  MinWidth 150
  MinHeight 100
  HorizontalAlignment center
  VerticalAlignment middle
  BorderColor Black
  BackgroundColor White
  FontName Arial
  FontSize 12
}

rectangle "BB0:\nDef X\nDef Y" as BB0
rectangle "BB1:" as BB1
rectangle "BB4:\n<color:red>Spill Y</color>\n\nDef Z" as BB4
rectangle "BB2:\nUse Z\n****\n****\n****\n****\nUse X" as BB2
rectangle "BB3:\n<color:red><b><i>Reload Y</i></b></color>\n\nUse Y" as BB3

BB0 --> BB1
note left on link
  Active: X,Y
end note

BB0 --> BB4
note on link
  Active: X,Y
end note

BB1 --> BB2
note on link
  Active: X,Y
end note

BB4 --> BB2
note on link
  Active: X,Z
  Spilled: Y
end note

BB2 --> BB3

' Move callouts to BB3
note left of BB3
  Active: X,Z
end note

note right of BB3
  Spilled: Y
end note

note left of BB2
  Take: X
end note

note right of BB2
  Cand: Y,Z
end note

legend right
  Num Available Regs : 2
endlegend

@enduml
