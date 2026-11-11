// The bench of programs/mul.asm in slot 1. The input is {A, B}, 4 bits each; the answers, worked by
// hand:
//
//   6 x 7 = 42     15 x 15 = 225     0 x 9 = 0     9 x 0 = 0
//   1 x 13 = 13    12 x 5 = 60

`timescale 1ns / 1ps

module tb_mul;

`include "tb_common.vh"

    initial begin
        //       slot  input  out_port outputs
        run_case(2'd1, 8'h67, 8'd42,   1);
        run_case(2'd1, 8'hff, 8'd225,  1);
        run_case(2'd1, 8'h09, 8'd0,    1);
        run_case(2'd1, 8'h90, 8'd0,    1);
        run_case(2'd1, 8'h1d, 8'd13,   1);
        run_case(2'd1, 8'hc5, 8'd60,   1);
        end_bench;
    end

endmodule
