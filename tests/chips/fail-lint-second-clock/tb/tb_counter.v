`timescale 1ns / 1ps
// The bench of counter. It drives the ports, compares the count with the value worked out by hand,
// and prints the 3 measures every bench prints. It reads the top module's ports only, so it runs on
// the RTL and on the routed netlist alike.
module tb_counter;
    reg        clk = 1'b0;
    reg        rst = 1'b1;
    reg        en = 1'b0;
    wire [7:0] count;
    integer    errors = 0;     // comparisons that failed
    integer    checks = 0;     // comparisons made
    integer    x_outputs = 0;  // clock edges after reset release at which an output is unknown
    reg        released = 1'b0;

    counter dut (
        .clk  (clk),
        .rst  (rst),
        .en   (en),
        .count(count)
    );

    always #10 clk = ~clk;

    always @(posedge clk) if (released && (^count === 1'bx)) x_outputs = x_outputs + 1;

    task expect_count(input [7:0] want);
        begin
            checks = checks + 1;
            if (count !== want) begin
                errors = errors + 1;
                $display("mismatch at %0t ns: count is %0d, expected %0d", $time, count, want);
            end
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst = 1'b0;
        @(negedge clk);
        released = 1'b1;
        expect_count(8'd0);    // the reset cleared the count, and 1 edge without the enable holds it
        en = 1'b1;
        repeat (3) @(negedge clk);
        expect_count(8'd3);    // 3 enabled edges
        en = 1'b0;
        repeat (2) @(negedge clk);
        expect_count(8'd3);    // without the enable the count holds
        en = 1'b1;
        repeat (252) @(negedge clk);
        expect_count(8'd255);  // 3 + 252
        @(negedge clk);
        expect_count(8'd0);    // 255 + 1 wraps to 0
        repeat (5) @(negedge clk);
        expect_count(8'd5);
        rst = 1'b1;
        @(negedge clk);
        expect_count(8'd0);    // the reset wins over the enable
        rst = 1'b0;
        repeat (2) @(negedge clk);
        expect_count(8'd2);
        $display("errors = %0d", errors);
        $display("checks = %0d", checks);
        $display("x_outputs = %0d", x_outputs);
        $finish;
    end
endmodule
