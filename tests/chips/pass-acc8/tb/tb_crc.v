// The bench of programs/crc.asm in slot 3. CRC-8, polynomial 0x07, of 1 byte; the answers, worked by
// hand (shift left; when a 1 leaves, XOR 0x07):
//
//   0x80: 07 0e 1c 38 70 e0 c7 89
//   0x01: 02 04 08 10 20 40 80 07
//   0xff: f9 f5 ed dd bd 7d fa f3
//   0x31: 62 c4 8f 19 32 64 c8 97
//   0x00: 00

`timescale 1ns / 1ps

module tb_crc;

`include "tb_common.vh"

    initial begin
        //       slot  input  out_port outputs
        run_case(2'd3, 8'h80, 8'h89,   1);
        run_case(2'd3, 8'h01, 8'h07,   1);
        run_case(2'd3, 8'hff, 8'hf3,   1);
        run_case(2'd3, 8'h31, 8'h97,   1);
        run_case(2'd3, 8'h00, 8'h00,   1);
        end_bench;
    end

endmodule
