// counter: an 8-bit counter with an enable.
// The fault this fixture holds: the block that works out the next count assigns nothing while en is
// low. The value must then be kept, and what keeps it is a latch.
module counter (
    input  wire       clk,   // the 1 clock; every flop takes its rising edge
    input  wire       rst,   // synchronous reset, active high: the count becomes 0
    input  wire       en,    // count up by 1 on the next rising edge; without it the count holds
    output reg  [7:0] count  // wraps from 255 to 0
);
    reg [7:0] next;
    always @(*) begin
        if (en) next = count + 8'd1;
    end
    always @(posedge clk) begin
        if (rst) count <= 8'd0;
        else count <= next;
    end
endmodule
