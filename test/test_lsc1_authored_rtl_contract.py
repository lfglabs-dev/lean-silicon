"""Cross-check the full-profile Lean/RTL observable contract."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuthoredRtlContractTests(unittest.TestCase):
    def test_lean_and_authored_rtl_share_the_checked_observations(self) -> None:
        completed = subprocess.run(
            [sys.executable, "tools/lsc1_authored_rtl_contract.py", "--verify"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("LSC1_AUTHORED_RTL_CONTRACT_PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
