// __TOP__: an 8-bit register with an enable. Replace the body with the design.
// The rules the gates hold: 1 clock, a reset on every flop, no latch, no loop of gates.
module __TOP__ (
    input  wire       clk,  // the 1 clock; every flop takes its rising edge
    input  wire       rst,  // synchronous reset, active high
    input  wire       en,   // load d on the next rising edge
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always @(posedge clk) begin
        if (rst) q <= 8'd0;
        else if (en) q <= d;
    end
endmodule
