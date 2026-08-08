#!/usr/bin/env python3
"""Compare the host/LSC-1 loop against the official Rust runner.

The leanSilicon side is fully observable: this tool records pc, fp, opcode,
effective addresses, input cell presence and values, writes, branch proposal,
deferred equalities, faults and final state for every transition.

The upstream side is not.  At the frozen commit ``Execution::trace`` is
``pub(crate)``, so ``Program::execute`` exposes only the final memory image,
the cycle count and ``mem_used``.  Equivalence is therefore claimed only for
the fields both sides actually produce, and the rest of the schema is emitted
with an explicit reason for being unverified.
"""
import argparse
import datetime
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from host import lean_compiler_adapter  # noqa: E402
from host.memory import HostMemory  # noqa: E402
from host.runtime import HostRuntime  # noqa: E402

EXPORT_SOURCE = ROOT / "tools" / "lean_compiler_export.py"
_export = types.ModuleType("_tracked_lean_compiler_export")
_export.__file__ = str(EXPORT_SOURCE)
sys.modules[_export.__name__] = _export
try:
    exec(compile(EXPORT_SOURCE.read_bytes(), str(EXPORT_SOURCE), "exec"), _export.__dict__)
finally:
    del sys.modules[_export.__name__]

SCHEMA = "leansilicon.host.comparison/1"

NOT_OBSERVABLE_UPSTREAM = {
    "per_step.pc": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.fp": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.opcode": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.addresses": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.inputs": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.writes": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.branch": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.deferred": "Execution::trace is pub(crate) at the frozen commit",
    "per_step.fault": "Program::execute panics rather than returning a fault code",
}


def upstream_execution(artifact_path: pathlib.Path, artifact: dict, upstream, toolchain: str):
    """Recorded upstream output, or a live re-run that must reproduce it.

    In live mode, the fresh probe execution block (mem prefix, mem_used, cycles,
    and relevant fields) is compared against the recorded upstream_execution and
    a mismatch refuses stale or tampered evidence. Claims are kept scoped.
    """
    recorded = artifact["upstream_execution"]
    if upstream is None:
        return recorded, "recorded_artifact", None
    _export.candidate_head()
    _export.require_checkout(upstream)
    probe, command = _export.run_probe(upstream, artifact["source"]["text"], toolchain)
    if probe["bytecode"] != artifact["program"]["bytecode"]:
        raise SystemExit(
            f"live compile of {artifact_path} does not reproduce the recorded bytecode"
        )
    entry_mismatches = [
        field for field in ("pc0", "fp0")
        if probe[field] != artifact["program"][field]
    ]
    if entry_mismatches:
        raise SystemExit(
            f"live compile of {artifact_path} does not reproduce recorded entry "
            f"metadata: {', '.join(entry_mismatches)}"
        )
    live_exec = probe["execution"]
    # Compare fresh probe against recorded to refuse stale/tampered evidence
    mismatches = []
    if live_exec.get("cycles") != recorded.get("cycles"):
        mismatches.append({"field": "cycles", "live": live_exec.get("cycles"), "recorded": recorded.get("cycles")})
    if live_exec.get("mem_used") != recorded.get("mem_used"):
        mismatches.append({"field": "mem_used", "live": live_exec.get("mem_used"), "recorded": recorded.get("mem_used")})
    if live_exec.get("mem_len") != recorded.get("mem_len"):
        mismatches.append({"field": "mem_len", "live": live_exec.get("mem_len"), "recorded": recorded.get("mem_len")})
    live_mem = live_exec.get("mem", [])
    rec_mem = recorded.get("mem", [])
    if live_mem != rec_mem:
        mismatches.append({"field": "mem", "reason": "live mem prefix differs from recorded"})
    if mismatches:
        raise SystemExit(
            "live probe execution does not match recorded upstream_execution: "
            + json.dumps(mismatches)
        )
    live = {
        "public_input": recorded.get("public_input"),
        "cycles": live_exec["cycles"],
        "mem_used": live_exec["mem_used"],
        "mem_len": live_exec["mem_len"],
        "mem": live_exec["mem"],
    }
    return live, "live_cargo_run", command


def compare(runtime: HostRuntime, run, upstream: dict) -> dict:
    """Compare every memory cell the host actually decided a value for.

    Memory is write-once on both sides, so a cell the host wrote can never be
    given a different value by a later upstream instruction.  Cells the host
    never reached are not compared.

    ``upstream["mem"]`` holds the ``mem_used`` prefix that upstream actually
    touched; the rest of its power-of-two buffer is untouched zero.  A host
    write at or past that prefix is a divergence, not a gap in the record.

    Unwritten cells are zero on both sides.  For a halted run, an absent host
    cell below ``mem_used`` is therefore only a mismatch when upstream records
    a nonzero value there.  When not halted, coverage gaps are recorded
    explicitly in not_compared and MATCH is never returned for skipped work.
    """
    mem = [int(value, 16) for value in upstream["mem"]]
    addresses = sorted(runtime.memory.cells)
    mismatches = []
    for address in addresses:
        host_value = runtime.memory.cells[address]
        if address >= upstream["mem_used"]:
            mismatches.append({
                "address": address,
                "host": f"{host_value:#034x}",
                "reason": f"upstream never touched this cell (mem_used={upstream['mem_used']})",
            })
        elif mem[address] != host_value:
            mismatches.append({
                "address": address,
                "host": f"{host_value:#034x}",
                "upstream": f"{mem[address]:#034x}",
            })

    cycles_comparable = run.terminal == "halted"
    if run.terminal not in ("halted", "unsupported"):
        mismatches.append({
            "field": "terminal",
            "host": run.terminal,
            "reason": run.reason,
        })
    if cycles_comparable and runtime.step_index != upstream["cycles"]:
        mismatches.append({
            "field": "cycles",
            "host": runtime.step_index,
            "upstream": upstream["cycles"],
        })

    not_compared = dict(NOT_OBSERVABLE_UPSTREAM)
    if not cycles_comparable:
        not_compared["cycles"] = (
            f"the host run ended as {run.terminal!r} ({run.reason}), so its step "
            f"count covers a prefix of the upstream run"
        )

    # A sparse halted memory image is valid: an absent host cell denotes zero.
    # A non-halted run still needs full coverage to claim any final-memory
    # result, even if the unvisited cells happen to be zero.
    covered = set(runtime.memory.cells.keys())
    expected = set(range(upstream["mem_used"]))
    missing = sorted(expected - covered)
    if missing:
        if run.terminal == "halted":
            for address in (address for address in missing if mem[address] != 0):
                mismatches.append({
                    "address": address,
                    "host": f"{0:#034x}",
                    "upstream": f"{mem[address]:#034x}",
                    "reason": "host omitted a nonzero upstream cell",
                })
        else:
            not_compared["final_memory_gaps"] = [f"{a:#x}" for a in missing]
            # Explicitly refuse MATCH when work was skipped
            if not mismatches:
                mismatches.append({
                    "field": "coverage",
                    "reason": "host run did not cover all upstream cells; gaps recorded in not_compared",
                })

    if mismatches:
        result = "MISMATCH"
    elif run.terminal == "halted":
        result = "MATCH"
    else:
        # An explicitly unsupported suffix may have no additional memory cells,
        # but it was still skipped.  Preserve the useful prefix evidence without
        # ever presenting it as full-run equivalence.
        result = "PREFIX_MATCH"
        not_compared["unsupported_suffix"] = run.reason

    return {
        "result": result,
        "compared": {
            "final_memory_addresses": addresses,
            "cycles": cycles_comparable,
        },
        "mismatches": mismatches,
        "not_compared": not_compared,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=pathlib.Path)
    parser.add_argument("--upstream", type=pathlib.Path,
                        help="clean detached frozen checkout; re-runs the compiler live")
    parser.add_argument("--out", type=pathlib.Path, help="write the comparison JSON")
    parser.add_argument("--rust-toolchain", default="1.88.0")
    args = parser.parse_args()
    args.artifact = args.artifact.resolve()

    try:
        rel = str(args.artifact.relative_to(ROOT))
    except ValueError as e:
        raise SystemExit(f"artifact path must be inside the repo: {args.artifact}") from e

    artifact = json.loads(args.artifact.read_text())
    program = lean_compiler_adapter.load(args.artifact)
    upstream, source, command = upstream_execution(
        args.artifact, artifact, args.upstream, args.rust_toolchain
    )

    runtime = HostRuntime(program, memory=HostMemory.with_public_input(1, 0))
    run = runtime.run()
    comparison = compare(runtime, run, upstream)

    document = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "artifact": {
            "path": rel,
            "sha256": _export.sha256(args.artifact),
        },
        "upstream": {
            "repository": _export.REPOSITORY,
            "sha": _export.COMMIT,
            "execution_source": source,
            "command": command,
            "rust_toolchain": args.rust_toolchain if command else None,
            "cycles": upstream["cycles"],
            "mem_used": upstream["mem_used"],
            "mem_len": upstream["mem_len"],
        },
        "lean_silicon": {
            "profile": runtime.profile.name,
            "terminal": run.terminal,
            "reason": run.reason,
            "steps": [record.as_dict() for record in run.records],
            "final_state": runtime.final_state(upstream["mem_used"]),
        },
        "comparison": comparison,
    }
    if str(args.out) == "-":
        sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    elif args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(
        f"{comparison['result']} upstream={_export.COMMIT} source={source} "
        f"steps={len(run.records)} terminal={run.terminal} "
        f"cells={len(comparison['compared']['final_memory_addresses'])}",
        file=sys.stderr if str(args.out) == "-" else sys.stdout,
    )
    if comparison["result"] == "MISMATCH":
        raise SystemExit(json.dumps(comparison["mismatches"], indent=2))


if __name__ == "__main__":
    main()
