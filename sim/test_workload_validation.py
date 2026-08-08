"""Regression tests for fresh workload-comparison receipts."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import workload_validation


class WorkloadValidationReceiptTest(unittest.TestCase):
    def test_validation_entrypoints_use_isolated_python(self):
        makefile = (workload_validation.ROOT / "Makefile").read_text()
        self.assertIn("$(PYTHON) -I tools/workload_validation.py", makefile)
        self.assertIn("$(PYTHON) -I tools/host_upstream_comparison.py", makefile)

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "json.py").write_text(
                "raise SystemExit('untracked shadow module imported')\n"
            )
            script = directory / "probe.py"
            script.write_text("import json\nprint(json.__name__)\n")
            completed = subprocess.run(
                [workload_validation.sys.executable, "-I", str(script)],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(completed.stdout.strip(), "json")

    def test_plan_paths_cannot_escape_or_use_untracked_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("tracked\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            self.assertEqual(
                workload_validation.resolve_tracked_path(repo, "tracked.txt"), tracked
            )

            (repo / "untracked.txt").write_text("untracked\n")
            with self.assertRaisesRegex(SystemExit, "not tracked"):
                workload_validation.resolve_tracked_path(repo, "untracked.txt")
            with self.assertRaisesRegex(SystemExit, "escapes its checkout"):
                workload_validation.resolve_tracked_path(repo, "../outside.txt")
            with self.assertRaisesRegex(SystemExit, "checkout-relative"):
                workload_validation.resolve_tracked_path(repo, "/tmp/outside.txt")

    def test_duplicate_workload_ids_are_rejected_before_comparison(self):
        plan = {"workloads": [{"id": "same"}, {"id": "same"}]}
        with self.assertRaisesRegex(SystemExit, "ids must be unique"):
            workload_validation.validate_unique_workload_ids(plan)

    def test_workload_ids_must_be_single_safe_filename_components(self):
        plan = {"workloads": [{"id": "suite/case"}]}
        with self.assertRaisesRegex(SystemExit, "safe filename components"):
            workload_validation.validate_unique_workload_ids(plan)

    def test_plan_must_contain_the_complete_required_workload_set(self):
        complete = {
            "workloads": [
                {"id": workload_id}
                for workload_id in workload_validation.REQUIRED_WORKLOAD_IDS
            ]
        }
        workload_validation.validate_unique_workload_ids(complete)

        invalid_sets = [
            [],
            [{"id": "field_division"}],
            [
                {"id": "field_division"},
                {"id": "heap_recurrence"},
                {"id": "substituted_case"},
            ],
        ]
        for workloads in invalid_sets:
            with self.subTest(workloads=workloads):
                with self.assertRaisesRegex(SystemExit, "required workload ids"):
                    workload_validation.validate_unique_workload_ids(
                        {"workloads": workloads}
                    )

    def test_required_ids_are_bound_to_documented_input_tuples(self):
        plan = json.loads(workload_validation.PLAN_PATH.read_text())
        workload_validation.validate_workload_identities(plan)

        plan["workloads"][1]["artifact"] = plan["workloads"][0]["artifact"]
        with self.assertRaisesRegex(SystemExit, "documented identity"):
            workload_validation.validate_workload_identities(plan)

        plan["workloads"][1]["artifact"] = (
            workload_validation.REQUIRED_WORKLOAD_INPUTS["heap_recurrence"][1]
        )
        plan["workloads"][1]["expected"]["cycles"] += 1
        with self.assertRaisesRegex(SystemExit, "canonical contents"):
            workload_validation.validate_workload_identities(plan)

    def test_upstream_repository_attribution_is_pinned(self):
        upstream = {
            "repository": workload_validation.SUPPORTED_UPSTREAM_REPOSITORY,
            "commit": workload_validation.SUPPORTED_UPSTREAM_COMMIT,
        }
        workload_validation.validate_upstream_repository(upstream)

        upstream["repository"] = "https://example.invalid/not-the-oracle.git"
        with self.assertRaisesRegex(SystemExit, "repository is unsupported"):
            workload_validation.validate_upstream_repository(upstream)

        upstream = {
            "repository": workload_validation.SUPPORTED_UPSTREAM_REPOSITORY,
            "commit": "0" * 40,
        }
        with self.assertRaisesRegex(SystemExit, "commit is unsupported"):
            workload_validation.validate_upstream_repository(upstream)

    def test_changed_upstream_origin_cannot_survive_postflight_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            cargo_lock = repo / "Cargo.lock"
            origin = repo / "case.json"
            cargo_lock.write_text("pinned lock\n")
            origin.write_text("pinned origin\n")
            subprocess.run(["git", "add", "Cargo.lock", "case.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            plan = {
                "upstream": {
                    "commit": head,
                    "cargo_lock_sha256": workload_validation.sha(cargo_lock),
                },
                "workloads": [{
                    "origin": "case.json",
                    "origin_sha256": workload_validation.sha(origin),
                }],
            }
            workload_validation.validate_upstream_checkout(repo, plan)

            origin.write_text("changed during comparison\n")
            with self.assertRaisesRegex(SystemExit, "must match HEAD"):
                workload_validation.validate_upstream_checkout(repo, plan)

    def test_hidden_tracked_change_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            tracked = repo / "tracked.txt"
            tracked.write_text("committed\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            subprocess.run(
                ["git", "update-index", "--assume-unchanged", "tracked.txt"],
                cwd=repo,
                check=True,
            )
            tracked.write_text("hidden change\n")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=repo, text=True
                ),
                "",
            )

            with self.assertRaisesRegex(SystemExit, "must match HEAD"):
                workload_validation.require_clean_tracked_worktree(repo)

    def test_clean_filter_cannot_hide_different_executed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "filter.mask.clean", "sed s/EVIL/GOOD/"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "filter.mask.smudge", "cat"],
                cwd=repo,
                check=True,
            )
            (repo / ".gitattributes").write_text("model.py filter=mask\n")
            model = repo / "model.py"
            model.write_text("MODEL = 'GOOD'\n")
            subprocess.run(["git", "add", ".gitattributes", "model.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "canonical"], cwd=repo, check=True)
            model.write_text("MODEL = 'EVIL'\n")
            self.assertEqual(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=repo, text=True
                ),
                "",
            )

            with self.assertRaisesRegex(SystemExit, "must match HEAD"):
                workload_validation.require_clean_tracked_worktree(repo)

    def test_git_replacement_objects_are_rejected_and_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            tracked = repo / "tracked.txt"
            tracked.write_text("canonical\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "canonical"], cwd=repo, check=True)
            original = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            tracked.write_text("replacement\n")
            subprocess.run(["git", "commit", "-qam", "replacement"], cwd=repo, check=True)
            replacement = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            subprocess.run(["git", "checkout", "-q", original], cwd=repo, check=True)
            replacement_env = dict(workload_validation.os.environ)
            replacement_env.pop("GIT_NO_REPLACE_OBJECTS")
            subprocess.run(
                ["git", "replace", original, replacement],
                cwd=repo,
                env=replacement_env,
                check=True,
            )

            self.assertEqual(
                workload_validation.capture(
                    ["git", "show", "HEAD:tracked.txt"], cwd=repo
                ),
                "canonical",
            )
            with self.assertRaisesRegex(SystemExit, "replacement refs"):
                workload_validation.require_clean_worktree(repo)

    def test_pinned_worktree_disables_hooks_and_ignores_live_checkout_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            tracked = repo / "model.py"
            tracked.write_text("MODEL = 'captured'\n")
            subprocess.run(["git", "add", "model.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "captured"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            hook = repo / ".git" / "hooks" / "post-checkout"
            hook.write_text(
                "#!/bin/sh\n"
                "printf \"MODEL = 'hook mutation'\\n\" > model.py\n"
                "git update-index --assume-unchanged model.py\n"
            )
            hook.chmod(0o755)

            with tempfile.TemporaryDirectory() as fake_temp:
                fake_git = Path(fake_temp) / "git"
                marker = Path(fake_temp) / "called"
                fake_git.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n")
                fake_git.chmod(0o755)
                hostile_path = f"{fake_temp}:{workload_validation.os.environ['PATH']}"
                with mock.patch.dict(workload_validation.os.environ, {"PATH": hostile_path}), mock.patch.object(
                    workload_validation, "set_worktree_immutable"
                ) as set_immutable:
                    with workload_validation.pinned_worktree(repo, head) as snapshot:
                        snapshot_root = snapshot.parent
                        self.assertEqual(
                            (snapshot / "model.py").stat().st_mode & 0o222,
                            0,
                        )
                        self.assertEqual(snapshot.stat().st_mode & 0o222, 0)
                        tracked.write_text("MODEL = 'temporary mutation'\n")
                        self.assertEqual(
                            (snapshot / "model.py").read_text(), "MODEL = 'captured'\n"
                        )
                        self.assertEqual(
                            subprocess.check_output(
                                [workload_validation.GIT, "rev-parse", "HEAD"],
                                cwd=snapshot,
                                text=True,
                            ).strip(),
                            head,
                        )
                        tracked.write_text("MODEL = 'captured'\n")
                self.assertFalse(marker.exists())

            set_immutable.assert_has_calls(
                [
                    mock.call(snapshot_root, immutable=True),
                    mock.call(snapshot_root, immutable=False),
                ]
            )

    def test_untracked_package_shadow_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            sim = repo / "sim"
            sim.mkdir()
            (sim / "lsc1_transaction.py").write_text("TRUSTED = True\n")
            subprocess.run(["git", "add", "sim/lsc1_transaction.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            shadow = sim / "lsc1_transaction"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("TRUSTED = False\n")

            with self.assertRaisesRegex(SystemExit, "untracked files"):
                workload_validation.require_clean_worktree(repo)

    def test_ignored_sourceless_package_shadow_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            host = repo / "host"
            host.mkdir()
            (repo / ".gitignore").write_text("*.pyc\n")
            (host / "runtime.py").write_text("TRUSTED = True\n")
            subprocess.run(["git", "add", ".gitignore", "host/runtime.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            shadow = host / "runtime"
            shadow.mkdir()
            (shadow / "__init__.pyc").write_bytes(b"unchecked bytecode")

            with self.assertRaisesRegex(SystemExit, "ignored importable paths"):
                workload_validation.require_clean_worktree(repo)

    def test_info_excluded_source_package_shadow_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            host = repo / "host"
            host.mkdir()
            (host / "runtime.py").write_text("TRUSTED = True\n")
            subprocess.run(["git", "add", "host/runtime.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            exclude = repo / ".git" / "info" / "exclude"
            exclude.write_text(exclude.read_text() + "\nhost/runtime/\n")
            shadow = host / "runtime"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("TRUSTED = False\n")

            with self.assertRaisesRegex(SystemExit, "ignored importable paths"):
                workload_validation.require_clean_worktree(repo)

    def test_ignored_symlinked_package_shadow_is_not_accepted_as_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            repo = base / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            host = repo / "host"
            host.mkdir()
            (host / "runtime.py").write_text("TRUSTED = True\n")
            subprocess.run(["git", "add", "host/runtime.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            exclude = repo / ".git" / "info" / "exclude"
            exclude.write_text(exclude.read_text() + "\nhost/runtime\n")
            external = base / "external-runtime"
            external.mkdir()
            (external / "__init__.py").write_text("TRUSTED = False\n")
            (host / "runtime").symlink_to(external, target_is_directory=True)

            with self.assertRaisesRegex(SystemExit, "ignored importable paths"):
                workload_validation.require_clean_worktree(repo)

    def test_selected_count_is_derived_from_validated_plan(self):
        plan = {"workloads": [{"id": "one"}, {"id": "two"}]}
        self.assertEqual(workload_validation.selected_workload_count(plan), 2)

    def test_plan_runtime_must_match_fixed_comparator_runtime(self):
        changed = dict(workload_validation.SUPPORTED_RUNTIME)
        changed["public_input"] = ["0x2", "0x0"]

        with self.assertRaisesRegex(SystemExit, "plan runtime differs"):
            workload_validation.validate_runtime(changed)

    def test_expected_outcome_includes_precise_model_boundary(self):
        comparison = {
            "comparison": {
                "result": "MISMATCH",
                "mismatches": [{"field": "terminal", "host": "fault"}],
            },
            "upstream": {"cycles": 58},
            "lean_silicon": {
                "terminal": "fault",
                "reason": "pc 1 raised bad_pointer preparing the transaction",
                "steps": [{"pc": 0}],
                "final_state": {"written": [0, 1, 3]},
            },
        }

        outcome = workload_validation.comparison_outcome(comparison)

        self.assertEqual(outcome["model_steps"], 1)
        self.assertEqual(
            outcome["reason"], "pc 1 raised bad_pointer preparing the transaction"
        )
        self.assertEqual(
            outcome["mismatches"], [{"field": "terminal", "host": "fault"}]
        )
        self.assertEqual(outcome["model_written"], [0, 1, 3])

    def test_comparison_profile_must_match_planned_runtime(self):
        comparison = {"lean_silicon": {"profile": "INTERPRETER_COMPAT"}}
        runtime = dict(workload_validation.SUPPORTED_RUNTIME)
        workload_validation.validate_comparison_runtime(comparison, runtime)

        comparison["lean_silicon"]["profile"] = "FORWARD_ONLY"
        with self.assertRaisesRegex(SystemExit, "comparison profile differs"):
            workload_validation.validate_comparison_runtime(comparison, runtime)

    def test_artifact_embedded_source_must_match_checked_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "case.zkdsl"
            source.write_text("def main():\n    return\n")
            artifact = {
                "source": {
                    "path": "workloads/case.zkdsl",
                    "sha256": workload_validation.sha(source),
                    "text": source.read_text(),
                }
            }
            workload_validation.validate_source_binding(
                source, artifact, "workloads/case.zkdsl"
            )

            artifact["source"]["text"] = "def main():\n    assert 1 == 0\n"
            with self.assertRaisesRegex(SystemExit, "source binding mismatch"):
                workload_validation.validate_source_binding(
                    source, artifact, "workloads/case.zkdsl"
                )

    def test_artifact_public_input_must_match_planned_runtime(self):
        runtime = dict(workload_validation.SUPPORTED_RUNTIME)
        artifact = {
            "upstream_execution": {
                "public_input": list(runtime["public_input"]),
            }
        }
        workload_validation.validate_artifact_runtime(artifact, runtime)

        artifact["upstream_execution"]["public_input"][0] = "0x2"
        with self.assertRaisesRegex(SystemExit, "public input differs"):
            workload_validation.validate_artifact_runtime(artifact, runtime)

    def test_new_invocation_invalidates_stale_aggregate_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            stale = cache / "receipt.json"
            stale.write_text(json.dumps({"status": "pass"}))

            receipt_path = workload_validation.prepare_receipt_path(cache)

            self.assertEqual(receipt_path, stale)
            self.assertFalse(stale.exists())

    def test_plan_is_loaded_from_captured_revision_not_live_path(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            plan_path = repo / "workloads" / "plan.json"
            plan_path.parent.mkdir()
            plan_path.write_text('{"identity":"captured"}\n')
            subprocess.run(["git", "add", "workloads/plan.json"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "plan"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            plan_path.write_text('{"identity":"transient"}\n')

            plan, plan_bytes = workload_validation.load_captured_plan(head, repo)

            self.assertEqual(plan, {"identity": "captured"})
            self.assertEqual(plan_bytes, b'{"identity":"captured"}\n')

    def test_failed_run_cannot_reuse_stale_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            out.write_text(json.dumps({"stale": True}))
            failed = subprocess.CompletedProcess([], 1, stdout="current run failed\n")

            with mock.patch.object(workload_validation.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(SystemExit, "comparison produced no receipt"):
                    workload_validation.run_comparison(
                        [workload_validation.sys.executable, "-I", "comparison"],
                        out,
                        "case",
                    )

            self.assertFalse(out.exists())

    def test_nonzero_run_accepts_fresh_expected_mismatch_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            expected = {"comparison": {"result": "MISMATCH"}}

            def write_fresh_receipt(*_args, **_kwargs):
                out.write_text(json.dumps({"forged_cache_file": True}))
                return subprocess.CompletedProcess(
                    [], 1, stdout=json.dumps(expected)
                )

            with mock.patch.object(workload_validation.subprocess, "run", side_effect=write_fresh_receipt):
                run, receipt = workload_validation.run_comparison(
                    [workload_validation.sys.executable, "-I", "comparison"],
                    out,
                    "case",
                )

            self.assertEqual(run.returncode, 1)
            self.assertEqual(receipt, expected)
            self.assertEqual(json.loads(out.read_text()), expected)

    def test_comparison_diagnostics_do_not_contaminate_fresh_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            expected = {"comparison": {"result": "MISMATCH"}}
            completed = subprocess.CompletedProcess(
                [], 1, stdout=json.dumps(expected), stderr="expected mismatch\n"
            )

            with mock.patch.object(workload_validation.subprocess, "run", return_value=completed):
                run, receipt = workload_validation.run_comparison(
                    [workload_validation.sys.executable, "-I", "comparison"],
                    out,
                    "case",
                )

            self.assertEqual(run.stderr, "expected mismatch\n")
            self.assertEqual(receipt, expected)
            self.assertEqual(json.loads(out.read_text()), expected)

    def test_comparison_uses_fresh_isolated_bytecode_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "comparison.json"
            observed_cache = None

            def inspect_isolated_cache(*_args, **kwargs):
                nonlocal observed_cache
                command = _args[0]
                prefix_option = next(
                    item for item in command if item.startswith("pycache_prefix=")
                )
                observed_cache = Path(prefix_option.split("=", 1)[1])
                self.assertTrue(observed_cache.is_dir())
                self.assertEqual(command[1:3], ["-I", "-X"])
                return subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=json.dumps({"comparison": {"result": "MATCH"}}),
                )

            with mock.patch.object(
                workload_validation.subprocess,
                "run",
                side_effect=inspect_isolated_cache,
            ):
                workload_validation.run_comparison(
                    [workload_validation.sys.executable, "-I", "comparison"],
                    out,
                    "case",
                )

            self.assertIsNotNone(observed_cache)
            self.assertFalse(observed_cache.exists())

    def test_changed_checkout_cannot_publish_aggregate_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            receipt_path = Path(temp) / "receipt.json"
            with mock.patch.object(
                workload_validation, "clean_head", return_value=("new-head", "new-tree")
            ):
                with self.assertRaisesRegex(SystemExit, "checkout changed"):
                    workload_validation.publish_receipt(
                        receipt_path, {"status": "pass"}, ("old-head", "old-tree")
                    )

            self.assertFalse(receipt_path.exists())


if __name__ == "__main__":
    unittest.main()
