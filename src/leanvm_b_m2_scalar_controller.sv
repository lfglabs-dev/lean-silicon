/* M2 scalar controller: wide test/service boundary, not the byte-RPC ABI. */
`default_nettype none
module leanvm_b_m2_scalar_controller #(
    parameter integer MEM_WORDS = 64
) (
    input wire clk, input wire rst_n,
    input wire load_valid, input wire [31:0] load_addr, input wire [127:0] load_value,
    input wire instr_valid, output wire instr_ready,
    input wire [2:0] instr_op, input wire [31:0] instr_a, input wire [31:0] instr_b,
    input wire [31:0] instr_c, input wire [127:0] instr_imm,
    /* Isolated host-service assumption for MUL back-solving. */
    output reg inverse_req, output reg [127:0] inverse_operand,
    input wire inverse_valid, input wire [127:0] inverse_value,
    output reg retired, output reg fault, output reg [31:0] pc, output reg [31:0] fp
);
    localparam [2:0] OP_XOR=3'd0, OP_MUL=3'd1, OP_SET=3'd2, OP_JUMP=3'd3, OP_HALT=3'd4;
    localparam [1:0] S_IDLE=2'd0, S_INV=2'd1, S_FAULT=2'd2, S_HALT=2'd3;
    reg [1:0] state;
    reg [127:0] mem [0:MEM_WORDS-1]; reg written [0:MEM_WORDS-1];
    reg [31:0] pending_missing, pending_result_addr; reg [127:0] pending_result;
    integer i;
    function automatic [127:0] xtime(input [127:0] x);
      begin xtime={x[126:0],1'b0} ^ (x[127] ? 128'h87 : 128'b0); end
    endfunction
    function automatic [127:0] gf_mul(input [127:0] x, input [127:0] y);
      integer n; reg [127:0] a,b,z;
      begin a=x; b=y; z=0; for(n=0;n<128;n=n+1) begin if(b[0]) z=z^a; a=xtime(a); b=b>>1; end gf_mul=z; end
    endfunction
    function automatic [32:0] reverse_g(input [127:0] value);
      integer n; reg [127:0] candidate;
      begin candidate=128'd1; reverse_g=0; for(n=0;n<MEM_WORDS;n=n+1) begin if(candidate==value) reverse_g={1'b1,n[31:0]}; candidate=xtime(candidate); end end
    endfunction
    assign instr_ready = state == S_IDLE && !load_valid;
    always @(posedge clk) begin : controller
      reg [31:0] a,b,c,next_pc,next_fp; reg [127:0] av,bv,cv,result,missing; reg aw,bw,cw;
      reg reverse_ok_d, reverse_ok_f; reg [31:0] reverse_d, reverse_f;
      retired <= 1'b0; inverse_req <= 1'b0;
      if(!rst_n) begin
        state<=S_IDLE; fault<=0; pc<=0; fp<=0; inverse_operand<=0; pending_missing<=0; pending_result_addr<=0; pending_result<=0;
        for(i=0;i<MEM_WORDS;i=i+1) begin mem[i]<=0; written[i]<=0; end
      end else if (load_valid && state==S_IDLE) begin
        if(load_addr >= MEM_WORDS) begin fault<=1'b1; state<=S_FAULT; end
        else if(written[load_addr] && mem[load_addr] != load_value) begin fault<=1'b1; state<=S_FAULT; end
        else begin mem[load_addr]<=load_value; written[load_addr]<=1'b1; end
      end else if(state==S_INV) begin
        inverse_req<=1'b1;
        if(inverse_valid) begin
          inverse_req<=1'b0;
          missing=gf_mul(pending_result,inverse_value);
          if((written[pending_missing] && mem[pending_missing]!=missing) ||
             (written[pending_result_addr] && mem[pending_result_addr]!=pending_result)) begin fault<=1'b1; state<=S_FAULT; end
          else begin mem[pending_missing]<=missing; written[pending_missing]<=1'b1; mem[pending_result_addr]<=pending_result; written[pending_result_addr]<=1'b1; pc<=pc+1'b1; retired<=1'b1; state<=S_IDLE; end
        end
      end else if(state==S_IDLE && instr_valid) begin
        {aw,a}= {1'b0,fp} + {1'b0,instr_a};
        {bw,b}= {1'b0,fp} + {1'b0,instr_b};
        {cw,c}= {1'b0,fp} + {1'b0,instr_c};
        case(instr_op)
          OP_SET: begin
            if(aw || a >= MEM_WORDS || pc == 32'hffffffff || (written[a] && mem[a]!=instr_imm)) begin fault<=1'b1; state<=S_FAULT; end
            else begin mem[a]<=instr_imm; written[a]<=1'b1; pc<=pc+1'b1; retired<=1'b1; end
          end
          OP_XOR, OP_MUL: begin
            if(aw || bw || cw || a >= MEM_WORDS || b >= MEM_WORDS || c >= MEM_WORDS || pc == 32'hffffffff) begin fault<=1'b1; state<=S_FAULT; end else begin
              aw=written[a]; bw=written[b]; cw=written[c]; av=aw?mem[a]:0; bv=bw?mem[b]:0; cv=cw?mem[c]:0;
              result=(instr_op==OP_XOR)?(av^bv):gf_mul(av,bv);
              if(cw && (aw != bw)) begin
                if(instr_op==OP_XOR) begin
                  missing=cv^(aw?av:bv);
                  if(written[aw?b:a] && mem[aw?b:a]!=missing) begin fault<=1'b1; state<=S_FAULT; end
                  else begin mem[aw?b:a]<=missing; written[aw?b:a]<=1'b1; mem[c]<=cv; written[c]<=1'b1; pc<=pc+1'b1; retired<=1'b1; end
                end else if((aw?av:bv)==0) begin fault<=1'b1; state<=S_FAULT; end
                else begin pending_missing<=aw?b:a; pending_result_addr<=c; pending_result<=cv; inverse_operand<=aw?av:bv; state<=S_INV; inverse_req<=1'b1; end
              end else if(written[c] && mem[c]!=result) begin fault<=1'b1; state<=S_FAULT; end
              else begin mem[c]<=result; written[c]<=1'b1; pc<=pc+1'b1; retired<=1'b1; end
            end
          end
          OP_JUMP: begin
            if(aw || bw || cw || a >= MEM_WORDS || b >= MEM_WORDS || c >= MEM_WORDS) begin fault<=1'b1; state<=S_FAULT; end else begin
              av=written[a]?mem[a]:0; bv=written[b]?mem[b]:0; cv=written[c]?mem[c]:0;
              if(av==0) begin
                if(pc == 32'hffffffff) begin fault<=1'b1; state<=S_FAULT; end
                else begin pc<=pc+1'b1; retired<=1'b1; end
              end else begin
                {reverse_ok_d,reverse_d}=reverse_g(bv); {reverse_ok_f,reverse_f}=reverse_g(cv);
                if(!reverse_ok_d || !reverse_ok_f) begin fault<=1'b1; state<=S_FAULT; end else begin pc<=reverse_d; fp<=reverse_f; retired<=1'b1; end
              end
            end
          end
          OP_HALT: begin if(fp!=0) begin fault<=1'b1; state<=S_FAULT; end else begin retired<=1'b1; state<=S_HALT; end end
          default: begin fault<=1'b1; state<=S_FAULT; end
        endcase
      end
    end
endmodule
`default_nettype wire
