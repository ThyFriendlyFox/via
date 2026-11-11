// acc8_regfile: the data store, 16 registers of 8 bits in flip-flops.
//
// 1 address serves the read and the write. The read is combinational; the
// write lands on the clock edge. rst clears every register.

`default_nettype none

module acc8_regfile (
    input  wire       clk,
    input  wire       rst,
    input  wire       we,
    input  wire [3:0] addr,
    input  wire [7:0] wdata,
    output reg  [7:0] rdata
);

    reg [127:0] q;   // r15 at the top, r0 at the bottom

    always @(posedge clk) begin
        if (rst) begin
            q <= 128'd0;
        end else if (we) begin
            case (addr)
                4'h0: q[  7:  0] <= wdata;
                4'h1: q[ 15:  8] <= wdata;
                4'h2: q[ 23: 16] <= wdata;
                4'h3: q[ 31: 24] <= wdata;
                4'h4: q[ 39: 32] <= wdata;
                4'h5: q[ 47: 40] <= wdata;
                4'h6: q[ 55: 48] <= wdata;
                4'h7: q[ 63: 56] <= wdata;
                4'h8: q[ 71: 64] <= wdata;
                4'h9: q[ 79: 72] <= wdata;
                4'ha: q[ 87: 80] <= wdata;
                4'hb: q[ 95: 88] <= wdata;
                4'hc: q[103: 96] <= wdata;
                4'hd: q[111:104] <= wdata;
                4'he: q[119:112] <= wdata;
                4'hf: q[127:120] <= wdata;
            endcase
        end
    end

    always @* begin
        rdata = 8'd0;
        case (addr)
            4'h0: rdata = q[  7:  0];
            4'h1: rdata = q[ 15:  8];
            4'h2: rdata = q[ 23: 16];
            4'h3: rdata = q[ 31: 24];
            4'h4: rdata = q[ 39: 32];
            4'h5: rdata = q[ 47: 40];
            4'h6: rdata = q[ 55: 48];
            4'h7: rdata = q[ 63: 56];
            4'h8: rdata = q[ 71: 64];
            4'h9: rdata = q[ 79: 72];
            4'ha: rdata = q[ 87: 80];
            4'hb: rdata = q[ 95: 88];
            4'hc: rdata = q[103: 96];
            4'hd: rdata = q[111:104];
            4'he: rdata = q[119:112];
            4'hf: rdata = q[127:120];
        endcase
    end

endmodule

`default_nettype wire
