// The bench of programs/gcd.asm in slot 2. The input is {A, B}, 4 bits each; the answers, worked by
// hand:
//
//   gcd(12, 8) = 4    gcd(15, 10) = 5    gcd(7, 7) = 7    gcd(13, 5) = 1
//   gcd(9, 12) = 3    gcd(9, 0) = 9      gcd(0, 6) = 6    gcd(0, 0) = 0

`timescale 1ns / 1ps

module tb_gcd;

`include "tb_common.vh"

    initial begin
        //       slot  input  out_port outputs
        run_case(2'd2, 8'hc8, 8'd4,    1);
        run_case(2'd2, 8'hfa, 8'd5,    1);
        run_case(2'd2, 8'h77, 8'd7,    1);
        run_case(2'd2, 8'hd5, 8'd1,    1);
        run_case(2'd2, 8'h9c, 8'd3,    1);
        run_case(2'd2, 8'h90, 8'd9,    1);
        run_case(2'd2, 8'h06, 8'd6,    1);
        run_case(2'd2, 8'h00, 8'd0,    1);
        end_bench;
    end

endmodule
