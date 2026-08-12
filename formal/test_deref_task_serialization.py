import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from formal import run_deref_bridge_tasks as runner


EXPECTED_TASKS = [
    "safety",
    "reachability",
    "accepted_result_reachability",
    "matching_retire_reachability",
    "accepted_result_safety",
    "matching_retire_safety",
    "post_retire_safety",
]


class DerefTaskSerializationTest(unittest.TestCase):
    def test_discovers_every_declared_task(self):
        self.assertEqual(runner.tasks(), EXPECTED_TASKS)

    @mock.patch.object(runner, "run_bounded")
    def test_runs_one_explicit_task_at_a_time_in_declaration_order(self, run):
        run.return_value = subprocess.CompletedProcess(["sby"], 0, "", None)
        runner.main()
        self.assertEqual(
            run.call_args_list,
            [
                mock.call(
                    ["sby", "-f", runner.SBY.name, task],
                    cwd=runner.HERE,
                    timeout=runner.TASK_TIMEOUT_SECONDS,
                )
                for task in EXPECTED_TASKS
            ],
        )

    @mock.patch.object(runner, "run_bounded")
    def test_stops_before_later_tasks_after_failure(self, run):
        run.return_value = subprocess.CompletedProcess(["sby"], 1, "failed\n", None)
        with self.assertRaises(subprocess.CalledProcessError):
            runner.main()
        self.assertEqual(run.call_count, 1)

    def test_rejects_an_empty_task_section(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "empty.sby"
            config.write_text("[tasks]\n\n[options]\nmode bmc\n")
            with self.assertRaisesRegex(RuntimeError, "no tasks found"):
                runner.tasks(config)


if __name__ == "__main__":
    unittest.main()
