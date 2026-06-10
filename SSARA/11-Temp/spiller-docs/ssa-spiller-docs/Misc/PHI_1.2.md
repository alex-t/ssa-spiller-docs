```plantuml
@startuml
title Def on the one path

skinparam shadowing false
skinparam rectangle {
  BorderColor Black
  BackgroundColor White
  FontName Arial
  FontSize 12
}

' Define basic blocks with required text formatting
rectangle "BB0:\nDef X\n\nDef Y" as BB0
rectangle "BB1:\n<color:red>Spill Y</color>\n\nDef Z" as BB1
rectangle "BB4:\n<color:red>Spill Y</color>" as BB4
rectangle "BB2:\nW = PHI([Z,BB1],[X,BB4])" as BB2
rectangle "BB3:\n<b>Use W</b>\n\nUse X\n\n<color:red>Reload Y</color>\n\nUse Y" as BB3

' Define CFG edges with callouts
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

' Updated Callout for BB1
note right of BB1
  Active: X,Z
end note

' Updated Callout for BB4
note right of BB4
  Active: X
end note

' Updated Callout for BB2
note left of BB2
  Take: X
end note

note right of BB2
  Cand: Z
end note

@enduml
