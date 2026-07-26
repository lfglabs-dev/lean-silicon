#!/bin/sh
# Reproducible ULX3S v3.1.8 smoke build.
# Requires: yosys, nextpnr-ecp5, ecppack from OSS CAD Suite (no -f ever).
set -eu

# Resolve the repository root from this script's location. The build products
# are archived into the committed results directory, so a wrong number of ".."
# silently scatters evidence outside the repository instead of failing.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
cd "$HERE"

TOP=smoke_top
LPF=ulx3s_v318_smoke.lpf
OUTDIR="$ROOT/results/ulx3s-smoke-uart-20260725"
mkdir -p "$OUTDIR"
# Both FPGA flows publish into OUTDIR. Keep the lock outside that directory so
# its inode remains stable while OUTDIR itself is atomically exchanged.
LOCK="$ROOT/results/.ulx3s-smoke-uart.publish.lock"
exec 9>"$LOCK"
flock 9
STAGE=$(mktemp -d "$(dirname "$OUTDIR")/.smoke-build.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
cp -a "$OUTDIR/." "$STAGE/"

# Names the artifacts are archived and checksummed under. They must match the
# files committed under results/, otherwise `sha256sum -c` names a file that
# does not exist and the manifest cannot be verified.
BIT_NAME=ulx3s_smoke.bit
CFG_NAME=smoke.config
SVF_NAME=smoke.svf

OSS_CAD_BIN=${OSS_CAD_BIN:-/root/oss/bin}
if [ -d "$OSS_CAD_BIN" ]; then
    PATH="$OSS_CAD_BIN:$PATH"
    export PATH
fi

{
    echo "=== TOOL VERSIONS ==="
    yosys -V
    nextpnr-ecp5 --version
    ecppack --version
    echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$STAGE/tool_versions.txt" 2>&1
cat "$STAGE/tool_versions.txt"

echo "=== SYNTH ==="
yosys -p "read_verilog -sv ${TOP}.sv; hierarchy -check -top ${TOP}; proc; check; synth_ecp5 -top ${TOP}; write_json ${TOP}.json" \
    > "$STAGE/yosys.log" 2>&1 || {
    status=$?
    cat "$STAGE/yosys.log"
    exit "$status"
}
cat "$STAGE/yosys.log"

echo "=== PLACE+ROUTE (25 MHz, no --timing-allow-fail) ==="
nextpnr-ecp5 --85k --package CABGA381 --json ${TOP}.json --lpf ${LPF} --textcfg ${TOP}.config \
    > "$STAGE/nextpnr.log" 2>&1 || {
    status=$?
    cat "$STAGE/nextpnr.log"
    exit "$status"
}
cat "$STAGE/nextpnr.log"

echo "=== PACK ==="
ecppack --svf ${TOP}.svf ${TOP}.config ${TOP}.bit > "$STAGE/ecppack.log" 2>&1 || {
    status=$?
    cat "$STAGE/ecppack.log"
    exit "$status"
}
cat "$STAGE/ecppack.log"

cp "${TOP}.bit"    "$STAGE/$BIT_NAME"
cp "${TOP}.config" "$STAGE/$CFG_NAME"
cp "${TOP}.svf"    "$STAGE/$SVF_NAME"

# Digest the archived copies from inside OUTDIR so the manifest holds bare
# file names that resolve when checked from that directory.
( cd "$STAGE" && sha256sum "$BIT_NAME" "$CFG_NAME" "$SVF_NAME" > SHA256SUMS )
( cd "$STAGE" && sha256sum -c SHA256SUMS )

# Capture timing line for report
grep -E 'Max frequency|Slack' "$STAGE/nextpnr.log" | tail -5 > "$STAGE/timing.txt" || true

# The stage is a complete archive snapshot. Exchange the whole directory in
# one same-filesystem operation so failure or interruption cannot expose a
# mixture of old artifacts and new checksums.
python3 "$ROOT/tools/atomic_publish.py" "$STAGE" "$OUTDIR"
cat "$OUTDIR/timing.txt"

echo "=== BUILD COMPLETE ==="
ls -l "$OUTDIR/$BIT_NAME"
echo "bitstream: $OUTDIR/$BIT_NAME"
echo "sha256: $(sha256sum "$OUTDIR/$BIT_NAME" | cut -d' ' -f1)"
