```plantuml
@startuml
title Updated MachineSSAUpdater PHI Insertion

skinparam linetype ortho
skinparam rectangle {
  BorderColor Black
  BackgroundColor White
  FontName Arial
  FontSize 12
}

' Define basic blocks with labels and formatting
rectangle "BB0: X Defined" as BB0
rectangle "BB1:\n<color:red>Critical Reg Pressure</color>\n\n**X Spilled**" as BB1
rectangle "BB2: BB2" as BB2
rectangle "BB3:\n<color:red>Reload: Y = RELOAD spillslot(X)</color>\n\n**Use of Y**" as BB3
rectangle "BB4:\n**Use of Y**" as BB4
rectangle "BB5: BB5" as BB5
rectangle "BB6:\n**Use of Y**" as BB6
rectangle "BB7:\n**<color:green>Z = PHI([X, BB2], [Y, BB6])</color>**\n\n**Use of <color:green>Z</color>**" as BB7

' Define edges using vertical (down) connectors
BB0 -down-> BB1
BB0 -down-> BB2
BB1 -down-> BB3
BB3 -down-> BB4
BB3 -down-> BB5
BB4 -down-> BB6
BB5 -down-> BB6
BB6 -down-> BB7
BB2 -down-> BB7

@enduml
