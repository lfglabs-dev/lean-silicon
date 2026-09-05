#!/usr/bin/env python3
"""Regress the deterministic, diagnosable ULX3S packet build recipe."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "fpga" / "ulx3s" / "build_packet_uart.sh"


class Ulx3sPacketBuildRecipeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.recipe = RECIPE.read_text()

    def test_lock_reexec_uses_canonical_script_path(self) -> None:
        self.assertIn('SCRIPT="$HERE/$(basename -- "$0")"', self.recipe)
        self.assertIn('lock "$LOCK" -- "$SCRIPT" "$@"', self.recipe)

    def test_route_is_deterministic_and_uses_router2(self) -> None:
        self.assertIn('--seed 1 --router router2', self.recipe)
        self.assertNotIn('--timing-allow-fail', self.recipe)

    def test_nextpnr_failure_log_is_emitted(self) -> None:
        self.assertIn('cat "$STAGE/nextpnr.log" >&2', self.recipe)
        self.assertIn('exit "$status"', self.recipe)


if __name__ == "__main__":
    unittest.main()
