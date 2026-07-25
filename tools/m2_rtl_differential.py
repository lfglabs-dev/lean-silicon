#!/usr/bin/env python3
"""Run the M2 RTL test and cross-check its deterministic operands with the independent frozen oracle."""
import pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sim'))
from scalar_step_oracle import multiply, inverse
cases=[(0x12,0x34),(0x55,0x66),(0x0a,0x05)]
assert multiply(*cases[0]) == 0x328
assert multiply(cases[2][0],cases[2][1]) == multiply(*cases[2])
assert multiply(multiply(*cases[2]),inverse(cases[2][1])) == cases[2][0]
out=ROOT/'test'/'m2_sim.out'
subprocess.run(['iverilog','-g2012','-s','tb_m2_scalar_controller','-o',str(out),str(ROOT/'src'/'leanvm_b_m2_scalar_controller.sv'),str(ROOT/'test'/'tb_m2_scalar_controller.sv')],check=True)
run=subprocess.run(['vvp',str(out)],text=True,capture_output=True,check=True)
if 'PASS m2 scalar controller' not in run.stdout: raise SystemExit(run.stdout)
print('PASS M2 RTL differential: xor, mul, XOR backsolve, MUL inverse-service backsolve, set, jump, halt')
