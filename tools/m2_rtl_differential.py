#!/usr/bin/env python3
"""Drive Cargo-vetted deterministic vectors through the M2 RTL."""
import argparse, pathlib, subprocess, sys, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sim'))
sys.path.insert(0,str(ROOT/'tools'))
from scalar_step_oracle import multiply, inverse
from frozen_upstream_differential import generate_cases
parser=argparse.ArgumentParser()
parser.add_argument("--upstream", type=pathlib.Path, required=True)
args=parser.parse_args()
seed=0xc308034a
count=64
subprocess.run([
    sys.executable, str(ROOT/'tools'/'frozen_upstream_differential.py'),
    '--upstream', str(args.upstream), '--seed', hex(seed), '--cases', str(count)
], check=True)
cases=generate_cases(seed,count)
assert multiply(*cases[0]) == 0x328
assert multiply(cases[2][0],cases[2][1]) == multiply(*cases[2])
assert multiply(multiply(*cases[2]),inverse(cases[2][1])) == cases[2][0]
with tempfile.TemporaryDirectory(prefix='m2-rtl-differential-') as directory:
    tmp=pathlib.Path(directory)
    fixed_out=tmp/'fixed.vvp'
    subprocess.run(['iverilog','-g2012','-s','tb_m2_scalar_controller','-o',str(fixed_out),
                    str(ROOT/'src'/'leanvm_b_m2_scalar_controller.sv'),
                    str(ROOT/'test'/'tb_m2_scalar_controller.sv')],check=True)
    fixed=subprocess.run(['vvp',str(fixed_out)],text=True,capture_output=True,check=True)
    if 'PASS m2 scalar controller' not in fixed.stdout: raise SystemExit(fixed.stdout)

    statements=[]
    for index,(a,b) in enumerate(cases):
        expected_xor=a^b
        expected_mul=multiply(a,b)
        statements.append(
            f"reset_dut; load(2,128'h{a:032x}); load(3,128'h{b:032x}); "
            f"issue(0,2,3,4); issue(1,2,3,5); "
            f"if(dut.mem[4]!==128'h{expected_xor:032x} || "
            f"dut.mem[5]!==128'h{expected_mul:032x}) $fatal(1,\"case {index}\");"
        )
    bench=tmp/'tb_seeded.sv'
    bench.write_text("""`timescale 1ns/1ps
module tb_seeded;
 reg clk=0,rst_n=0,load_valid=0,instr_valid=0,inverse_valid=0;
 reg [31:0] load_addr=0,instr_a=0,instr_b=0,instr_c=0;
 reg [127:0] load_value=0,instr_imm=0,inverse_value=0; reg [2:0] instr_op=0;
 wire instr_ready,inverse_req,retired,fault; wire [127:0] inverse_operand; wire [31:0] pc,fp;
 leanvm_b_m2_scalar_controller #(.MEM_WORDS(8)) dut(.*);
 always #5 clk=~clk;
 task reset_dut; begin @(negedge clk);rst_n=0;@(negedge clk);rst_n=1;end endtask
 task load; input[31:0] a;input[127:0] v;begin @(negedge clk);load_addr=a;load_value=v;load_valid=1;@(negedge clk);load_valid=0;end endtask
 task issue;input[2:0] op;input[31:0] a,b,c;begin @(negedge clk);while(!instr_ready)@(negedge clk);instr_op=op;instr_a=a;instr_b=b;instr_c=c;instr_valid=1;@(negedge clk);instr_valid=0;while(!retired&&!fault)@(negedge clk);if(fault)$fatal(1,"unexpected fault");end endtask
 initial begin
""" + "\n".join(statements) + """
  $display("PASS 64 seeded Cargo-vetted RTL vectors");$finish;
 end
endmodule
""")
    seeded_out=tmp/'seeded.vvp'
    subprocess.run(['iverilog','-g2012','-s','tb_seeded','-o',str(seeded_out),
                    str(ROOT/'src'/'leanvm_b_m2_scalar_controller.sv'),str(bench)],check=True)
    seeded=subprocess.run(['vvp',str(seeded_out)],text=True,capture_output=True,check=True)
    if f'PASS {count} seeded Cargo-vetted RTL vectors' not in seeded.stdout:
        raise SystemExit(seeded.stdout)
print('PASS M2 RTL differential: 64 seeded Cargo-vetted cases driven through RTL plus controller edge regressions')
