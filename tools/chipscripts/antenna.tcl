# The ANTENNA gate's OpenROAD script: the routed database against the antenna rules of its LEF.
source vars.tcl
read_db $database
check_antennas -report_file $out/antenna.rpt
puts "WORKCENTER antenna done"
