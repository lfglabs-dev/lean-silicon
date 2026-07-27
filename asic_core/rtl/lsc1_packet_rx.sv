`default_nettype none

// Bounded LSC-1 v1 request receiver.  This module owns framing and integrity
// only; opcode/state/payload semantics belong to the controller.
module lsc1_packet_rx (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          abort,
    input  wire [7:0]    rx_data,
    input  wire          rx_valid,
    output wire          rx_ready,
    output reg           frame_valid,
    input  wire          frame_ready,
    output reg  [7:0]    frame_opcode,
    output reg  [15:0]   frame_length,
    output reg  [2047:0] frame_payload,
    output reg           fault_valid,
    output reg  [7:0]    fault_status,
    output wire          busy
);
    localparam [7:0] SOF = 8'ha1;
    localparam [7:0] VERSION = 8'h01;
    localparam [15:0] MAX_PAYLOAD = 16'd256;

    localparam [2:0] S_SOF = 3'd0, S_HEADER = 3'd1, S_BODY = 3'd2,
                     S_WAIT = 3'd3;
    reg [2:0] state;
    reg [2:0] header_index;
    reg [15:0] body_index;
    reg [15:0] declared_length;
    reg [7:0] version;
    reg [7:0] opcode;
    reg [7:0] flags;
    reg [31:0] crc;
    reg [31:0] received_crc;
    assign busy = state != S_SOF || frame_valid || fault_valid;

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

    assign rx_ready = (state != S_WAIT) && !frame_valid && !fault_valid;
    wire rx_fire = rx_valid && rx_ready;

    task automatic raise_fault(input [7:0] status);
        begin
            fault_valid <= 1'b1;
            fault_status <= status;
            state <= S_WAIT;
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n || abort) begin
            state <= S_SOF;
            header_index <= 0;
            body_index <= 0;
            declared_length <= 0;
            version <= 0;
            opcode <= 0;
            flags <= 0;
            crc <= 32'hffffffff;
            received_crc <= 0;
            frame_valid <= 1'b0;
            frame_opcode <= 0;
            frame_length <= 0;
            frame_payload <= 0;
            fault_valid <= 1'b0;
            fault_status <= 0;
        end else begin
            if (frame_valid && frame_ready) begin
                frame_valid <= 1'b0;
                state <= S_SOF;
            end
            if (fault_valid && frame_ready) begin
                fault_valid <= 1'b0;
                state <= S_SOF;
            end

            if (rx_fire) begin
                case (state)
                    S_SOF: begin
                        frame_payload <= 0;
                        body_index <= 0;
                        received_crc <= 0;
                        if (rx_data != SOF) begin
                            raise_fault(8'h80); // BAD_SOF
                        end else begin
                            crc <= crc_byte(32'hffffffff, rx_data);
                            header_index <= 0;
                            state <= S_HEADER;
                        end
                    end
                    S_HEADER: begin
                        crc <= crc_byte(crc, rx_data);
                        case (header_index)
                            0: version <= rx_data;
                            1: opcode <= rx_data;
                            2: flags <= rx_data;
                            3: declared_length[7:0] <= rx_data;
                            4: begin
                                declared_length[15:8] <= rx_data;
                                body_index <= 0;
                                if ({rx_data, declared_length[7:0]} > MAX_PAYLOAD)
                                    raise_fault(8'h83); // BAD_LENGTH
                                else
                                    state <= S_BODY;
                            end
                            default: state <= S_SOF;
                        endcase
                        header_index <= header_index + 1'b1;
                    end
                    S_BODY: begin
                        if (body_index < declared_length) begin
                            // Keep this bound coupled to the declared storage capacity.
                            // JUMP's inverse witness occupies payload bytes 86 through 102.
                            if (body_index < MAX_PAYLOAD)
                                frame_payload[body_index*8 +: 8] <= rx_data;
                            crc <= crc_byte(crc, rx_data);
                        end else begin
                            case (body_index - declared_length)
                                0: received_crc[7:0] <= rx_data;
                                1: received_crc[15:8] <= rx_data;
                                2: received_crc[23:16] <= rx_data;
                                3: begin
                                    received_crc[31:24] <= rx_data;
                                    if ({rx_data, received_crc[23:0]} != ~crc)
                                        raise_fault(8'h84); // BAD_CRC
                                    else if (version != VERSION)
                                        raise_fault(8'h81); // BAD_VERSION
                                    else if (flags != 0)
                                        raise_fault(8'h85); // BAD_FLAGS
                                    else begin
                                        frame_opcode <= opcode;
                                        frame_length <= declared_length;
                                        frame_valid <= 1'b1;
                                        state <= S_WAIT;
                                    end
                                end
                            endcase
                        end
                        body_index <= body_index + 1'b1;
                    end
                    default: state <= S_SOF;
                endcase
            end
        end
    end
endmodule

`default_nettype wire
