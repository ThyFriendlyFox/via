# The timing constraints of acc8. A line with a number ends with `;# source: <where it comes from>`.
create_clock -name clk -period 40 [get_ports clk] ;# source: the fixture's premise: a 25 MHz clock
set_input_delay 4 -clock clk [get_ports {rst boot[*] in_port[*]}] ;# source: the fixture's premise: an input is valid 4 ns after the clock edge
set_output_delay 4 -clock clk [get_ports {out_port[*] out_valid halted}] ;# source: the fixture's premise: an output is read 4 ns before the clock edge
