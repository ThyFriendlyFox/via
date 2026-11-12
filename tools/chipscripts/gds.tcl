# The LAYOUT gate's Magic script: the placed and routed DEF with the library's cell layouts, as a GDS.
# The environment gives CELL_GDS, TECH_LEF, DEF, TOP and OUT; the process is the start file's.
if {![file exists $::env(DEF)]} { puts "ERROR: no placement file $::env(DEF)"; exit 2 }
drc off
gds readonly yes
gds rescale no
gds read $::env(CELL_GDS)
lef read $::env(TECH_LEF)
def read $::env(DEF)
load $::env(TOP) -dereference
select top cell
# Where 2 cells meet, Magic works the mask layers out again from its own view of both and writes them
# into the top cell. Those shapes differ from the kit's drawn ones by slivers that break its rule deck.
# The cells are drawn to stand side by side as they are: the top cell holds the wires alone. `cif help`
# does not list an option that starts with `*`.
cif *hier write disable
cif *array write disable
gds nodatestamp yes
gds write $::env(OUT)/$::env(TOP).gds
puts "WORKCENTER gds written"
quit -noprompt
