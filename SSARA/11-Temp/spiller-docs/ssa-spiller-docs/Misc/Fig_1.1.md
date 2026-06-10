```plantuml
@startuml
title Before SSA Updater

skinparam linetype ortho
skinparam rectangle {
  BorderColor Black
  BackgroundColor White
  FontName Arial
  FontSize 12
}

' Define nodes outside the red dotted grouping
rectangle "BB0: X Defined" as BB0
rectangle "BB2: BB2" as BB2
rectangle "BB7:\n**Use of X**" as BB7

' Group BB1, BB3, BB4, BB5, and BB6 inside a red dotted package with caption "dominated by BB1"
package "dominated by BB1" as Cluster {
  skinparam packageBorderColor red
  skinparam packageBorderThickness 1
  skinparam packageBorderStyle dotted

  rectangle "BB1:\n<color:red>Critical Reg Pressure</color>\n\n**X Spilled**" as BB1
  rectangle "BB3:\n**Use of X**" as BB3
  rectangle "BB4:\n**Use of X**" as BB4
  rectangle "BB5: BB5" as BB5
  rectangle "BB6:\n**Use of X**" as BB6
}

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
