# The STA gate's OpenSTA script, run once for each corner in that corner's folder. vars.tcl gives the
# corner's liberty file and SPEF. The clock is propagated here, whatever the constraints say.
source vars.tcl
read_liberty $liberty
read_verilog $netlist
link_design $top
read_sdc $sdc
read_spef $spef
set_propagated_clock [all_clocks]
# Each net that joins 2 or more pins needs its wire: nets.txt names them, and the gate holds the SPEF to
# that list. OpenSTA gives a net the SPEF leaves out an estimate and says nothing. The supply nets are
# ports of the routed netlist and carry no signal: they are left out here, and the judge leaves them
# out of what check_setup lists.
set names [open $out/nets.txt w]
set signal_nets 0
foreach net [get_nets *] {
    set name [get_full_name $net]
    if {[lsearch -exact $supply_nets $name] >= 0} { continue }
    set joined [expr {[llength [get_pins -quiet -of_objects $net]] + [llength [get_ports -quiet -of_objects $net]]}]
    if {$joined >= 2} {
        puts $names $name
        incr signal_nets
    }
}
close $names
puts "WORKCENTER nets $signal_nets"
puts "WORKCENTER check_setup begin"
check_setup -verbose
puts "WORKCENTER check_setup end"
puts "WORKCENTER paths begin"
report_checks -path_delay max -format full_clock_expanded
report_checks -path_delay min -format full_clock_expanded
puts "WORKCENTER paths end"
# 4 digits: a slack of -0.004 ns is negative, and 2 digits print it as -0.00.
puts "WORKCENTER setup"
report_worst_slack -max -digits 4
puts "WORKCENTER hold"
report_worst_slack -min -digits 4
puts "WORKCENTER tns"
report_tns -digits 4
puts "WORKCENTER violators begin"
report_check_types -max_slew -max_capacitance -max_fanout -min_pulse_width -min_period -violators
puts "WORKCENTER violators end"
puts "WORKCENTER skew begin"
report_clock_skew -setup -digits 4
report_clock_skew -hold -digits 4
puts "WORKCENTER skew end"
write_sdf $out/$top.sdf
puts "WORKCENTER sta done"
