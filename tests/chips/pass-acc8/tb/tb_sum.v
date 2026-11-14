// The bench of programs/sum.asm in slot 0. The answers, worked by hand:
//
//   N = 10: 1 + 2 + ... + 10 = 10 x 11 / 2 = 55, 1 output per term
//   N = 0:  no term, no output, out_port keeps its reset value 0
//   N = 1:  1, 1 output
//   N = 22: 22 x 23 / 2 = 253, the largest sum 8 bits hold
//   N = 23: 23 x 24 / 2 = 276, which wraps to 276 - 256 = 20
//
// A reset in the middle of a program: the run with N = 23 is first left after 40 instructions. The
// program takes 5 instructions to start and 9 for each term, and the 8th of the 9 is the OUT. So the
// 40th instruction is the OUT of the 4th term: out_port is 1 + 2 + 3 + 4 = 10, and the processor is not
// halted. The run with N = 0 that follows must find out_port back at 0.

`timescale 1ns / 1ps

module tb_sum;

`include "tb_common.vh"

    initial begin
        //       slot  input  out_port outputs
        run_case(2'd0, 8'd10, 8'd55,   10);
        //       slot  input  instructions out_port
        abandon (2'd0, 8'd23, 40,          8'd10);
        run_case(2'd0, 8'd0,  8'd0,    0);
        run_case(2'd0, 8'd1,  8'd1,    1);
        run_case(2'd0, 8'd22, 8'd253,  22);
        run_case(2'd0, 8'd23, 8'd20,   23);
        end_bench;
    end

endmodule
