// counter: an 8-bit counter with an enable.
// The fault this fixture holds: the count goes up by 2, and the bench asks for 1.
module counter (
    input  wire       clk,   // the 1 clock; every flop takes its rising edge
    input  wire       rst,   // synchronous reset, active high: the count becomes 0
    input  wire       en,    // count up on the next rising edge; without it the count holds
    output reg  [7:0] count  // wraps past 255
);
    always @(posedge clk) begin
        if (rst) count <= 8'd0;
        else if (en) count <= count + 8'd2;
    end
endmodule
