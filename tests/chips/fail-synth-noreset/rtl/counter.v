// counter: an 8-bit counter whose enable is registered once.
// The fault this fixture holds: the flop en_q has no reset, and chip.json gives no answer for it.
// The bench passes: en_q takes a known value at the first rising edge, while the reset holds the count.
module counter (
    input  wire       clk,   // the 1 clock; every flop takes its rising edge
    input  wire       rst,   // synchronous reset, active high: the count becomes 0
    input  wire       en,    // registered once: the count goes up 1 edge after the edge that reads en
    output reg  [7:0] count  // wraps from 255 to 0
);
    reg en_q;
    always @(posedge clk) en_q <= en;
    always @(posedge clk) begin
        if (rst) count <= 8'd0;
        else if (en_q) count <= count + 8'd1;
    end
endmodule
