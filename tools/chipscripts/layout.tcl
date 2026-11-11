# The LAYOUT gate's OpenROAD script: a mapped netlist to a routed database. tools/chipback.py writes
# vars.tcl in the folder this runs in; every value of the process comes from there, none is written here.
source vars.tcl

read_lef $tech_lef
read_lef $cell_lef
read_liberty $liberty
read_verilog $netlist
link_design $top
read_sdc $sdc

# The part of the core the cells take, fill cells left out: the number the project's limit holds. It is
# counted from the database, so it is the same number at each step of the build.
proc utilization {fill_cells} {
    set block [ord::get_db_block]
    set core [$block getCoreArea]
    set cells 0.0
    foreach inst [$block getInsts] {
        set master [$inst getMaster]
        if {[lsearch -exact $fill_cells [$master getName]] < 0} {
            set cells [expr {$cells + double([$master getWidth]) * [$master getHeight]}]
        }
    }
    set unit [expr {double([$block getDbUnitsPerMicron])}]
    set area [expr {double([$core xMax] - [$core xMin]) * ([$core yMax] - [$core yMin])}]
    return [list [expr {$cells / $area}] [expr {$cells / ($unit * $unit)}]]
}

if {$die_area ne ""} {
    initialize_floorplan -die_area $die_area -core_area $core_area -site $site
} else {
    initialize_floorplan -utilization $utilization -aspect_ratio 1.0 -core_space $core_space -site $site
}
source tracks.tcl
place_pins -hor_layers $pin_layer_h -ver_layers $pin_layer_v
tapcell -distance $tap_distance -tapcell_master $tap_cell

# The clock tree and the timing repair only add cells. A netlist that is over the project's limit here,
# or that does not fit the core at all, stays so: the build stops before its long steps, and the gate
# judges the number printed.
set used [lindex [utilization $fill_cells] 0]
puts [format "WORKCENTER utilization %.4f after the floorplan" $used]
if {$used > 1.0 || ($utilization_limit ne "" && $used > $utilization_limit)} {
    puts "WORKCENTER stopped: the cells take more of the core than it may hold"
    exit
}
# The placer spreads the cells to the table's density, and stops with an error when they take more of
# the core than that. On such a core the density is what the cells take, with room for the cells the
# build adds.
if {$used > $density} {
    set density [expr {min(1.0, $used + $density_headroom)}]
}
puts [format "WORKCENTER density %.4f" $density]

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

# A pin of a cell that takes a signal or a supply and is on no net floats. An output may stay open.
set open_pins 0
foreach inst [[ord::get_db_block] getInsts] {
    foreach pin [$inst getITerms] {
        if {[$pin getNet] eq "NULL" && [$pin getIoType] ne "OUTPUT"} {
            incr open_pins
            if {$open_pins <= 5} { puts "WORKCENTER open pin [$inst getName]/[[$pin getMTerm] getName]" }
        }
    }
}
puts "WORKCENTER open pins $open_pins"

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
lassign [utilization $fill_cells] used cells
puts [format "WORKCENTER utilization %.4f of the core, %.2f um2 of cells" $used $cells]
puts "WORKCENTER layout written"
