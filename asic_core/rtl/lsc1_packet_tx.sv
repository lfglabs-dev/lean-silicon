`default_nettype none

// Stable-under-backpressure LSC-1 v1 response serializer.
module lsc1_packet_tx (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          abort,
    input  wire          start,
    input  wire [7:0]    status,
    input  wire [15:0]   payload_length,
    input  wire [543:0]  payload,
    output wire          busy,
    output reg           done_pulse,
    output reg  [31:0]   payload_crc,
    output reg  [7:0]    tx_data,
    output wire          tx_valid,
    input  wire          tx_ready,
    output wire [15:0]   arch_index, arch_length,
    output wire [7:0]    arch_status,
    output wire [543:0]  arch_payload,
    output wire          arch_active,
    output wire [31:0]   arch_saved_crc,
    output wire [31:0]   arch_envelope_crc_work,
    output wire [31:0]   arch_payload_crc_work,
    output wire          arch_done_pulse,
    output wire [31:0]   arch_payload_crc
);
    reg active;
    reg [15:0] index;
    reg [15:0] saved_length;
    reg [7:0] saved_status;
    reg [543:0] saved_payload;
    reg [31:0] saved_crc;
    reg [31:0] envelope_crc_work;
    reg [31:0] payload_crc_work;

    function automatic [31:0] crc_byte;
        input [31:0] crc_in;
        input [7:0] data;
        integer bit_index;
        reg [31:0] work;
        begin
            work = crc_in ^ data;
            for (bit_index = 0; bit_index < 8; bit_index = bit_index + 1)
                work = work[0] ? ((work >> 1) ^ 32'hedb88320) : (work >> 1);
            crc_byte = work;
        end
    endfunction

    assign busy = active;
    assign tx_valid = active;
    assign arch_index = index; assign arch_length = saved_length;
    assign arch_status = saved_status; assign arch_payload = saved_payload;
    assign arch_active = active;
    assign arch_saved_crc = saved_crc;
    assign arch_envelope_crc_work = envelope_crc_work;
    assign arch_payload_crc_work = payload_crc_work;
    assign arch_done_pulse = done_pulse;
    assign arch_payload_crc = payload_crc;

    always @(*) begin
        if (index == 0) tx_data = 8'h5a;
        else if (index == 1) tx_data = 8'h01;
        else if (index == 2) tx_data = saved_status;
        else if (index == 3) tx_data = saved_length[7:0];
        else if (index == 4) tx_data = saved_length[15:8];
        else if (index < 5 + saved_length)
            tx_data = saved_payload[(index-5)*8 +: 8];
        else begin
            case (index - 5 - saved_length)
                0: tx_data = saved_crc[7:0];
                1: tx_data = saved_crc[15:8];
                2: tx_data = saved_crc[23:16];
                default: tx_data = saved_crc[31:24];
            endcase
        end
    end

    always @(posedge clk) begin
        if (!rst_n || abort) begin
            active <= 1'b0;
            index <= 0;
            saved_length <= 0;
            saved_status <= 0;
            saved_payload <= 0;
            saved_crc <= 0;
            envelope_crc_work <= 32'hffffffff;
            payload_crc_work <= 32'hffffffff;
            payload_crc <= 0;
            done_pulse <= 1'b0;
        end else begin
            done_pulse <= 1'b0;
            if (start && !active) begin
                active <= 1'b1;
                index <= 0;
                saved_length <= payload_length;
                saved_status <= status;
                saved_payload <= payload;
                saved_crc <= 0;
                envelope_crc_work <= 32'hffffffff;
                payload_crc_work <= 32'hffffffff;
            end else if (active && tx_ready) begin
                if (index <= saved_length + 4) begin
                    envelope_crc_work <= crc_byte(envelope_crc_work, tx_data);
                    if (index >= 5)
                        payload_crc_work <= crc_byte(payload_crc_work, tx_data);
                    if (index == saved_length + 4) begin
                        saved_crc <= ~crc_byte(envelope_crc_work, tx_data);
                        payload_crc <= saved_length == 0 ? 0 :
                            ~crc_byte(payload_crc_work, tx_data);
                    end
                end
                if (index == saved_length + 8) begin
                    active <= 1'b0;
                    done_pulse <= 1'b1;
                end else
                    index <= index + 1'b1;
            end
        end
    end
endmodule

`default_nettype wire
