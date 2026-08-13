#!/usr/bin/env python3
"""Reproducible HOST synthesis/formal lane for the canonical full LSC-1 top."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "assurance/full-lsc1-netlist/plan.json"
BOUNDED_EDGES = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(argv: list[str]) -> str:
    return subprocess.check_output(argv, cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()


def run(name: str, argv: list[str], receipt: dict, *, cwd: Path = ROOT,
        expect: int = 0, timeout: int | None = None,
        env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=timeout, env=env)
    receipt["commands"].append({"name": name, "argv": argv,
                                "exit_code": completed.returncode})
    if completed.returncode != expect:
        sys.stderr.write(completed.stdout)
        raise SystemExit(f"{name}: expected exit {expect}, got {completed.returncode}")
    return completed.stdout


def require_clean() -> None:
    """Compare tracked working-tree bytes to HEAD despite index hint flags."""
    index_fd, index_name = tempfile.mkstemp(prefix="full-lsc1-netlist-index-")
    os.close(index_fd)
    os.unlink(index_name)
    try:
        env = os.environ | {"GIT_INDEX_FILE": index_name}
        subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
        clean = subprocess.run(["git", "update-index", "--really-refresh", "-q"],
                               cwd=ROOT, env=env).returncode == 0
    finally:
        Path(index_name).unlink(missing_ok=True)
    if not clean:
        raise SystemExit("tracked checkout must match HEAD")


def prepare_private_cache(cache: Path) -> None:
    """Create a private cache, but never change permissions on an existing path."""
    if cache.exists():
        if not cache.is_dir():
            raise SystemExit("cache must be a directory")
    else:
        cache.mkdir(parents=True, mode=0o700)
    if stat.S_IMODE(cache.stat().st_mode) & 0o077:
        raise SystemExit("cache must deny group/other access")


def canonical_rtl_env(**updates: str) -> dict[str, str]:
    """Return an environment that cannot redirect tests away from pinned RTL."""
    env = os.environ.copy()
    env.pop("LSC1_RTL_DIR", None)
    env.pop("LSC1_SYNTH_NETLIST", None)
    env.update(updates)
    return env


def bounded_sat_argv(read_script: str) -> list[str]:
    """Build the mandatory bound including one operational post-reset state."""
    return ["yosys", "-Q", "-p", read_script +
            f"sat -verify -prove-asserts -set-assumes -seq {BOUNDED_EDGES} "
            "-set-def-inputs"]


def classify_induction(name: str, returncode: int, output: str, *,
                       timed_out: bool = False) -> str:
    """Classify only explicit resource exhaustion as blocked; fail closed otherwise."""
    if returncode == 0:
        return "pass"
    lowered = output.lower()
    if "proof did fail" in lowered:
        sys.stderr.write(output)
        raise SystemExit(f"{name}: temporal induction found a counterexample")
    if timed_out or "maximum number of time steps" in lowered:
        return "blocked"
    sys.stderr.write(output)
    raise SystemExit(f"{name}: temporal induction tool failure (exit {returncode})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", required=True, type=Path)
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    if cache == ROOT or ROOT in cache.parents:
        raise SystemExit("cache must be outside checkout")
    prepare_private_cache(cache)
    require_clean()
    plan = json.loads(PLAN_PATH.read_text())
    head = capture(["git", "rev-parse", "HEAD"])
    tree = capture(["git", "rev-parse", "HEAD^{tree}"])
    base = plan["source_commit"]
    if capture(["git", "rev-parse", f"{base}^{{tree}}"] ) != plan["source_tree"]:
        raise SystemExit("pinned source tree mismatch")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=ROOT, check=True)
    for tool in ("yosys", "iverilog", "vvp"):
        if not shutil.which(tool):
            raise SystemExit(f"required HOST tool missing: {tool}")

    rtl = [ROOT / item for item in plan["inputs"]]
    receipt = {
        "schema": "lean-silicon/full-lsc1-netlist-receipt/v1",
        "status": "running", "source_commit": base,
        "source_tree": plan["source_tree"], "checkout_head": head,
        "checkout_tree": tree, "plan_sha256": sha256(PLAN_PATH),
        "host_mandatory": True, "physical_artifacts_generated": False,
        "toolchain": {"python": sys.version.replace("\n", " "),
                      "yosys": capture(["yosys", "-V"]),
                      "iverilog": capture(["iverilog", "-V"]).splitlines()[0]},
        "manifest": [{"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for path in rtl],
        "top": plan["top"], "observables": plan["observables"],
        "constraints": plan["constraints"], "commands": [], "proofs": {},
        "unbounded_experiments": plan["unbounded_experiments"],
        "covers": {}, "mutations": [], "limits": plan["excluded"][:],
    }
    netlist = cache / "lean_silicon_lsc1.generic.v"
    rtl_args = " ".join(str(path.relative_to(ROOT)) for path in rtl)
    synth_script = (
        f"read_verilog -sv {rtl_args}; hierarchy -check -top {plan['top']}; "
        f"proc; flatten; opt; fsm; opt; memory; opt; check; "
        f"rename {plan['top']} lean_silicon_lsc1_netlist; "
        f"write_verilog -noattr {netlist}"
    )
    run("synthesize_generic_netlist", ["yosys", "-Q", "-p", synth_script], receipt)
    receipt["netlist"] = {"path": netlist.name, "sha256": sha256(netlist),
                          "bytes": netlist.stat().st_size}

    netlist_env = canonical_rtl_env(LSC1_SYNTH_NETLIST=str(netlist))
    run("synthesized_netlist_implemented_opcode_sequences",
        [sys.executable, "-m", "unittest", "sim.test_packet_frontend_rtl_differential", "-v"],
        receipt, env=netlist_env)

    # Complete wrapper observables, arbitrary post-reset inputs.  The base case
    # is bounded; temporal induction is attempted and its exact outcome retained.
    miter = cache / "whole_design_miter.sv"
    miter.write_text("""module whole_design_miter(input clk, input [7:0] ui_in,
 input [7:0] uio_in, input ena, input rst_n);
 wire [7:0] r_uo,r_uio,r_oe,n_uo,n_uio,n_oe;
 lean_silicon_lsc1 rtl(ui_in,r_uo,uio_in,r_uio,r_oe,ena,clk,rst_n);
 lean_silicon_lsc1_netlist net(ui_in,n_uo,uio_in,n_uio,n_oe,ena,clk,rst_n);
 reg past_valid = 1'b0;
 always @(posedge clk) begin
   past_valid <= 1'b1;
   if (!past_valid) assume(!rst_n);
   if (past_valid) begin
     assert(r_uo == n_uo); assert(r_uio == n_uio); assert(r_oe == n_oe);
   end
 end
endmodule
""")
    eq_read = (f"read_verilog -formal -sv {rtl_args} {netlist} {miter}; "
               "prep -flatten -top whole_design_miter; async2sync; chformal -lower; ")
    run("whole_design_bmc_3", bounded_sat_argv(eq_read), receipt)
    receipt["proofs"]["whole_design_bmc"] = {"status": "pass",
        "edges": BOUNDED_EDGES,
        "observables": plan["observables"], "post_reset_inputs": "unconstrained"}
    induction_argv = ["yosys", "-Q", "-p", eq_read +
        "sat -verify -prove-asserts -set-assumes -tempinduct -seq 4 -maxsteps 32 -set-def-inputs"]
    try:
        induction = subprocess.run(induction_argv, cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        induction_rc = induction.returncode
        induction_timed_out = False
        induction_blocker = None if induction_rc == 0 else induction.stdout[-4000:]
    except subprocess.TimeoutExpired as error:
        induction_rc = 124
        induction_timed_out = True
        captured = error.stdout or b""
        tail = (captured.decode(errors="replace") if isinstance(captured, bytes)
                else captured)[-4000:]
        induction_blocker = "15-second HOST limit expired during whole-design induction attempt\n" + tail
    induction_status = classify_induction(
        "whole_design_temporal_induction_attempt", induction_rc,
        induction_blocker or "", timed_out=induction_timed_out)
    receipt["commands"].append({"name": "whole_design_temporal_induction_attempt",
        "argv": induction_argv, "exit_code": induction_rc})
    receipt["proofs"]["whole_design_induction"] = {
        "status": induction_status,
        "method": "temporal induction", "maxsteps": 32,
        "blocker": induction_blocker}
    receipt["proofs"]["whole_design_equivalence_boundary"] = {
        "classification": ("unbounded-pass" if induction_status == "pass"
                           else "bounded-pass-unbounded-blocked"),
        "mandatory_bounded_edges": BOUNDED_EDGES,
        "unbounded_method": "temporal induction",
        "unbounded_blocker": induction_blocker,
        "soundness_rule": ("only a successful induction command may classify the "
                           "whole design as unbounded")}

    inv_read = (f"read_verilog -formal -D FORMAL_FULL_LSC1 -sv {rtl_args} "
                "formal/full_lsc1_controller_invariants.sv; "
                "prep -flatten -top lean_silicon_lsc1; async2sync; "
                "chformal -cover -remove; chformal -lower; ")
    run("controller_invariants_bmc_3", bounded_sat_argv(inv_read), receipt)
    controller_argv = ["yosys", "-Q", "-p", inv_read +
        "sat -verify -prove-asserts -set-assumes -tempinduct -seq 4 -maxsteps 64 -set-def-inputs"]
    try:
        controller = subprocess.run(controller_argv, cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        controller_rc = controller.returncode
        controller_timed_out = False
        controller_blocker = None if controller_rc == 0 else controller.stdout[-4000:]
    except subprocess.TimeoutExpired as error:
        controller_rc = 124
        controller_timed_out = True
        captured = error.stdout or b""
        tail = (captured.decode(errors="replace") if isinstance(captured, bytes)
                else captured)[-4000:]
        controller_blocker = "15-second HOST limit expired during controller induction attempt\n" + tail
    controller_status = classify_induction(
        "controller_invariants_induction_attempt", controller_rc,
        controller_blocker or "", timed_out=controller_timed_out)
    receipt["commands"].append({"name": "controller_invariants_induction_attempt",
        "argv": controller_argv, "exit_code": controller_rc})
    receipt["proofs"]["controller_invariants"] = {
        "status": ("pass" if controller_status == "pass"
                   else "bounded-pass-unbounded-blocked"),
        "bounded_edges": BOUNDED_EDGES, "method": "temporal induction",
        "blocker": controller_blocker}
    run("opcode_reset_backpressure_fault_nonvacuity",
        ["make", "-C", "test/packet_frontend", "sim"], receipt)
    run("all_opcode_model_rtl_sequences", [sys.executable, "-m", "unittest",
        "sim.test_packet_frontend_rtl_differential", "-v"], receipt,
        env=canonical_rtl_env())
    receipt["covers"]["cycle_sequences"] = {
        "status": "witnessed",
        "scope": ("all implemented opcodes, including valid NEGOTIATE and a staged "
                  "instruction followed by valid RETIRE, plus reset, abort, "
                  "backpressure and faults")}

    mutated_miter = cache / "whole_design_miter.mutated.sv"
    original_miter = miter.read_text()
    changed = original_miter.replace("assert(r_uo == n_uo);",
                                      "assert(r_uo == (n_uo ^ 8'h01));", 1)
    if changed == original_miter:
        raise SystemExit("failed to apply observable correspondence mutation")
    mutated_miter.write_text(changed)
    mutation_read = (f"read_verilog -formal -sv {rtl_args} {netlist} {mutated_miter}; "
                     "prep -flatten -top whole_design_miter; async2sync; chformal -lower; ")
    mutation_argv = ["yosys", "-Q", "-p", mutation_read +
        "sat -verify -prove-asserts -set-assumes -seq 3 -set-def-inputs"]
    mutation = subprocess.run(mutation_argv,
        cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    receipt["commands"].append({"name": "observable_correspondence_mutation",
        "argv": mutation_argv, "exit_code": mutation.returncode})
    killed = mutation.returncode != 0 and "proof did fail" in mutation.stdout.lower()
    receipt["mutations"].append({"name": "invert RTL uo_out bit zero in correspondence property",
                                 "killed": killed})
    if not killed:
        sys.stderr.write(mutation.stdout)
        raise SystemExit("observable correspondence mutation was not killed")

    receipt["status"] = "pass"
    receipt_path = cache / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    checksums = cache / "SHA256SUMS"
    checksums.write_text("".join(f"{sha256(path)}  {path.name}\n" for path in
                                 (netlist, miter, mutated_miter, receipt_path)))
    print(json.dumps({"status": "pass", "receipt": str(receipt_path),
                      "netlist_sha256": sha256(netlist)}, sort_keys=True))


if __name__ == "__main__":
    main()
