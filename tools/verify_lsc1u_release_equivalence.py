#!/usr/bin/env python3
"""Verify the pinned v0.1.1 physical netlist from durable release evidence."""
import argparse, hashlib, json, pathlib, shutil, subprocess, zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT_ID = "9004116698"
ARCHIVE_SHA = "1c6721712d3dec19f0b143bd3af99e5e0982928a151d6142a25f5bf0dd1ef80f"
NETLIST_SHA = "97000459a97f1d775db06ed88fefb59e28fde09b27a5046aaadd036ad01e16bc"
SOURCE_SHA = "741a2073e0d341a15bb130b1d75295bbceb138df"
ARCHIVE_PATH = ROOT / "release" / "v0.1.1" / "evidence" / f"tt_submission-{ARTIFACT_ID}.zip"
RTL_HASHES = {
 "gf2n_mul_bitstream.sv":"d635c514ab20d9220708f0249c5307733027d7066f4f42476657d437db3e3cd7",
 "gf128_mul_bitstream.sv":"1f50cc6a666864a2e8daa107a0d28a780394a82dff2444d9674e9f02ebc5a5a2",
 "lsc1u_core.sv":"f1c653ffe7d84b594bd43950d639f523b38b086e89772f4dab7f1c33bfcd1fb0",
 "tt_um_lfglabs_lsc1u.sv":"595b51e8411023c614163030d621dcb906d9152108874655759d8a9a0e0cdc03",
}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def run(cmd, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, check=True, **kw)
def frozen_source(name):
    result = run(
        ["git", "show", f"{SOURCE_SHA}:src/{name}"],
        cwd=ROOT, stdout=subprocess.PIPE,
    )
    return result.stdout
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--cache-dir", required=True, type=pathlib.Path)
    a=ap.parse_args(); cache=a.cache_dir.resolve(); cache.mkdir(parents=True, exist_ok=True)
    if ROOT == cache or ROOT in cache.parents: raise SystemExit("cache must be outside the checkout")
    archive=ARCHIVE_PATH
    if sha(archive)!=ARCHIVE_SHA: raise SystemExit("artifact archive hash mismatch")
    stage=cache/"lsc1u-v0.1.1-equivalence"; shutil.rmtree(stage,ignore_errors=True); stage.mkdir()
    with zipfile.ZipFile(archive) as z:
        data=z.read("tt_submission/tt_um_lfglabs_lsc1u.v")
    net=stage/"selected_tt_um_lfglabs_lsc1u.v"; net.write_bytes(data)
    if sha(net)!=NETLIST_SHA: raise SystemExit("selected netlist hash mismatch")
    for name,want in RTL_HASHES.items():
        source=stage/name; source.write_bytes(frozen_source(name))
        if sha(source)!=want: raise SystemExit(f"frozen RTL identity mismatch: {SOURCE_SHA}:src/{name}")
    for name in ["sky130_fd_sc_hd_netlist_eq_cells.v","lsc1u_release_gate_wrapper.sv","lsc1u_release_netlist_eq_formal.sv","lsc1u_release_netlist_eq.sby"]: shutil.copy2(ROOT/"formal"/name,stage/name)
    text=(stage/"lsc1u_release_netlist_eq.sby").read_text().replace("../src/","")
    (stage/"lsc1u_release_netlist_eq.sby").write_text(text)
    run(["yosys","-V"]); print(f"source_commit={SOURCE_SHA}\narchive_sha256={ARCHIVE_SHA}\nnetlist_sha256={NETLIST_SHA}")
    witness=stage/"reset_release_witness.json"
    run(["yosys","-p",("read_verilog -sv gf2n_mul_bitstream.sv gf128_mul_bitstream.sv "
        "lsc1u_core.sv tt_um_lfglabs_lsc1u.sv; prep -flatten -top tt_um_lfglabs_lsc1u; "
        "sat -seq 3 -set-at 1 rst_n 0 -set-at 2 rst_n 1 -set-at 2 ena 1 "
        "-set-at 2 uio_oe 182 -show rst_n,ena,uio_oe "
        "-dump_json reset_release_witness.json")],cwd=stage)
    if not witness.is_file(): raise SystemExit("reset-release SAT witness is UNSAT or missing")
    try: json.loads(witness.read_text())
    except (json.JSONDecodeError, OSError) as exc: raise SystemExit("reset-release SAT witness is invalid") from exc
    run(["sby","-f","lsc1u_release_netlist_eq.sby","bounded"],cwd=stage)
    harness=stage/"lsc1u_release_netlist_eq_formal.sv"
    mutated=harness.read_text().replace("assert(rtl_uo == gate_uo);","assert(rtl_uo == (gate_uo ^ 8'h01));")
    if mutated==harness.read_text(): raise SystemExit("mutation was not applied")
    harness.write_text(mutated)
    result=subprocess.run(["sby","-f","lsc1u_release_netlist_eq.sby","bounded"],cwd=stage)
    status_path=stage/"lsc1u_release_netlist_eq_bounded"/"status"
    status=status_path.read_text().strip() if status_path.is_file() else "MISSING"
    status_kind=status.split(maxsplit=1)[0]
    if result.returncode==0 or status_kind!="FAIL":
        raise SystemExit(f"mutation did not produce a property failure (status={status}, rc={result.returncode})")
    print(f"PASS: pinned bounded equivalence, non-vacuity witness, and mutation counterexample (status={status})")
if __name__ == "__main__": main()
