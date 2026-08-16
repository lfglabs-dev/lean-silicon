`default_nettype none

// Authored LSC-1 BLAKE3 transaction shell.  The packet frontend owns request
// decoding and byte serialization; this module owns only the service/result
// lifecycle and the identifiers which bind its transitions.
module lsc1_blake3_lifecycle (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        abort,
    input  wire        service_start,
    input  wire [31:0] service_txn_id,
    input  wire [31:0] service_next_pc,
    input  wire [31:0] service_next_fp,
    input  wire        service_accept,
    input  wire        service_discard,
    input  wire        result_tx_done,
    input  wire [31:0] result_tx_crc,
    input  wire        retire_attempt,
    input  wire [31:0] retire_txn_id,
    input  wire [31:0] retire_result_crc,
    output reg         service_pending,
    output reg         result_pending,
    output reg  [31:0] staged_txn_id,
    output reg  [31:0] staged_service_id,
    output reg  [31:0] staged_next_pc,
    output reg  [31:0] staged_next_fp,
    output reg  [31:0] staged_result_crc,
    output reg  [31:0] service_seq,
    output reg  [31:0] retire_seq,
    output wire        retire_match,
    output wire [7:0]  retire_mismatch_detail,
    output reg         done_pulse
);
    assign retire_match = result_pending &&
                          retire_txn_id == staged_txn_id &&
                          retire_result_crc == staged_result_crc;
    assign retire_mismatch_detail = retire_txn_id != staged_txn_id ? 8'd1 : 8'd2;

    always @(posedge clk) begin
        if (!rst_n) begin
            service_pending <= 1'b0;
            result_pending <= 1'b0;
            staged_txn_id <= 0;
            staged_service_id <= 0;
            staged_next_pc <= 0;
            staged_next_fp <= 0;
            staged_result_crc <= 0;
            service_seq <= 0;
            retire_seq <= 0;
            done_pulse <= 1'b0;
        end else if (abort) begin
            service_pending <= 1'b0;
            result_pending <= 1'b0;
            staged_result_crc <= 0;
            done_pulse <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            if (service_start) begin
                service_pending <= 1'b1;
                result_pending <= 1'b0;
                staged_txn_id <= service_txn_id;
                staged_service_id <= service_seq + 1'b1;
                staged_next_pc <= service_next_pc;
                staged_next_fp <= service_next_fp;
                staged_result_crc <= 0;
                service_seq <= service_seq + 1'b1;
            end
            if (service_discard)
                service_pending <= 1'b0;
            if (service_accept) begin
                service_pending <= 1'b0;
                result_pending <= 1'b1;
                staged_result_crc <= 0;
            end
            if (result_tx_done && result_pending)
                staged_result_crc <= result_tx_crc;
            if (retire_attempt && result_pending) begin
                result_pending <= 1'b0;
                if (retire_match) begin
                    retire_seq <= retire_seq + 1'b1;
                    done_pulse <= 1'b1;
                end
            end
        end
    end
endmodule

`default_nettype wire
