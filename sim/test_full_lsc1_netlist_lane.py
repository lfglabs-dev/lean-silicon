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
            before = stat.S_IMODE(cache.stat().st_mode)
            with self.assertRaisesRegex(SystemExit, "deny group/other"):
                full_lsc1_netlist.prepare_private_cache(cache)
            self.assertEqual(stat.S_IMODE(cache.stat().st_mode), before)

    def test_absent_cache_is_created_private(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            cache = Path(parent) / "new" / "cache"
            full_lsc1_netlist.prepare_private_cache(cache)
            self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o700)

    def test_canonical_rtl_environment_removes_override(self) -> None:
        with mock.patch.dict(os.environ, {"LSC1_RTL_DIR": "/substituted"}):
            env = full_lsc1_netlist.canonical_rtl_env(LSC1_SYNTH_NETLIST="net.v")
        self.assertNotIn("LSC1_RTL_DIR", env)
        self.assertEqual(env["LSC1_SYNTH_NETLIST"], "net.v")

    def test_mandatory_bound_includes_operational_post_reset_state(self) -> None:
        self.assertGreaterEqual(full_lsc1_netlist.BOUNDED_EDGES, 3)
        argv = full_lsc1_netlist.bounded_sat_argv("read-design; ")
        self.assertIn(f"-seq {full_lsc1_netlist.BOUNDED_EDGES}", argv[-1])
        self.assertIn("-set-assumes", argv[-1])
        self.assertIn("-set-def-inputs", argv[-1])


if __name__ == "__main__":
    unittest.main()
