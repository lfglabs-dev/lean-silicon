import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class HostAuthoredRTLBoundaryTests(unittest.TestCase):
    def test_real_model_lean_and_authored_rtl_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = pathlib.Path(directory) / "receipt.json"
            done = subprocess.run(
                [sys.executable, "tools/lsc1_host_authored_rtl_boundary.py", "--verify",
                 "--receipt", str(receipt)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn("LSC1_HOST_AUTHORED_RTL_BOUNDARY_PASS", done.stdout)
            self.assertTrue(receipt.is_file())


if __name__ == "__main__":
    unittest.main()
