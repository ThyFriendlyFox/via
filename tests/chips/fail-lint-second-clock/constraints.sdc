# The timing constraints of counter. A line with a number ends with `;# source: <where it comes from>`.
# The fault this fixture holds: line 4 makes the enable a second clock, and the first flow takes 1.
create_clock -name clk -period 20 [get_ports clk] ;# source: the fixture's premise: a 50 MHz clock
create_clock -name en_clk -period 40 [get_ports en] ;# source: the fixture's premise: the enable as a 25 MHz clock
set_input_delay 4 -clock clk [get_ports {rst en}] ;# source: the fixture's premise: an input is valid 4 ns after the clock edge
set_output_delay 4 -clock clk [get_ports {count[*]}] ;# source: the fixture's premise: an output is read 4 ns before the clock edge
