#!/usr/bin/env python3
"""Regress the fail-closed, shared OSS CAD Suite acquisition path."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
ACTION = ROOT / ".github" / "actions" / "setup-oss-cad-suite" / "action.yml"


class OssCadSuiteWorkflowTest(unittest.TestCase):
    def test_every_formal_lane_uses_the_verified_local_action(self):
        workflow = WORKFLOW.read_text()
        self.assertNotIn("YosysHQ/setup-oss-cad-suite", workflow)
        self.assertEqual(
            workflow.count("uses: ./.github/actions/setup-oss-cad-suite"), 7
        )

        for job in (
            "formal-and-lint",
            "deref-lifecycle",
            "deref-lifecycle-mutations",
            "jump-lifecycle",
            "jump-lifecycle-mutations",
            "full-lsc1-netlist",
        ):
            with self.subTest(job=job):
                start = workflow.index(f"  {job}:\n")
                header = workflow[start : workflow.index("    steps:\n", start)]
                self.assertIn("needs: formal-toolchain", header)

    def test_acquisition_is_bounded_and_integrity_checked(self):
        action = ACTION.read_text()
        for required in (
            "--connect-timeout 30",
            "--max-time 900",
            "--retry 4",
            "--retry-all-errors",
            "--retry-max-time 1800",
            "EXPECTED_BYTES",
            "EXPECTED_SHA256",
            "sha256sum --check --status",
            "tar -xzf",
            'test -x "$SUITE_DIR/bin/yosys"',
            'test -x "$SUITE_DIR/bin/sby"',
        ):
            with self.subTest(required=required):
                self.assertIn(required, action)


if __name__ == "__main__":
    unittest.main()
