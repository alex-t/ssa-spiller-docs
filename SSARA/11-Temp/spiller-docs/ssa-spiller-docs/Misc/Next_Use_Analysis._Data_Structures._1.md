```plantuml
@startuml

skinparam linetype ortho
skinparam dpi 150
top to bottom direction

rectangle "MachineInstr* MI" as MI

' Define the main vertical chain
rectangle "VReg_1" as V1
rectangle "VReg_2" as V2
rectangle "VReg_3" as V3
rectangle "VReg_4" as V4
rectangle "VReg_5" as V5
rectangle "VReg_6" as V6

MI --> V1
V1 --> V2
V2 --> V3
V3 --> V4
V4 --> V5
V5 --> V6

' Define subregister hierarchy for VReg_1 positioned beside it
package "std::set (Red-Black Tree) sorted ascending by insertion" {
    skinparam packageBorderColor red
    skinparam packageBackgroundColor white
    skinparam packageStyle dashed
    rectangle "subreg1:2" as V1_1
    rectangle "subreg0:4" as V1_2
    V1 -right-> V1_1
    V1_1 -right-> V1_2
}

' Define subregister hierarchy for VReg_2 positioned beside it
rectangle "subreg2:5" as V2_1
rectangle "subreg2_3:14" as V2_2
rectangle "full_reg:25" as V2_3

V2 -right-> V2_1
V2_1 -right-> V2_2
V2_2 -right-> V2_3

@enduml


