`default_nettype none

// Purely combinational alias precheck for the eight BLAKE3 service cells: reports
// whether any two cells name the same address while disagreeing on presence or value.
module lsc1_blake3_alias_check (
    input wire [31:0] message_offset_0, message_offset_1,
    input wire [31:0] message_offset_2, message_offset_3,
    input wire [31:0] cv_offset, out_offset,
    input wire [7:0] cell_present_0, cell_present_1, cell_present_2, cell_present_3,
    input wire [7:0] cell_present_4, cell_present_5, cell_present_6, cell_present_7,
    input wire [127:0] cell_value_0, cell_value_1, cell_value_2, cell_value_3,
    input wire [127:0] cell_value_4, cell_value_5, cell_value_6, cell_value_7,
    output wire alias_inconsistent
);
    // Addresses were previously formed as offset + a transaction base common to all
    // eight cells.  Adding a constant is a bijection on Z/2^32 and Verilog `+` wraps,
    // so the base cancels out of every pairwise equality below and is not an input.
    wire [31:0] address [0:7];
    wire [7:0] present [0:7];
    wire [127:0] value [0:7];
    wire [63:0] alias_pair;

    assign address[0] = message_offset_0;
    assign address[1] = message_offset_1;
    assign address[2] = message_offset_2;
    assign address[3] = message_offset_3;
    assign address[4] = cv_offset;
    assign address[5] = cv_offset + 1'b1;
    assign address[6] = out_offset;
    assign address[7] = out_offset + 1'b1;
    assign present[0] = cell_present_0;
    assign present[1] = cell_present_1;
    assign present[2] = cell_present_2;
    assign present[3] = cell_present_3;
    assign present[4] = cell_present_4;
    assign present[5] = cell_present_5;
    assign present[6] = cell_present_6;
    assign present[7] = cell_present_7;
    assign value[0] = cell_value_0;
    assign value[1] = cell_value_1;
    assign value[2] = cell_value_2;
    assign value[3] = cell_value_3;
    assign value[4] = cell_value_4;
    assign value[5] = cell_value_5;
    assign value[6] = cell_value_6;
    assign value[7] = cell_value_7;

    genvar alias_i, alias_j;
    generate
        for (alias_i = 0; alias_i < 8; alias_i = alias_i + 1) begin : g_alias_i
            for (alias_j = 0; alias_j < 8; alias_j = alias_j + 1) begin : g_alias_j
                if (alias_j > alias_i)
                    assign alias_pair[alias_i*8+alias_j] =
                        address[alias_i] == address[alias_j] &&
                        (present[alias_i] != present[alias_j] ||
                         value[alias_i] != value[alias_j]);
                else
                    assign alias_pair[alias_i*8+alias_j] = 1'b0;
            end
        end
    endgenerate

    assign alias_inconsistent = |alias_pair;

endmodule

`default_nettype wire
