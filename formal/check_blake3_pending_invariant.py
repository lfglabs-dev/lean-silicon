#!/usr/bin/env python3
"""Prove and mutation-check the full-LSC1 aggregate result-pending binding."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "asic_core" / "rtl" / "lsc1_packet_frontend.sv"
INVARIANT = ROOT / "formal" / "full_lsc1_controller_invariants.sv"
UNION_BINDING = ".result_pending(result_pending || blake_result_pending)"


def harness(result_binding: str) -> str:
    return f"""
module blake3_pending_invariant_formal(input clk, output wire cover_condition);
  reg past_valid = 1'b0;
  reg rst_n = 1'b0;
  (* anyseq *) reg scalar_result_pending;
  (* anyseq *) reg blake_result_pending;
  wire aggregate_result_pending = {result_binding};
  assign cover_condition = past_valid && rst_n && blake_result_pending &&
                           !scalar_result_pending && aggregate_result_pending;
  always @(posedge clk) begin
    past_valid <= 1'b1;
    rst_n <= 1'b1;
    if (past_valid && rst_n) begin
      assert(aggregate_result_pending ==
             (scalar_result_pending || blake_result_pending));
      cover(cover_condition);
    end
  end
endmodule
"""


def run(source: Path, mode: str) -> subprocess.CompletedProcess[str]:
    sby_mode = "bmc" if mode == "prove" else "cover"
    config = source.with_suffix(".sby")
    config.write_text(f"""[options]
mode {sby_mode}
depth 3

[engines]
smtbmc boolector

[script]
read -formal -sv {source.name}
prep -top blake3_pending_invariant_formal

[files]
{source.name}
""")
    return subprocess.run(
        ["sby", "-f", config.name], cwd=source.parent, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def main() -> int:
    frontend = FRONTEND.read_text()
    if frontend.count(UNION_BINDING) != 1:
        print("production_union_binding=false")
        return 1
    if "if (blake_result_pending) assert(result_pending);" not in INVARIANT.read_text():
        print("blake_subset_invariant=false")
        return 1

    with tempfile.TemporaryDirectory(prefix="blake3-pending-invariant-") as raw:
        source = Path(raw) / "binding.sv"
        source.write_text(harness("scalar_result_pending || blake_result_pending"))
        baseline = run(source, "prove")
        coverage = run(source, "cover")
        source.write_text(harness("scalar_result_pending"))
        mutation = run(source, "prove")

    baseline_pass = baseline.returncode == 0
    cover_reached = coverage.returncode == 0
    mutation_killed = mutation.returncode != 0
    print(f"production_union_binding=true")
    print(f"baseline_proof={str(baseline_pass).lower()}")
    print(f"blake_only_pending_cover={str(cover_reached).lower()}")
    print(f"omit_blake_pending_mutation_killed={str(mutation_killed).lower()}")
    return 0 if baseline_pass and cover_reached and mutation_killed else 1


if __name__ == "__main__":
    raise SystemExit(main())
