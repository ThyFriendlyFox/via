# The LVS gate's Netgen script: the extracted layout against the final netlist with its supply pins.
# The environment gives LAYOUT_SPICE, CELL_SPICE, NETLIST, SETUP, TOP and OUT.
foreach v {LAYOUT_SPICE CELL_SPICE NETLIST SETUP} {
    if {![file exists $::env($v)]} { puts "ERROR: no file $::env($v) ($v)"; exit 2 }
}
set layout [readnet spice $::env(LAYOUT_SPICE)]
set source [readnet spice $::env(CELL_SPICE)]
readnet verilog $::env(NETLIST) $source
lvs "$layout $::env(TOP)" "$source $::env(TOP)" $::env(SETUP) $::env(OUT)/lvs.rpt -json
puts "WORKCENTER lvs done"
