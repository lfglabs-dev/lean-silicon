#!/usr/bin/env python3
"""Dependency-free executable oracle for frozen scalar micro-semantics.

Hex integers denote polynomial-basis field words; serialized bytes are little
endian. This is intentionally a single-step/reference oracle, not an RTL
controller or a full upstream Rust runner.
"""
import json
import pathlib
import sys

MASK = (1 << 128) - 1
REDUCTION = 0x87

class Fault(Exception):
    pass

def word(s): return int(s, 16) if isinstance(s, str) else s
def xtime(a): return ((a << 1) & MASK) ^ (REDUCTION if a >> 127 else 0)
def mul(a, b):
    out = 0
    while b:
        if b & 1: out ^= a
        a = xtime(a); b >>= 1
    return out
def inv(a):
    if a == 0: return 0
    # a^(2^128-2), matching the library's zero convention too.
    out, base, exponent = 1, a, (1 << 128) - 2
    while exponent:
        if exponent & 1: out = mul(out, base)
        base = mul(base, base); exponent >>= 1
    return out
def encode(i):
    out = 1
    for _ in range(i): out = xtime(out)
    return out
def reverse(v, limit=1 << 16):
    p = 1
    for i in range(limit):
        if p == v: return i
        p = xtime(p)
    raise Fault("invalid_g_power")
def checked_add(a, b):
    z = a + b
    if z > 0xffffffff: raise Fault("u32_overflow")
    return z
def expected(v):
    value = v.get("expect", v.get("expect_index"))
    if isinstance(value, str) and value.startswith("0x"): return word(value)
    if isinstance(value, list): return [word(x) if isinstance(x, str) and x.startswith("0x") else x for x in value]
    return value

def execute(v):
    op = v["op"]
    if op == "xor": return word(v["a"]) ^ word(v["b"])
    if op == "xor_backsolve": return word(v["known"]) ^ word(v["result"])
    if op == "mul": return mul(word(v["a"]), word(v["b"]))
    if op == "mul_backsolve":
        known = word(v["known"])
        if known == 0: raise Fault("mul_backsolve_zero_divisor")
        return mul(word(v["result"]), inv(known))
    if op == "inv": return inv(word(v["a"]))
    if op == "write_once":
        old, new = v["initial"], word(v["value"])
        if old is not None and word(old) != new: raise Fault("write_conflict")
        return "written"
    if op == "deref_cell":
        l = None if v["left"] is None else word(v["left"])
        r = None if v["right"] is None else word(v["right"])
        if l is not None and r is not None and l != r: raise Fault("deref_mismatch")
        if l is None and r is None: return "deferred_then_zero"
        return [l if l is not None else r, r if r is not None else l]
    if op == "deref_pc": return checked_add(v["pc"], 2)
    if op == "deref_fp": return v["fp"]
    if op == "reverse": return reverse(word(v["value"]))
    if op == "jump":
        if word(v["c"]) == 0: return [checked_add(v["pc"], 1), v["fp"]]
        try:
            d = v["d_index"] if "d_index" in v else reverse(word(v["d"]))
            f = v["f_index"] if "f_index" in v else reverse(word(v["f"]))
            return [d, f]
        except Fault: raise Fault("invalid_jump_target")
    if op == "blake3": raise Fault("external_blake3_required")
    if op == "checked_add": return checked_add(v["a"], v["b"])
    if op == "halt":
        if v["pc"] != v["sentinel"] or v["fp"] != 0: raise Fault("bad_halt_state")
        return "halt"
    raise AssertionError(op)

def main():
    source = pathlib.Path(__file__).with_name("vectors.json")
    vectors = json.loads(source.read_text())["vectors"]
    failures = []
    for v in vectors:
        try:
            got = execute(v)
            want = expected(v)
            if "fault" in v or got != want: failures.append((v["id"], got, v.get("fault", want)))
        except Fault as err:
            if str(err) != v.get("fault"): failures.append((v["id"], str(err), v.get("fault")))
    if failures:
        for f in failures: print("FAIL", *f)
        raise SystemExit(1)
    print(f"ok: {len(vectors)} frozen scalar vectors")

if __name__ == "__main__": main()
