"""Family regressions for provenance-sensitive full-netlist lane behavior."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import full_lsc1_netlist


class FullLsc1NetlistLaneTests(unittest.TestCase):
    def test_existing_public_cache_is_rejected_without_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            cache = Path(parent) / "shared"
            cache.mkdir(mode=0o755)
            cache.chmod(0o755)
            before = stat.S_IMODE(cache.stat().st_mode)
            with self.assertRaisesRegex(SystemExit, "deny group/other"):
                full_lsc1_netlist.prepare_private_cache(cache)
            self.assertEqual(stat.S_IMODE(cache.stat().st_mode), before)

    def test_absent_cache_is_created_private(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            cache = Path(parent) / "new" / "cache"
            full_lsc1_netlist.prepare_private_cache(cache)
            self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o700)

    def test_canonical_rtl_environment_removes_overrides(self) -> None:
        with mock.patch.dict(os.environ, {
                "LSC1_RTL_DIR": "/substituted",
                "LSC1_SYNTH_NETLIST": "/substituted.v",
        }):
            env = full_lsc1_netlist.canonical_rtl_env(LSC1_SYNTH_NETLIST="net.v")
        self.assertNotIn("LSC1_RTL_DIR", env)
        self.assertEqual(env["LSC1_SYNTH_NETLIST"], "net.v")

        with mock.patch.dict(os.environ, {
                "LSC1_RTL_DIR": "/substituted",
                "LSC1_SYNTH_NETLIST": "/substituted.v",
        }):
            baseline = full_lsc1_netlist.canonical_rtl_env()
        self.assertNotIn("LSC1_RTL_DIR", baseline)
        self.assertNotIn("LSC1_SYNTH_NETLIST", baseline)

    def test_induction_counterexamples_fail_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "found a counterexample"):
            full_lsc1_netlist.classify_induction(
                "whole-design", 1, "ERROR: proof did fail")
        self.assertEqual(full_lsc1_netlist.classify_induction(
            "whole-design", 124, "HOST timeout without a proof result",
            timed_out=True), "blocked")

    def test_induction_tool_errors_fail_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "tool failure"):
            full_lsc1_netlist.classify_induction(
                "whole-design", 1, "ERROR: parser failed before proof")
        with self.assertRaisesRegex(SystemExit, "tool failure"):
            full_lsc1_netlist.classify_induction(
                "whole-design", 124, "launcher reserved exit code")
        self.assertEqual(full_lsc1_netlist.classify_induction(
            "whole-design", 1, "Reached maximum number of time steps"), "blocked")

    def test_mandatory_bound_includes_operational_post_reset_state(self) -> None:
        self.assertGreaterEqual(full_lsc1_netlist.BOUNDED_EDGES, 3)
        argv = full_lsc1_netlist.bounded_sat_argv("read-design; ")
        self.assertIn(f"-seq {full_lsc1_netlist.BOUNDED_EDGES}", argv[-1])
        self.assertIn("-set-assumes", argv[-1])
        self.assertIn("-set-def-inputs", argv[-1])


if __name__ == "__main__":
    unittest.main()
