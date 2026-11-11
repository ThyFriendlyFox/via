# The timing constraints of __TOP__. A line with a number ends with `;# source: <where it comes from>`.
create_clock -name clk -period 20 [get_ports clk] ;# source: fill: the requirement that states the clock; 20 ns is 50 MHz
set_input_delay 4 -clock clk [get_ports {rst en d[*]}] ;# source: fill: how long after the clock edge what drives the chip holds each input valid
set_output_delay 4 -clock clk [get_ports {q[*]}] ;# source: fill: how long before the clock edge what reads the chip needs each output
