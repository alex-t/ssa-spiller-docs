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
rectangle "BB1:\nDef Z" as BB1
rectangle "BB4:" as BB4
rectangle "BB2:\n<color:red>W = PHI([Z,BB1],[X,BB4])</color>" as BB2
rectangle "BB3:\n<color:red><b>Use W</b></color>\n\nUse X\n\nUse Y" as BB3

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

' Callouts for BB1 and BB4
note right of BB1
  Active: X,Y,Z
end note

note right of BB4
  Active: X,Y
end note

' New Callout for BB2
note right of BB2
  There must be PHI node to select the value!
end note

@enduml
