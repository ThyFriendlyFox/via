# The timing constraints of counter. A line with a number ends with `;# source: <where it comes from>`.
# The fault this fixture holds: a 5 ns period, which the typical corner meets and the slow corner misses.
create_clock -name clk -period 5 [get_ports clk] ;# source: the fixture's premise: a 200 MHz clock
set_input_delay 4 -clock clk [get_ports {rst en}] ;# source: the fixture's premise: an input is valid 4 ns after the clock edge
set_output_delay 4 -clock clk [get_ports {count[*]}] ;# source: the fixture's premise: an output is read 4 ns before the clock edge
