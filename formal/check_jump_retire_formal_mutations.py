#!/usr/bin/env python3
"""Run the critical lifecycle mutations against the exact JUMP witness."""

try:
    from formal import check_deref_retire_formal_mutations as checks
except ModuleNotFoundError:
    import check_deref_retire_formal_mutations as checks

checks.SBY_NAME = "full_lsc1_jump_bridge.sby"
checks.TEMP_PREFIX = "jump"

if __name__ == "__main__":
    raise SystemExit(checks.main())
