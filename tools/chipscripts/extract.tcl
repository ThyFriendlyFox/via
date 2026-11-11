# The LVS gate's Magic script: the layout's own netlist, device for device, with no parasitics.
# The environment gives GDS, TOP and OUT.
if {![file exists $::env(GDS)]} { puts "ERROR: no layout file $::env(GDS)"; exit 2 }
gds read $::env(GDS)
load $::env(TOP) -dereference
select top cell
if {[llength [cellname list children $::env(TOP)]] == 0} { puts "ERROR: cell $::env(TOP) is empty"; exit 2 }
extract do local
extract no capacitance
extract no coupling
extract no resistance
extract no adjust
extract unique
extract
ext2spice lvs
ext2spice -o $::env(OUT)/$::env(TOP).lvs.spice $::env(TOP).ext
feedback save $::env(OUT)/extract.feedback.txt
puts "WORKCENTER extracted"
quit -noprompt
