// Shared by the acc8 benches: the clock, the device, the reset, and the 3 measures every bench
// prints. A bench includes it inside its module. It reads the device's ports only, so the 4 program
// benches run on the RTL and on the routed netlist alike.
//
//   `TB_STREAM   the device is acc8_core alone and the bench drives rom_data (tb_random.v)
//
// Inputs change and outputs are sampled on the falling edge, so `cycle` is the count of
// instructions executed since the reset. Every input is unknown until the first reset.

    localparam integer MAX_CYCLES = 2000;

    reg        clk = 1'b0;
    reg        rst;
    reg  [1:0] boot;
    reg  [7:0] in_port;
    wire [7:0] out_port;
    wire       out_valid;
    wire       halted;

`ifdef TB_STREAM
    reg  [12:0] rom_data;
    wire [7:0]  rom_addr;

    acc8_core dut (
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

    wire [17:0] observed = {rom_addr, out_port, out_valid, halted};
`else
    acc8 dut (
        .clk       (clk),
        .rst       (rst),
        .boot      (boot),
        .in_port   (in_port),
        .out_port  (out_port),
        .out_valid (out_valid),
        .halted    (halted)
    );

    wire [9:0] observed = {out_port, out_valid, halted};
`endif

    always #5 clk = ~clk;

    integer errors    = 0;     // comparisons that failed
    integer checks    = 0;     // comparisons made
    integer x_outputs = 0;     // clock edges after reset release at which an output is unknown
    reg     released  = 1'b0;  // the first reset has ended
    integer cycle;
    integer outputs;           // out_valid pulses since the reset

    always @(posedge clk) if (released && (^observed === 1'bx)) x_outputs = x_outputs + 1;

    // 2 rising edges with rst high, then the release.
    task reset_device;
        input [1:0] slot;
        input [7:0] value;
        begin
            @(negedge clk);
            rst     = 1'b1;
            boot    = slot;
            in_port = value;
            @(negedge clk);
            @(negedge clk);
            rst      = 1'b0;
            released = 1'b1;
            cycle    = 0;
            outputs  = 0;
        end
    endtask

    task clock_once;
        begin
            @(negedge clk);
            cycle = cycle + 1;
            if (out_valid === 1'b1)
                outputs = outputs + 1;
        end
    endtask

`ifndef TB_STREAM
    // 1 program run: reset into `slot` with `value` on the input port, clock until halted and 3
    // cycles more, in which a halted processor changes nothing. Then 3 checks: halted, out_port, and
    // the count of out_valid pulses.
    task run_case;
        input [1:0]   slot;
        input [7:0]   value;
        input [7:0]   want;
        input integer want_outputs;
        integer       halt_cycle;
        begin
            reset_device(slot, value);
            while (halted !== 1'b1 && cycle < MAX_CYCLES)
                clock_once;
            halt_cycle = cycle;
            repeat (3)
                clock_once;
            checks = checks + 3;
            if (halted !== 1'b1) begin
                errors = errors + 1;
                $display("slot %0d, input 0x%02x: not halted after %0d cycles", slot, value, halt_cycle);
            end
            if (out_port !== want) begin
                errors = errors + 1;
                $display("slot %0d, input 0x%02x: out_port is %0d, expected %0d", slot, value, out_port, want);
            end
            if (outputs != want_outputs) begin
                errors = errors + 1;
                $display("slot %0d, input 0x%02x: %0d outputs, expected %0d",
                         slot, value, outputs, want_outputs);
            end
        end
    endtask

    // A run that does not end: reset into `slot`, then `count` instructions. 2 checks: the processor
    // is not halted, and out_port is `want`. The reset of the next run comes in the middle of this one.
    task abandon;
        input [1:0]   slot;
        input [7:0]   value;
        input integer count;
        input [7:0]   want;
        begin
            reset_device(slot, value);
            repeat (count)
                clock_once;
            checks = checks + 2;
            if (halted !== 1'b0) begin
                errors = errors + 1;
                $display("slot %0d, input 0x%02x: halted after %0d cycles", slot, value, count);
            end
            if (out_port !== want) begin
                errors = errors + 1;
                $display("slot %0d, input 0x%02x: out_port is %0d after %0d cycles, expected %0d",
                         slot, value, out_port, count, want);
            end
        end
    endtask
`endif

    // The 3 measures every bench prints, then the end of the run.
    task end_bench;
        begin
            $display("errors = %0d", errors);
            $display("checks = %0d", checks);
            $display("x_outputs = %0d", x_outputs);
            $finish;
        end
    endtask
