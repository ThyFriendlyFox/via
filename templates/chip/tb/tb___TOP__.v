`timescale 1ns / 1ps
// The bench of __TOP__. It drives the ports, compares each output with the value worked out by hand,
// and prints the 3 measures every bench prints. It reads the top module's ports only, so it runs on
// the RTL and on the routed netlist alike.
module tb___TOP__;
    reg        clk = 1'b0;
    reg        rst = 1'b1;
    reg        en = 1'b0;
    reg  [7:0] d = 8'd0;
    wire [7:0] q;
    integer    errors = 0;     // comparisons that failed
    integer    checks = 0;     // comparisons made
    integer    x_outputs = 0;  // clock edges after reset release at which an output is unknown
    reg        released = 1'b0;

    __TOP__ dut (
        .clk(clk),
        .rst(rst),
        .en (en),
        .d  (d),
        .q  (q)
    );

    always #10 clk = ~clk;

    always @(posedge clk) if (released && (^q === 1'bx)) x_outputs = x_outputs + 1;

    task expect_q(input [7:0] want);
        begin
            checks = checks + 1;
            if (q !== want) begin
                errors = errors + 1;
                $display("mismatch at %0t ns: q is %h, expected %h", $time, q, want);
            end
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst = 1'b0;
        @(negedge clk);
        released = 1'b1;
        expect_q(8'h00);  // the reset cleared the register
        d  = 8'hA5;
        en = 1'b1;
        @(negedge clk);
        expect_q(8'hA5);  // an enabled edge loads d
        d  = 8'h3C;
        en = 1'b0;
        @(negedge clk);
        expect_q(8'hA5);  // without the enable the register holds
        en = 1'b1;
        @(negedge clk);
        expect_q(8'h3C);
        $display("errors = %0d", errors);
        $display("checks = %0d", checks);
        $display("x_outputs = %0d", x_outputs);
        $finish;
    end
endmodule
