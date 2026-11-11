// acc8: an 8-bit accumulator processor with its program in a ROM.
//
//   clk        the 1 clock; every flip-flop takes its rising edge
//   rst        synchronous reset, active high
//   boot       the ROM slot (0 to 3) the program starts in, read while rst is high
//   in_port    read by the IN instruction on the clock edge that ends it
//   out_port   the last value an OUT instruction wrote
//   out_valid  high for the 1 cycle after an OUT instruction
//   halted     high after a HLT instruction, until the next reset

`default_nettype none

module acc8 (
    input  wire       clk,
    input  wire       rst,
    input  wire [1:0] boot,
    input  wire [7:0] in_port,
    output wire [7:0] out_port,
    output wire       out_valid,
    output wire       halted
);

    wire [7:0]  rom_addr;
    wire [12:0] rom_data;

    acc8_rom u_rom (
        .addr (rom_addr),
        .data (rom_data)
    );

    acc8_core u_core (
        .clk       (clk),
        .rst       (rst),
        .boot      (boot),
        .rom_addr  (rom_addr),
        .rom_data  (rom_data),
        .in_port   (in_port),
        .out_port  (out_port),
        .out_valid (out_valid),
        .halted    (halted)
    );

endmodule

`default_nettype wire
