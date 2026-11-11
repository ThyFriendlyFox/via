// counter: an 8-bit counter with an enable.
// The rules the gates hold: 1 clock, a reset on every flop, no latch, no loop of gates.
module counter (
    input  wire       clk,   // the 1 clock; every flop takes its rising edge
    input  wire       rst,   // synchronous reset, active high: the count becomes 0
    input  wire       en,    // count up by 1 on the next rising edge; without it the count holds
    output reg  [7:0] count  // wraps from 255 to 0
);
    always @(posedge clk) begin
        if (rst) count <= 8'd0;
        else if (en) count <= count + 8'd1;
    end
endmodule
