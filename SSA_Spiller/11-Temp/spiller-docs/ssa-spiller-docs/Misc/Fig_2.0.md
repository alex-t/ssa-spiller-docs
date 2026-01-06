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
rectangle "BB3:\nUse Y" as BB3

BB0 --> BB1
note left on link
  Active: X,Y
end note

BB0 --> BB4
note on link
  Active: X,Y
end note

BB1 --> BB2
BB4 --> BB2
BB2 --> BB3

legend right
  Num Available Regs : 2
endlegend

@enduml
