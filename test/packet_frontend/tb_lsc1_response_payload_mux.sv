`default_nettype none

// Purely combinational byte selector for the seven externally serialized response schemas.
module lsc1_response_payload_mux_golden (
    input wire [2:0] kind,
    input wire [15:0] payload_index,
    input wire [31:0] blake_staged_txn_id, blake_staged_service_id,
    input wire [31:0] blake_staged_next_pc, blake_staged_next_fp,
    input wire [127:0] staged_message_0, staged_message_1, staged_message_2, staged_message_3,
    input wire [127:0] staged_cv_0, staged_cv_1,
    input wire [127:0] staged_metadata,
    input wire [1:0] staged_write_count,
    input wire [31:0] staged_write_address_0, staged_write_address_1,
    input wire [127:0] staged_write_value_0, staged_write_value_1,
    input wire [31:0] staged_access_0, staged_access_1, staged_access_2, staged_access_3,
    input wire [31:0] staged_access_4, staged_access_5, staged_access_6, staged_access_7,
    input wire [31:0] staged_txn_id, staged_next_pc, staged_next_fp,
    input wire [1:0] scalar_staged_write_count,
    input wire scalar_staged_deferred,
    input wire [7:0] scalar_staged_access_count,
    input wire [31:0] scalar_staged_write_address,
    input wire [127:0] scalar_staged_write_value,
    input wire [31:0] scalar_staged_deferred_target, scalar_staged_deferred_local,
    input wire [31:0] scalar_staged_access_0, scalar_staged_access_1, scalar_staged_access_2,
    input wire [31:0] short_txn_id,
    input wire [7:0] short_detail,
    input wire blake_service_pending, blake_result_pending, result_pending,
    input wire [31:0] retire_seq, committed_pc, committed_fp,
    input wire [7:0] last_fault,
    input wire state_valid,
    output reg [7:0] payload_data
);
    wire [127:0] staged_message [0:3];
    wire [127:0] staged_cv [0:1];
    wire [31:0] staged_write_address [0:1];
    wire [127:0] staged_write_value [0:1];
    wire [31:0] staged_access [0:7];
    assign staged_message[0]=staged_message_0; assign staged_message[1]=staged_message_1;
    assign staged_message[2]=staged_message_2; assign staged_message[3]=staged_message_3;
    assign staged_cv[0]=staged_cv_0; assign staged_cv[1]=staged_cv_1;
    assign staged_write_address[0]=staged_write_address_0; assign staged_write_address[1]=staged_write_address_1;
    assign staged_write_value[0]=staged_write_value_0; assign staged_write_value[1]=staged_write_value_1;
    assign staged_access[0]=staged_access_0; assign staged_access[1]=staged_access_1;
    assign staged_access[2]=staged_access_2; assign staged_access[3]=staged_access_3;
    assign staged_access[4]=staged_access_4; assign staged_access[5]=staged_access_5;
    assign staged_access[6]=staged_access_6; assign staged_access[7]=staged_access_7;
    integer ext_word;
    always @(*) begin
        payload_data = 0;
        if (kind == 1) begin
            if (payload_index < 4)
                payload_data = blake_staged_txn_id[payload_index*8 +: 8];
            else if (payload_index < 8)
                payload_data = blake_staged_service_id[(payload_index-4)*8 +: 8];
            else if (payload_index == 8) payload_data = 8'h01;
            else if (payload_index == 9) payload_data = 0;
            else if (payload_index < 74) begin
                ext_word = (payload_index-10) / 16;
                payload_data = staged_message[ext_word][((payload_index-10)%16)*8 +: 8];
            end else if (payload_index < 106) begin
                ext_word = (payload_index-74) / 16;
                payload_data = staged_cv[ext_word][((payload_index-74)%16)*8 +: 8];
            end else
                payload_data = staged_metadata[(payload_index-106)*8 +: 8];
        end else if (kind == 2) begin
            if (payload_index < 4)
                payload_data = blake_staged_txn_id[payload_index*8 +: 8];
            else if (payload_index < 8)
                payload_data = blake_staged_next_pc[(payload_index-4)*8 +: 8];
            else if (payload_index < 12)
                payload_data = blake_staged_next_fp[(payload_index-8)*8 +: 8];
            else if (payload_index == 12) payload_data = staged_write_count;
            else if (payload_index < 13 + staged_write_count*20) begin
                ext_word = (payload_index-13) / 20;
                if (((payload_index-13)%20) < 4)
                    payload_data = staged_write_address[ext_word][((payload_index-13)%20)*8 +: 8];
                else
                    payload_data = staged_write_value[ext_word][(((payload_index-13)%20)-4)*8 +: 8];
            end else if (payload_index == 13 + staged_write_count*20)
                payload_data = 0; // n_deferred
            else if (payload_index == 14 + staged_write_count*20)
                payload_data = 8; // n_accesses
            else begin
                ext_word = (payload_index-(15 + staged_write_count*20)) / 4;
                payload_data = staged_access[ext_word][((payload_index-(15 + staged_write_count*20))%4)*8 +: 8];
            end
        end else if (kind == 3) begin
            case (payload_index)
                0: payload_data = staged_txn_id[7:0];
                1: payload_data = staged_txn_id[15:8];
                2: payload_data = staged_txn_id[23:16];
                3: payload_data = staged_txn_id[31:24];
                4: payload_data = staged_next_pc[7:0];
                5: payload_data = staged_next_pc[15:8];
                6: payload_data = staged_next_pc[23:16];
                7: payload_data = staged_next_pc[31:24];
                8: payload_data = staged_next_fp[7:0];
                9: payload_data = staged_next_fp[15:8];
                10: payload_data = staged_next_fp[23:16];
                11: payload_data = staged_next_fp[31:24];
                12: payload_data = scalar_staged_write_count;
                default: begin
                    if (scalar_staged_write_count != 0) begin
                        case (payload_index)
                            13: payload_data = scalar_staged_write_address[7:0];
                            14: payload_data = scalar_staged_write_address[15:8];
                            15: payload_data = scalar_staged_write_address[23:16];
                            16: payload_data = scalar_staged_write_address[31:24];
                            17: payload_data = scalar_staged_write_value[7:0];
                            18: payload_data = scalar_staged_write_value[15:8];
                            19: payload_data = scalar_staged_write_value[23:16];
                            20: payload_data = scalar_staged_write_value[31:24];
                            21: payload_data = scalar_staged_write_value[39:32];
                            22: payload_data = scalar_staged_write_value[47:40];
                            23: payload_data = scalar_staged_write_value[55:48];
                            24: payload_data = scalar_staged_write_value[63:56];
                            25: payload_data = scalar_staged_write_value[71:64];
                            26: payload_data = scalar_staged_write_value[79:72];
                            27: payload_data = scalar_staged_write_value[87:80];
                            28: payload_data = scalar_staged_write_value[95:88];
                            29: payload_data = scalar_staged_write_value[103:96];
                            30: payload_data = scalar_staged_write_value[111:104];
                            31: payload_data = scalar_staged_write_value[119:112];
                            32: payload_data = scalar_staged_write_value[127:120];
                            33: payload_data = 0;
                            34: payload_data = scalar_staged_access_count;
                            35: payload_data = scalar_staged_access_0[7:0];
                            36: payload_data = scalar_staged_access_0[15:8];
                            37: payload_data = scalar_staged_access_0[23:16];
                            38: payload_data = scalar_staged_access_0[31:24];
                            39: payload_data = scalar_staged_access_1[7:0];
                            40: payload_data = scalar_staged_access_1[15:8];
                            41: payload_data = scalar_staged_access_1[23:16];
                            42: payload_data = scalar_staged_access_1[31:24];
                            43: payload_data = scalar_staged_access_2[7:0];
                            44: payload_data = scalar_staged_access_2[15:8];
                            45: payload_data = scalar_staged_access_2[23:16];
                            46: payload_data = scalar_staged_access_2[31:24];
                            default: payload_data = 0;
                        endcase
                    end else if (scalar_staged_deferred) begin
                        case (payload_index)
                            13: payload_data = 1;
                            14: payload_data = scalar_staged_deferred_target[7:0];
                            15: payload_data = scalar_staged_deferred_target[15:8];
                            16: payload_data = scalar_staged_deferred_target[23:16];
                            17: payload_data = scalar_staged_deferred_target[31:24];
                            18: payload_data = scalar_staged_deferred_local[7:0];
                            19: payload_data = scalar_staged_deferred_local[15:8];
                            20: payload_data = scalar_staged_deferred_local[23:16];
                            21: payload_data = scalar_staged_deferred_local[31:24];
                            22: payload_data = scalar_staged_access_count;
                            23: payload_data = scalar_staged_access_0[7:0];
                            24: payload_data = scalar_staged_access_0[15:8];
                            25: payload_data = scalar_staged_access_0[23:16];
                            26: payload_data = scalar_staged_access_0[31:24];
                            27: payload_data = scalar_staged_access_1[7:0];
                            28: payload_data = scalar_staged_access_1[15:8];
                            29: payload_data = scalar_staged_access_1[23:16];
                            30: payload_data = scalar_staged_access_1[31:24];
                            31: payload_data = scalar_staged_access_2[7:0];
                            32: payload_data = scalar_staged_access_2[15:8];
                            33: payload_data = scalar_staged_access_2[23:16];
                            34: payload_data = scalar_staged_access_2[31:24];
                            default: payload_data = 0;
                        endcase
                    end else begin
                        case (payload_index)
                            13: payload_data = 0;
                            14: payload_data = scalar_staged_access_count;
                            15: payload_data = scalar_staged_access_0[7:0];
                            16: payload_data = scalar_staged_access_0[15:8];
                            17: payload_data = scalar_staged_access_0[23:16];
                            18: payload_data = scalar_staged_access_0[31:24];
                            19: payload_data = scalar_staged_access_1[7:0];
                            20: payload_data = scalar_staged_access_1[15:8];
                            21: payload_data = scalar_staged_access_1[23:16];
                            22: payload_data = scalar_staged_access_1[31:24];
                            23: payload_data = scalar_staged_access_2[7:0];
                            24: payload_data = scalar_staged_access_2[15:8];
                            25: payload_data = scalar_staged_access_2[23:16];
                            26: payload_data = scalar_staged_access_2[31:24];
                            default: payload_data = 0;
                        endcase
                    end
                end
            endcase
        end else if (kind == 4) begin
            case (payload_index)
                0: payload_data = short_txn_id[0 +: 8];
                1: payload_data = short_txn_id[15:8];
                2: payload_data = short_txn_id[23:16];
                3: payload_data = short_txn_id[31:24];
                4: payload_data = short_detail;
                default: payload_data = 0;
            endcase
        end else if (kind == 5) begin
            case (payload_index)
                0: payload_data = blake_service_pending ? 8'h02 :
                                              (blake_result_pending || result_pending) ? 8'h01 : 8'h00;
                1: payload_data = short_txn_id[7:0];
                2: payload_data = short_txn_id[15:8];
                3: payload_data = short_txn_id[23:16];
                4: payload_data = short_txn_id[31:24];
                5: payload_data = short_detail;
                6: payload_data = retire_seq[7:0];
                7: payload_data = retire_seq[15:8];
                8: payload_data = retire_seq[23:16];
                9: payload_data = retire_seq[31:24];
                10: payload_data = last_fault;
                11: payload_data = committed_pc[7:0];
                12: payload_data = committed_pc[15:8];
                13: payload_data = committed_pc[23:16];
                14: payload_data = committed_pc[31:24];
                15: payload_data = committed_fp[7:0];
                16: payload_data = committed_fp[15:8];
                17: payload_data = committed_fp[23:16];
                18: payload_data = committed_fp[31:24];
                19: payload_data = state_valid;
                default: payload_data = 0;
            endcase
        end else if (kind == 6) begin
            case (payload_index)
                0: payload_data = 1;
                1: payload_data = short_detail;
                2: payload_data = 0;
                3: payload_data = 1;
                4: payload_data = 16;
                5: payload_data = 0;
                6: payload_data = 8'h06;
                7: payload_data = 0;
                8: payload_data = 0;
                9: payload_data = 0;
                10: payload_data = 8'h31;
                11: payload_data = 8'h43;
                12: payload_data = 8'h53;
                13: payload_data = 8'h4c;
                default: payload_data = 0;
            endcase
        end else if (kind == 7) begin
            case (payload_index)
                0: payload_data = short_txn_id[7:0];
                1: payload_data = short_txn_id[15:8];
                2: payload_data = short_txn_id[23:16];
                3: payload_data = short_txn_id[31:24];
                4: payload_data = retire_seq[7:0];
                5: payload_data = retire_seq[15:8];
                6: payload_data = retire_seq[23:16];
                7: payload_data = retire_seq[31:24];
                8: payload_data = committed_pc[7:0];
                9: payload_data = committed_pc[15:8];
                10: payload_data = committed_pc[23:16];
                11: payload_data = committed_pc[31:24];
                12: payload_data = committed_fp[7:0];
                13: payload_data = committed_fp[15:8];
                14: payload_data = committed_fp[23:16];
                15: payload_data = committed_fp[31:24];
                default: payload_data = 0;
            endcase
        end
    end

endmodule

`default_nettype wire

module tb_lsc1_response_payload_mux;
    reg [2:0] kind; reg [15:0] payload_index;
    reg [31:0] blake_staged_txn_id, blake_staged_service_id, blake_staged_next_pc, blake_staged_next_fp;
    reg [127:0] staged_message [0:3]; reg [127:0] staged_cv [0:1]; reg [127:0] staged_metadata;
    reg [1:0] staged_write_count; reg [31:0] staged_write_address [0:1];
    reg [127:0] staged_write_value [0:1]; reg [31:0] staged_access [0:7];
    reg [31:0] staged_txn_id, staged_next_pc, staged_next_fp;
    reg [1:0] scalar_staged_write_count; reg scalar_staged_deferred;
    reg [7:0] scalar_staged_access_count; reg [31:0] scalar_staged_write_address;
    reg [127:0] scalar_staged_write_value;
    reg [31:0] scalar_staged_deferred_target, scalar_staged_deferred_local;
    reg [31:0] scalar_staged_access_0, scalar_staged_access_1, scalar_staged_access_2;
    reg [31:0] short_txn_id; reg [7:0] short_detail;
    reg blake_service_pending, blake_result_pending, result_pending;
    reg [31:0] retire_seq, committed_pc, committed_fp; reg [7:0] last_fault; reg state_valid;
    wire [7:0] dut_data, golden_data; integer i, j;
    wire [127:0] staged_message_0=staged_message[0], staged_message_1=staged_message[1];
    wire [127:0] staged_message_2=staged_message[2], staged_message_3=staged_message[3];
    wire [127:0] staged_cv_0=staged_cv[0], staged_cv_1=staged_cv[1];
    wire [31:0] staged_write_address_0=staged_write_address[0], staged_write_address_1=staged_write_address[1];
    wire [127:0] staged_write_value_0=staged_write_value[0], staged_write_value_1=staged_write_value[1];
    wire [31:0] staged_access_0=staged_access[0], staged_access_1=staged_access[1];
    wire [31:0] staged_access_2=staged_access[2], staged_access_3=staged_access[3];
    wire [31:0] staged_access_4=staged_access[4], staged_access_5=staged_access[5];
    wire [31:0] staged_access_6=staged_access[6], staged_access_7=staged_access[7];

    lsc1_response_payload_mux dut (.*, .payload_data(dut_data));
    lsc1_response_payload_mux_golden golden (.*, .payload_data(golden_data));

    task automatic check_schema; input [2:0] schema; input integer length; begin
        kind = schema;
        for (i = 0; i < length; i = i + 1) begin
            payload_index = i; #1;
            if (dut_data !== golden_data)
                $fatal(1, "schema %0d byte %0d got=%02x expected=%02x", schema, i, dut_data, golden_data);
        end
        if (schema >= 3) begin
            payload_index = length; #1;
            if (dut_data !== 0 || golden_data !== 0) $fatal(1, "schema %0d first out-of-range nonzero", schema);
            payload_index = length + 16; #1;
            if (dut_data !== 0 || golden_data !== 0) $fatal(1, "schema %0d distant out-of-range nonzero", schema);
        end
    end endtask

    initial begin
        blake_staged_txn_id=32'h04030201; blake_staged_service_id=32'h14131211;
        blake_staged_next_pc=32'h24232221; blake_staged_next_fp=32'h34333231;
        for (i=0;i<4;i=i+1) for(j=0;j<16;j=j+1) staged_message[i][j*8 +: 8]=8'h40+i*16+j;
        for (i=0;i<2;i=i+1) for(j=0;j<16;j=j+1) staged_cv[i][j*8 +: 8]=8'h80+i*16+j;
        for(j=0;j<16;j=j+1) staged_metadata[j*8 +: 8]=8'ha0+j;
        for(i=0;i<2;i=i+1) begin
            staged_write_address[i]=32'hb4b3b2b1+i*32'h04040404;
            for(j=0;j<16;j=j+1) staged_write_value[i][j*8 +: 8]=8'hc0+i*16+j;
        end
        for(i=0;i<8;i=i+1) staged_access[i]=32'h50403020+i*32'h04040404;
        staged_txn_id=32'hd4d3d2d1; staged_next_pc=32'he4e3e2e1; staged_next_fp=32'hf4f3f2f1;
        scalar_staged_write_address=32'h67666564;
        for(j=0;j<16;j=j+1) scalar_staged_write_value[j*8 +: 8]=8'h70+j;
        scalar_staged_deferred_target=32'h87868584; scalar_staged_deferred_local=32'h97969594;
        scalar_staged_access_count=3; scalar_staged_access_0=32'ha7a6a5a4;
        scalar_staged_access_1=32'hb7b6b5b4; scalar_staged_access_2=32'hc7c6c5c4;
        short_txn_id=32'h37363534; short_detail=8'h47; retire_seq=32'h57565554;
        committed_pc=32'h67666564; committed_fp=32'h77767574; last_fault=8'h87; state_valid=1;
        blake_service_pending=1; blake_result_pending=0; result_pending=0;
        staged_write_count=0; scalar_staged_write_count=0; scalar_staged_deferred=0;
        check_schema(1,122);
        staged_write_count=0; check_schema(2,47);
        staged_write_count=1; check_schema(2,67);
        staged_write_count=2; check_schema(2,87);
        scalar_staged_write_count=1; scalar_staged_deferred=0; check_schema(3,47);
        scalar_staged_write_count=0; scalar_staged_deferred=1; check_schema(3,35);
        scalar_staged_write_count=0; scalar_staged_deferred=0; check_schema(3,27);
        check_schema(4,5); check_schema(5,20); check_schema(6,14); check_schema(7,16);
        kind=0; payload_index=0; #1; if(dut_data!==0) $fatal(1, "default kind zero failed");
        kind=3; payload_index=17; scalar_staged_write_count=1;
        scalar_staged_write_value[7:0]=8'h19; #1;
        if(dut_data!==8'h19) $fatal(1, "scalar staged source toggle failed");
        kind=2; staged_write_count=2; payload_index=33; staged_write_address[1]=32'h2b2a2928; #1;
        if(dut_data!==8'h28) $fatal(1, "BLAKE3 variable-offset source toggle failed");
        $display("PASS: seven response schemas, scalar variants, BLAKE3 write counts, source toggles, and default-zero offsets");
        $finish;
    end
endmodule
