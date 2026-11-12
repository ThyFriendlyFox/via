// The bench of acc8_core alone on a stream of 1024 instruction words: 1017 of every instruction but
// HLT at random, then HLT, then 6 words that would each change a core that had not stopped.
//
// tb/random_stim.vh holds the stream, and for each word the ports the model of acc8.py has after it;
// `python3 acc8.py stim` writes it. After every word the bench compares rom_addr (the program
// counter), out_port, out_valid and halted with the model's: 1 check a word.
//
// The bench drives acc8_core, and the routed netlist of acc8 holds no module of that name. So
// chip.json marks this bench rtl_only.

`timescale 1ns / 1ps
`define TB_STREAM

module tb_random;

`include "tb_common.vh"

    integer words = 0;

    // 1 word of the stream: {in_port, rom_data} for the core, and the ports wanted after it.
    task step;
        input [20:0] stimulus;
        input [17:0] want;
        begin
            rom_data = stimulus[12:0];
            in_port  = stimulus[20:13];
            clock_once;
            words  = words + 1;
            checks = checks + 1;
            if (observed !== want) begin
                errors = errors + 1;
                $display("word %0d (%h): rom_addr, out_port, out_valid, halted are %h, expected %h",
                         words, stimulus[12:0], observed, want);
            end
        end
    endtask

    initial begin
        rom_data = 13'd0;
        reset_device(2'd2, 8'd0);
`include "random_stim.vh"
        end_bench;
    end

endmodule
