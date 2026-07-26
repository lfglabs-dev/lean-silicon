#!/usr/bin/env python3
"""Record the source revision and per-file digests a build's inputs came from.

An evidence archive that names a revision not containing its own build inputs
cannot be reproduced or audited: the reader cannot tell which sources produced
the bitstream. Naming the revision alone is also not enough, because a build run
from a modified worktree does not match any revision. Both are therefore
recorded, and the dirty flag is computed over the build inputs rather than the
whole tree -- a build writes its own products into results/, so a whole-tree
comparison would report "dirty" on every successful run and mean nothing.

When the revision cannot be determined at all -- an exported tarball, or no git
on PATH -- there is nothing to compare against, so the match is reported as
"unknown" rather than "yes". Claiming the inputs agree with a revision that was
never identified is a stronger statement than the evidence supports.

Usage: source_provenance.py <output-file> <source>...
"""
from hashlib import sha256
from pathlib import Path
from subprocess import DEVNULL, CalledProcessError, check_output
import sys

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return check_output(["git", *args], cwd=ROOT, stderr=DEVNULL).decode().strip()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: source_provenance.py <output-file> <source>...")
    out, sources = Path(argv[0]), argv[1:]

    try:
        revision = _git("rev-parse", "HEAD")
    except (CalledProcessError, FileNotFoundError):
        revision = "unknown"

    lines = ["=== SOURCE PROVENANCE ==="]
    digests = []
    dirty = False
    for src in sorted(sources):
        # Resolved against the caller's directory: the build scripts run from
        # fpga/ulx3s and name their inputs relative to it.
        path = Path(src).resolve()
        rel = path.relative_to(ROOT).as_posix()
        digest = sha256(path.read_bytes()).hexdigest()
        digests.append(f"{digest}  {rel}")
        if revision != "unknown":
            try:
                committed = _git("rev-parse", f"HEAD:{rel}")
                dirty |= committed != _git("hash-object", str(path))
            except CalledProcessError:
                dirty = True  # not present at HEAD at all

    lines.append(f"revision: {revision}")
    if revision == "unknown":
        matched = "unknown"  # nothing was compared, so "yes" would be unearned
    else:
        matched = "no" if dirty else "yes"
    lines.append(f"inputs-match-revision: {matched}")
    lines.extend(digests)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
