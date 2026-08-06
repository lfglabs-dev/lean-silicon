#!/usr/bin/env python3
"""Deterministic tests for the release workflow's exact-head GDS selector."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "tools" / "select_exact_gds_run.sh"
HEAD = "a" * 40
WRONG_HEAD = "b" * 40


def run(status, conclusion="", head=HEAD, run_id=101):
    return {
        "databaseId": run_id,
        "headSha": head,
        "url": f"https://example.invalid/runs/{run_id}",
        "status": status,
        "conclusion": conclusion,
        "createdAt": f"2026-08-04T12:{run_id % 60:02d}:00Z",
    }


class ExactGdsSelectorTest(unittest.TestCase):
    def invoke(self, responses, max_polls=None):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            response_path = temp_path / "responses.json"
            response_path.write_text(json.dumps(responses))
            fake_gh = temp_path / "gh"
            fake_gh.write_text(
                """#!/usr/bin/env python3
import json, os
from pathlib import Path
responses = json.loads(Path(os.environ['FAKE_GH_RESPONSES']).read_text())
state = Path(os.environ['FAKE_GH_STATE'])
index = int(state.read_text()) if state.exists() else 0
state.write_text(str(index + 1))
print(json.dumps(responses[min(index, len(responses) - 1)]))
"""
            )
            fake_gh.chmod(0o755)
            output = temp_path / "selected.json"
            env = os.environ | {
                "PATH": f"{temp_path}:{os.environ['PATH']}",
                "FAKE_GH_RESPONSES": str(response_path),
                "FAKE_GH_STATE": str(temp_path / "state"),
                "GDS_POLL_INTERVAL_SECONDS": "0",
                "GDS_MAX_POLLS": str(max_polls or len(responses)),
            }
            result = subprocess.run(
                ["bash", str(SELECTOR), HEAD, str(output)],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            selected = json.loads(output.read_text()) if output.exists() else None
            return result, selected

    def test_success_selects_exact_head(self):
        result, selected = self.invoke([[run("completed", "success")]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(selected["headSha"], HEAD)

    def test_pending_same_head_waits_then_succeeds(self):
        result, selected = self.invoke(
            [[run("in_progress")], [run("completed", "success")]]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("waiting for exact-head GDS run", result.stderr)
        self.assertEqual(selected["databaseId"], 101)

    def test_wrong_head_is_rejected(self):
        result, selected = self.invoke([[run("completed", "success", WRONG_HEAD)]])
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(selected)
        self.assertIn("timed out", result.stderr)

    def test_terminal_red_is_rejected_immediately(self):
        result, selected = self.invoke([[run("completed", "failure")]], max_polls=3)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(selected)
        self.assertIn("completed with conclusion 'failure'", result.stderr)
        self.assertNotIn("timed out", result.stderr)

    def test_missing_exact_head_has_bounded_timeout(self):
        result, selected = self.invoke([[]], max_polls=3)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(selected)
        self.assertIn("timed out after 3 polls", result.stderr)


if __name__ == "__main__":
    unittest.main()
