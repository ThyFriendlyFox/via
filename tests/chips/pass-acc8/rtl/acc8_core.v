// acc8_core: the processor without its program store.
//
// 1 instruction per clock: the word at rom_addr must come back on rom_data
// in the same cycle.
//
//   rom_data[12:9]  opcode
//   rom_data[8]     m: 1 = the operand is the value arg, 0 = it is register
//                   r[arg[3:0]]. On JZ and JC, m = 1 inverts the condition.
//   rom_data[7:0]   arg: a value, a register number or a jump address
//
// rst is synchronous and active high. While it is high, boot names the slot
// the program starts in: pc = boot * 64.

`default_nettype none

module acc8_core (
    input  wire        clk,
    input  wire        rst,
    input  wire [1:0]  boot,
    output wire [7:0]  rom_addr,
    input  wire [12:0] rom_data,
    input  wire [7:0]  in_port,
    output reg  [7:0]  out_port,
    output reg         out_valid,
    output reg         halted
);

    localparam [3:0] OP_HLT = 4'h0;
    localparam [3:0] OP_LD  = 4'h1;
    localparam [3:0] OP_ST  = 4'h2;
    localparam [3:0] OP_ADD = 4'h3;
    localparam [3:0] OP_SUB = 4'h4;
    localparam [3:0] OP_CMP = 4'h5;
    localparam [3:0] OP_AND = 4'h6;
    localparam [3:0] OP_OR  = 4'h7;
    localparam [3:0] OP_XOR = 4'h8;
    localparam [3:0] OP_SHL = 4'h9;
    localparam [3:0] OP_SHR = 4'ha;
    localparam [3:0] OP_IN  = 4'hb;
    localparam [3:0] OP_OUT = 4'hc;
    localparam [3:0] OP_JMP = 4'hd;
    localparam [3:0] OP_JZ  = 4'he;
    localparam [3:0] OP_JC  = 4'hf;

    reg  [7:0] pc;
    reg  [7:0] acc;
    reg        z;
    reg        c;

    wire [3:0] op  = rom_data[12:9];
    wire       m   = rom_data[8];
    wire [7:0] arg = rom_data[7:0];

    assign rom_addr = pc;

    reg        rf_we;
    wire [7:0] rf_rdata;

    acc8_regfile u_regfile (
        .clk   (clk),
        .rst   (rst),
        .we    (rf_we & ~halted),
        .addr  (arg[3:0]),
        .wdata (acc),
        .rdata (rf_rdata)
    );

    wire [7:0] src  = m ? arg : rf_rdata;
    wire [8:0] sum  = {1'b0, acc} + {1'b0, src};
    wire [8:0] diff = {1'b0, acc} - {1'b0, src};   // bit 8 is the borrow

    reg  [7:0] res;   // the value for acc and for the Z flag
    reg        cy;    // the value for the C flag
    reg        acc_we;
    reg        z_we;
    reg        c_we;
    reg        out_we;
    reg        halt;
    reg        jump;

    always @* begin
        res    = src;
        cy     = 1'b0;
        acc_we = 1'b0;
        z_we   = 1'b0;
        c_we   = 1'b0;
        rf_we  = 1'b0;
        out_we = 1'b0;
        halt   = 1'b0;
        jump   = 1'b0;
        case (op)
            OP_HLT: halt = 1'b1;
            OP_LD : begin acc_we = 1'b1; z_we = 1'b1; end
            OP_ST : rf_we = 1'b1;
            OP_ADD: begin res = sum[7:0];  cy = sum[8];  acc_we = 1'b1; z_we = 1'b1; c_we = 1'b1; end
            OP_SUB: begin res = diff[7:0]; cy = diff[8]; acc_we = 1'b1; z_we = 1'b1; c_we = 1'b1; end
            OP_CMP: begin res = diff[7:0]; cy = diff[8]; z_we = 1'b1; c_we = 1'b1; end
            OP_AND: begin res = acc & src; acc_we = 1'b1; z_we = 1'b1; end
            OP_OR : begin res = acc | src; acc_we = 1'b1; z_we = 1'b1; end
            OP_XOR: begin res = acc ^ src; acc_we = 1'b1; z_we = 1'b1; end
            OP_SHL: begin res = {acc[6:0], 1'b0}; cy = acc[7]; acc_we = 1'b1; z_we = 1'b1; c_we = 1'b1; end
            OP_SHR: begin res = {1'b0, acc[7:1]}; cy = acc[0]; acc_we = 1'b1; z_we = 1'b1; c_we = 1'b1; end
            OP_IN : begin res = in_port; acc_we = 1'b1; z_we = 1'b1; end
            OP_OUT: out_we = 1'b1;
            OP_JMP: jump = 1'b1;
            OP_JZ : jump = z ^ m;
            OP_JC : jump = c ^ m;
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            pc        <= {boot, 6'd0};
            acc       <= 8'd0;
            z         <= 1'b0;
            c         <= 1'b0;
            out_port  <= 8'd0;
            out_valid <= 1'b0;
            halted    <= 1'b0;
        end else if (!halted) begin
            if (jump)
                pc <= arg;
            else if (!halt)
                pc <= pc + 8'd1;
            if (acc_we)
                acc <= res;
            if (z_we)
                z <= (res == 8'd0);
            if (c_we)
                c <= cy;
            if (out_we)
                out_port <= acc;
            out_valid <= out_we;
            halted    <= halt;
        end
    end

endmodule

`default_nettype wire
