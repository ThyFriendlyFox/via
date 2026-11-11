# The STA gate's OpenSTA script, run once for each corner in that corner's folder. vars.tcl gives the
# corner's liberty file and SPEF. The clock is propagated here, whatever the constraints say.
source vars.tcl
read_liberty $liberty
read_verilog $netlist
link_design $top
read_sdc $sdc
read_spef $spef
set_propagated_clock [all_clocks]
# The supply nets are ports of the routed netlist and carry no signal: they are not counted, and the
# judge leaves them out of what check_setup lists.
set signal_nets 0
foreach net [get_nets *] {
    if {[lsearch -exact $supply_nets [get_full_name $net]] < 0} { incr signal_nets }
}
puts "WORKCENTER nets $signal_nets"
puts "WORKCENTER check_setup begin"
check_setup -verbose
puts "WORKCENTER check_setup end"
report_checks -path_delay max -format full_clock_expanded
report_checks -path_delay min -format full_clock_expanded
puts "WORKCENTER setup"
report_worst_slack -max
puts "WORKCENTER hold"
report_worst_slack -min
report_tns
puts "WORKCENTER violators begin"
report_check_types -max_slew -max_capacitance -max_fanout -min_pulse_width -min_period -violators
puts "WORKCENTER violators end"
puts "WORKCENTER skew begin"
report_clock_skew
puts "WORKCENTER skew end"
write_sdf $out/$top.sdf
puts "WORKCENTER sta done"
