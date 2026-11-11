# The DRC gate's Magic script: every rule of the technology file on the whole layout. It writes each
# rule that is broken with its boxes, and the count. The environment gives GDS, TOP and OUT.
if {![file exists $::env(GDS)]} { puts "ERROR: no layout file $::env(GDS)"; exit 2 }
gds read $::env(GDS)
load $::env(TOP)
select top cell
if {[llength [cellname list children $::env(TOP)]] == 0} { puts "ERROR: cell $::env(TOP) is empty"; exit 2 }
expand
drc euclidean on
drc style drc(full)
drc check
drc catchup
set result [drc listall why]
set oscale [cif scale out]
set count 0
set f [open $::env(OUT)/magic.rpt w]
foreach {why boxes} $result {
    puts $f $why
    foreach b $boxes {
        puts $f [format " %.3fum %.3fum %.3fum %.3fum" [expr {$oscale*[lindex $b 0]}] [expr {$oscale*[lindex $b 1]}] \
            [expr {$oscale*[lindex $b 2]}] [expr {$oscale*[lindex $b 3]}]]
        incr count
    }
}
puts $f "WORKCENTER drc count $count"
close $f
puts "WORKCENTER drc count $count"
quit -noprompt
