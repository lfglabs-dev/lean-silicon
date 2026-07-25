#!/usr/bin/env python3
"""Drive Cargo-vetted deterministic vectors through the M2 RTL."""
import argparse, datetime, hashlib, json, pathlib, subprocess, sys, tempfile
import types
ROOT=pathlib.Path(__file__).resolve().parents[1]
SCALAR_GATE_SOURCE=ROOT/'tools'/'frozen_upstream_differential.py'
scalar_gate=types.ModuleType('_tracked_frozen_upstream_differential')
scalar_gate.__file__=str(SCALAR_GATE_SOURCE)
sys.modules[scalar_gate.__name__]=scalar_gate
try:
    exec(compile(SCALAR_GATE_SOURCE.read_bytes(), str(SCALAR_GATE_SOURCE), 'exec'),
         scalar_gate.__dict__)
finally:
    del sys.modules[scalar_gate.__name__]
COMMIT,REPOSITORY=scalar_gate.COMMIT,scalar_gate.REPOSITORY
candidate_head,generate_cases=scalar_gate.candidate_head,scalar_gate.generate_cases
require_checkout=scalar_gate.require_checkout
multiply,inverse=scalar_gate.ORACLE.multiply,scalar_gate.ORACLE.inverse
parser=argparse.ArgumentParser()
parser.add_argument("--upstream", type=pathlib.Path, required=True)
parser.add_argument("--seed", type=lambda value: int(value, 0), default=0xc308034a)
parser.add_argument("--cases", type=int, default=64)
parser.add_argument("--record", type=pathlib.Path, help="write reproducibility metadata as JSON")
parser.add_argument("--rust-toolchain", default="1.88.0")
args=parser.parse_args()
if args.cases <= 0: raise SystemExit('--cases must be positive')
tested_head=candidate_head()
preflight=require_checkout(args.upstream)
seed=args.seed
count=args.cases
subprocess.run([
    sys.executable, str(ROOT/'tools'/'frozen_upstream_differential.py'),
    '--upstream', str(args.upstream), '--seed', hex(seed), '--cases', str(count),
    '--rust-toolchain', args.rust_toolchain,
], check=True)
cases=generate_cases(seed,count)
if count >= 1: assert multiply(*cases[0]) == 0x328
if count >= 3:
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
  $display("PASS {count} seeded Cargo-vetted RTL vectors");$finish;
 end
endmodule
""".format(count=count))
    seeded_out=tmp/'seeded.vvp'
    subprocess.run(['iverilog','-g2012','-s','tb_seeded','-o',str(seeded_out),
                    str(ROOT/'src'/'leanvm_b_m2_scalar_controller.sv'),str(bench)],check=True)
    seeded=subprocess.run(['vvp',str(seeded_out)],text=True,capture_output=True,check=True)
    if f'PASS {count} seeded Cargo-vetted RTL vectors' not in seeded.stdout:
        raise SystemExit(seeded.stdout)
postflight=require_checkout(args.upstream)
if candidate_head() != tested_head:
    raise SystemExit('candidate checkout rejected: HEAD changed during differential')
message=f'PASS M2 RTL differential: {count} seeded Cargo-vetted cases driven through RTL plus controller edge regressions'
if args.record:
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps({
        'schema': 1, 'result': 'PASS', 'exit_status': 0,
        'tested_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'tested_repo_head': tested_head,
        'upstream': {'repository': REPOSITORY, 'sha': COMMIT, 'preflight': preflight,
                     'postflight': postflight,
                     'cargo_lock_sha256': digest(args.upstream/'Cargo.lock')},
        'profile': f'M2 XOR and MUL only; {count} deterministic seeded full-width vectors plus fixed controller edge regressions.',
        'limits': 'M2 does not implement full upstream execution; no DEREF, JUMP, BLAKE3, write-once memory, pointer resolution, or trace equivalence is claimed.',
        'seed': f'{seed:#x}', 'case_count': count,
        'commands': {'scalar_gate': [sys.executable, str(ROOT/'tools'/'frozen_upstream_differential.py'), '--upstream', str(args.upstream), '--seed', hex(seed), '--cases', str(count), '--rust-toolchain', args.rust_toolchain],
                     'iverilog_fixed': ['iverilog', '-g2012', '-s', 'tb_m2_scalar_controller'],
                     'iverilog_seeded': ['iverilog', '-g2012', '-s', 'tb_seeded'],
                     'vvp_fixed_exit_status': 0, 'vvp_seeded_exit_status': 0},
        'rust_toolchain': args.rust_toolchain,
        'provenance': {'checker_sha256': digest(pathlib.Path(__file__)),
                       'scalar_gate_sha256': digest(SCALAR_GATE_SOURCE),
                       'rtl_sha256': digest(ROOT/'src/leanvm_b_m2_scalar_controller.sv')},
    }, indent=2, sort_keys=True)+'\n')
print(message)
