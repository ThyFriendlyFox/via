# The LAYOUT gate's OpenROAD script: a mapped netlist to a routed database. tools/chipback.py writes
# vars.tcl in the folder this runs in; every value of the process comes from there, none is written here.
source vars.tcl

read_lef $tech_lef
read_lef $cell_lef
read_liberty $liberty
read_verilog $netlist
link_design $top
read_sdc $sdc

if {$die_area ne ""} {
    initialize_floorplan -die_area $die_area -core_area $core_area -site $site
} else {
    initialize_floorplan -utilization $utilization -aspect_ratio 1.0 -core_space $core_space -site $site
}
source tracks.tcl
place_pins -hor_layers $pin_layer_h -ver_layers $pin_layer_v
tapcell -distance $tap_distance -tapcell_master $tap_cell

set_wire_rc -signal -layer $wire_rc_signal
set_wire_rc -clock -layer $wire_rc_clock
global_placement -density $density
detailed_placement
check_placement -verbose

clock_tree_synthesis -root_buf $clock_root -buf_list $clock_buffers
# From here on the clock is the tree that was built, not an ideal one: hold means nothing before this.
set_propagated_clock [all_clocks]
repair_clock_nets
detailed_placement
estimate_parasitics -placement
repair_timing -setup
repair_timing -hold
detailed_placement
check_placement -verbose
filler_placement $fill_cells
check_placement -verbose
puts "WORKCENTER placement checked"

foreach pin $power_pins { add_global_connection -net $power_net -inst_pattern .* -pin_pattern "^$pin$" -power }
foreach pin $ground_pins { add_global_connection -net $ground_net -inst_pattern .* -pin_pattern "^$pin$" -ground }
set_voltage_domain -name CORE -power $power_net -ground $ground_net
define_pdn_grid -name grid -voltage_domains CORE -pins $stripe_layer
add_pdn_stripe -grid grid -layer $rail_layer -width $rail_width -followpins
# A stripe of each supply net must cross the core, or the rails of 1 net stay apart. The table's pitch
# suits a core wider than itself; a narrower core takes its own width as the pitch.
set core [[ord::get_db_block] getCoreArea]
set core_width [expr {([$core xMax] - [$core xMin]) / double([[ord::get_db_block] getDbUnitsPerMicron])}]
if {$stripe_pitch > $core_width} {
    set stripe_pitch $core_width
    set stripe_offset [expr {$core_width / 4.0}]
}
add_pdn_stripe -grid grid -layer $stripe_layer -width $stripe_width -pitch $stripe_pitch -offset $stripe_offset
add_pdn_connect -grid grid -layers [list $rail_layer $stripe_layer]
pdngen
foreach net [list $power_net $ground_net] {
    if {[catch {check_power_grid -net $net} said]} {
        puts "WORKCENTER grid $net open: $said"
    } else {
        puts "WORKCENTER grid $net connected"
    }
}

set_routing_layers -signal $route_bottom-$route_top -clock $route_bottom-$route_top
global_route -guide_file $out/route.guide -congestion_iterations 50 -verbose
detailed_route -guide $out/route.guide -output_drc $out/route_drc.rpt -output_maze $out/maze.log \
    -bottom_routing_layer $route_bottom -top_routing_layer $route_top -verbose 1
puts "WORKCENTER routed"

write_def $out/$top.def
write_verilog $out/$top.v
write_verilog -include_pwr_gnd $out/$top.pwr.v
write_db $out/$top.odb

define_process_corner -ext_model_index 0 X
foreach {wire rules} $rcx {
    extract_parasitics -ext_model_file $rules
    write_spef $out/$top.$wire.spef
}
report_design_area
puts "WORKCENTER layout written"
