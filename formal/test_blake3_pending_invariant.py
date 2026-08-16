#!/usr/bin/env python3
"""Harness regressions for independent BLAKE3 pending-invariant mutants."""

from __future__ import annotations

import contextlib
import io
import json
import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from formal import check_blake3_pending_invariant as check
from formal import validate_blake3_pending_contract as validator


class Blake3PendingInvariantHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        version = subprocess.run(["yosys", "-V"], text=True,
                                 stdout=subprocess.PIPE).stdout.strip()
        self.assertEqual(
            validator._yosys_identity(version),
            (validator.SUPPORTED_YOSYS_VERSION, validator.SUPPORTED_YOSYS_GIT_SHA),
            "authoritative oracle tests require the exact repository-pinned OSS CAD Suite",
        )
        self.runtime_version = version
        archive = os.environ.get("OSS_CAD_SUITE_ARCHIVE")
        self.assertIsNotNone(archive, "tests require the authenticated pinned archive")
        self.assertEqual(validator.sha256(Path(archive)), validator.MANIFEST["archive_sha256"])

    def test_emitted_yosys_representation_fixtures(self) -> None:
        fixtures = check.FORMAL / "fixtures" / "blake3_pending_oracle"
        legacy = json.loads((fixtures / "yosys-0.33-assert.json").read_text())
        self.assertTrue(legacy["creator"].startswith("Yosys 0.33"))
        valid, reason, meta = validator.validate_design(legacy, self.runtime_version)
        self.assertFalse(valid)
        self.assertEqual(reason, "json_creator_missing_or_malformed")

        pinned = json.loads((fixtures / "yosys-0.68-check.json").read_text())
        self.assertTrue(pinned["creator"].startswith("Yosys 0.68+40"))
        valid, reason, meta = validator.validate_design(pinned, self.runtime_version)
        self.assertTrue(valid, reason)
        self.assertGreater(meta["representation_classification"]["check_flavor_cell"], 0)
        self.assertGreater(meta["trigger_classification"]["check_combinational"], 0)
        self.assertEqual(meta["supported_yosys_range"], validator.SUPPORTED_YOSYS_RANGE)

    def test_all_legacy_trigger_forms_fail_closed_identically(self) -> None:
        """Legacy cells cannot prove continuous sampling, regardless of source form."""
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.33-assert.json"
        baseline = json.loads(fixture.read_text())
        cells = baseline["modules"][validator.TOP]["cells"]
        target_name = next(name for name, cell in cells.items()
                           if cell.get("type") == "$assert")
        for form in ("combinational", "posedge", "negedge", "level", "multi_event"):
            # These source forms are deliberately represented by the same actual
            # emitted 0.33 fixture: that indistinguishability is precisely why
            # none can be certified as continuously sampled from this JSON.
            design = copy.deepcopy(baseline)
            self.assertEqual(design["modules"][validator.TOP]["cells"][target_name],
                             baseline["modules"][validator.TOP]["cells"][target_name])
            valid, reason, meta = validator.validate_design(design, self.runtime_version)
            self.assertFalse(valid, f"legacy {form} unexpectedly validated")
            self.assertEqual(reason, "json_creator_missing_or_malformed")

    def test_pinned_check_trigger_semantics(self) -> None:
        """Exercise trigger encodings emitted by the pinned Yosys $check form."""
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        baseline = json.loads(fixture.read_text())
        cells = baseline["modules"][validator.TOP]["cells"]
        target_name = next(name for name, cell in cells.items()
                           if cell.get("type") == "$check"
                           and cell.get("parameters", {}).get("FLAVOR") == "assert"
                           and cell.get("parameters", {}).get("TRG_ENABLE", "").endswith("0")
                           and cell.get("connections", {}).get("TRG") == [])

        valid, reason, meta = validator.validate_design(copy.deepcopy(baseline), self.runtime_version)
        self.assertTrue(valid, reason)
        self.assertEqual(meta["trigger_classification"]["check_combinational"], 1)

        variants = {
            "posedge": ("1", [2], "check_posedge_triggered"),
            "negedge": ("0", [2], "check_negedge_triggered"),
        }
        for name, (polarity, bits, classification) in variants.items():
            design = copy.deepcopy(baseline)
            target = design["modules"][validator.TOP]["cells"][target_name]
            target["parameters"].update(TRG_ENABLE="1", TRG_WIDTH="1",
                                         TRG_POLARITY=polarity)
            target["connections"]["TRG"] = bits
            valid, reason, meta = validator.validate_design(design, self.runtime_version)
            self.assertFalse(valid, f"{name} unexpectedly validated")
            self.assertIn("production_blake_pending_implication_cells=0", reason)
            self.assertGreaterEqual(meta["trigger_classification"][classification], 1)

        event = copy.deepcopy(baseline)
        target = event["modules"][validator.TOP]["cells"][target_name]
        target["parameters"].update(TRG_ENABLE="1", TRG_WIDTH="10", TRG_POLARITY="10")
        target["connections"]["TRG"] = [2, 3]
        valid, reason, meta = validator.validate_design(event, self.runtime_version)
        self.assertFalse(valid, "event-triggered pending assertion unexpectedly validated")
        self.assertIn("production_blake_pending_implication_cells=0", reason)
        self.assertEqual(meta["trigger_classification"]["check_event_triggered"], 1)

        malformed = copy.deepcopy(baseline)
        target = malformed["modules"][validator.TOP]["cells"][target_name]
        target["parameters"].update(TRG_ENABLE="1", TRG_WIDTH="1", TRG_POLARITY="x")
        target["connections"]["TRG"] = [2]
        valid, reason, meta = validator.validate_design(malformed, self.runtime_version)
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_formal_cell_representation")
        self.assertEqual(meta["trigger_classification"]["unknown_check_trigger"], 1)

    def test_irrelevant_triggered_assert_cannot_satisfy_contract(self) -> None:
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        design = json.loads(fixture.read_text())
        cells = design["modules"][validator.TOP]["cells"]
        target_name = next(name for name, cell in cells.items()
                           if cell.get("type") == "$check"
                           and cell.get("parameters", {}).get("FLAVOR") == "assert"
                           and cell.get("connections", {}).get("TRG") == [])
        target = cells.pop(target_name)
        target["parameters"].update(TRG_ENABLE="1", TRG_WIDTH="1", TRG_POLARITY="1")
        target["connections"]["TRG"] = [2]
        cells["irrelevant_triggered_pending_assert"] = target
        valid, reason, _ = validator.validate_design(design, self.runtime_version)
        self.assertFalse(valid)
        self.assertIn("production_blake_pending_implication_cells=0", reason)

    def test_unknown_check_representation_fails_closed(self) -> None:
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        design = json.loads(fixture.read_text())
        cells = design["modules"][validator.TOP]["cells"]
        assertion = next(cell for cell in cells.values()
                         if cell.get("type") == "$check"
                         and cell.get("parameters", {}).get("FLAVOR") == "assert")
        assertion["parameters"]["FLAVOR"] = "future_assert_encoding"
        valid, reason, _ = validator.validate_design(design, self.runtime_version)
        self.assertFalse(valid)
        self.assertEqual(reason, "unsupported_formal_cell_representation")

    def test_creator_and_runtime_provenance_fail_closed(self) -> None:
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        baseline = json.loads(fixture.read_text())
        cases = (
            (None, self.runtime_version, "json_creator_missing_or_malformed"),
            ("garbage", self.runtime_version, "json_creator_missing_or_malformed"),
            ("Yosys 0.68+39 (git sha1 0f2bcb94b)", self.runtime_version,
             "json_creator_unsupported_yosys_build"),
            ("Yosys 0.68+40 (git sha1 111111111)", self.runtime_version,
             "json_creator_unsupported_yosys_build"),
            ("Yosys 0.69+1 (git sha1 0f2bcb94b)", self.runtime_version,
             "json_creator_unsupported_yosys_build"),
            ("Yosys 0.33 (git sha1 2584903a060)", self.runtime_version,
             "json_creator_missing_or_malformed"),
            (baseline["creator"], "garbage", "runtime_yosys_version_missing_or_malformed"),
            (baseline["creator"], "Yosys 0.69+1 (git sha1 0f2bcb94b)",
             "runtime_unsupported_yosys_build"),
            (baseline["creator"], "Yosys 0.68+40 (git sha1 111111111)",
             "runtime_unsupported_yosys_build"),
        )
        for creator, runtime, expected_reason in cases:
            design = copy.deepcopy(baseline)
            if creator is None:
                design.pop("creator", None)
            else:
                design["creator"] = creator
            with self.subTest(creator=creator, runtime=runtime):
                valid, reason, _ = validator.validate_design(design, runtime)
                self.assertFalse(valid)
                self.assertEqual(reason, expected_reason)

        valid, reason, meta = validator.validate_design(baseline, self.runtime_version)
        self.assertTrue(valid, reason)
        self.assertEqual(meta["creator_identity"], meta["runtime_identity"])

    def test_authoritative_path_cannot_be_spoofed_with_a_fixture(self) -> None:
        """The CLI boundary always generates JSON with its verified executable."""
        fixture = check.FORMAL / "fixtures" / "blake3_pending_oracle" / "yosys-0.68-check.json"
        valid, reason, meta = validator.validate(fixture)
        self.assertFalse(valid)
        self.assertEqual(reason, "production_invariant_elaboration_failed")
        self.assertEqual(meta["runtime_yosys_version"], self.runtime_version)
        self.assertEqual(meta["consumption_route"],
                         "fixed_parent_sealed_snapshot_descriptor_runtime_and_io")

    def test_authoritative_binary_digest_and_path_fail_closed(self) -> None:
        """A banner/fixture copier, tampered binary, or symlink never executes."""
        production = check.FORMAL / check.INVARIANT
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            marker = root / "executed"
            fake = root / "yosys"
            fake.write_text(f"#!/bin/sh\ntouch {marker}\necho '{self.runtime_version}'\n")
            fake.chmod(0o755)
            valid, reason, _ = validator.validate(production, str(fake))
            self.assertFalse(valid)
            self.assertEqual(reason, "yosys_executable_digest_mismatch")
            self.assertFalse(marker.exists(), "digest-rejected executable was run")

            pinned = Path(subprocess.run(["sh", "-c", "command -v yosys"], text=True,
                                         stdout=subprocess.PIPE, check=True).stdout.strip())
            tampered = root / "tampered-yosys"
            tampered.write_bytes(pinned.read_bytes() + b"\n# tampered\n")
            tampered.chmod(0o755)
            valid, reason, _ = validator.validate(production, str(tampered))
            self.assertFalse(valid)
            self.assertEqual(reason, "yosys_executable_digest_mismatch")

            substitute = root / "path-yosys"
            substitute.symlink_to(pinned)
            valid, reason, _ = validator.validate(production, str(substitute))
            self.assertFalse(valid)
            self.assertTrue(reason.startswith("yosys_executable_no_follow_open_failed"), reason)

    def test_authenticated_archive_boundary_fails_closed(self) -> None:
        production = check.FORMAL / check.INVARIANT
        pinned = Path(subprocess.run(["sh", "-c", "command -v yosys"], text=True,
                                     stdout=subprocess.PIPE, check=True).stdout.strip())
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tampered = root / "suite.tgz"
            tampered.write_bytes(b"not the pinned archive")
            with mock.patch.dict(os.environ, {"OSS_CAD_SUITE_ARCHIVE": str(tampered)}):
                valid, reason, _ = validator.validate(production)
            self.assertFalse(valid)
            self.assertEqual(reason, "archive_digest_mismatch")

            link = root / "linked-suite.tgz"
            link.symlink_to(os.environ["OSS_CAD_SUITE_ARCHIVE"])
            with mock.patch.dict(os.environ, {"OSS_CAD_SUITE_ARCHIVE": str(link)}):
                valid, reason, _ = validator.validate(production)
            self.assertFalse(valid)
            self.assertTrue(reason.startswith("archive_no_follow_open_failed"), reason)

            path_bin = root / "bin"
            path_bin.mkdir()
            (path_bin / "yosys").symlink_to(pinned)
            with mock.patch.dict(os.environ, {"PATH": str(path_bin)}):
                valid, reason, _ = validator.validate(production, "yosys")
            self.assertFalse(valid)
            self.assertTrue(reason.startswith("yosys_executable_no_follow_open_failed"), reason)

    def test_authoritative_toctou_checks_fail_closed(self) -> None:
        production = check.FORMAL / check.INVARIANT
        original = validator._verify_fd_unchanged
        calls = 0

        def unstable(fd, before):
            nonlocal calls
            calls += 1
            stable, after = original(fd, before)
            if calls == 1:
                return False, {**after, "simulated_change": True}
            return stable, after

        with mock.patch.object(validator, "_verify_fd_unchanged", side_effect=unstable):
            valid, reason, _ = validator.validate(production)
        self.assertFalse(valid)
        self.assertEqual(reason, "archive_changed_during_version")

        calls = 0
        def unstable_source(fd, before):
            nonlocal calls
            calls += 1
            stable, after = original(fd, before)
            if calls == 3:
                return False, {**after, "simulated_change": True}
            return stable, after

        with mock.patch.object(validator, "_verify_fd_unchanged", side_effect=unstable_source):
            valid, reason, _ = validator.validate(production)
        self.assertFalse(valid)
        self.assertEqual(reason, "source_changed_during_elaboration")

    def test_authoritative_source_symlink_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            link = Path(raw) / "invariant.sv"
            link.symlink_to(check.FORMAL / check.INVARIANT)
            valid, reason, _ = validator.validate(link)
        self.assertFalse(valid)
        self.assertTrue(reason.startswith("source_no_follow_open_failed"), reason)

    def test_preexisting_extracted_tree_substitution_is_ignored(self) -> None:
        """Ambient extracted files are ignored in favor of the authenticated archive."""
        pinned = Path(subprocess.run(["sh", "-c", "command -v yosys"], text=True,
                                     stdout=subprocess.PIPE, check=True).stdout.strip())
        with tempfile.TemporaryDirectory() as raw:
            fake_suite = Path(raw)
            (fake_suite / "bin").mkdir()
            os.link(pinned, fake_suite / "bin" / "yosys")
            for relative in ("lib/ld-linux-x86-64.so.2", "lib/libstdc++.so.6",
                             "libexec/yosys", "share/yosys/plugins/spoof.so",
                             "share/yosys/spoof.txt"):
                target = fake_suite / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("forged runtime object\n")
            valid, reason, meta = validator.validate(
                check.FORMAL / check.INVARIANT, str(fake_suite / "bin" / "yosys"))
        self.assertTrue(valid, reason)
        self.assertEqual(meta["snapshot_route"],
                         "fixed-parent_sealed_snapshot_descriptor_entries")

    def test_cli_preserves_final_source_symlink_for_no_follow(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            link = Path(raw) / "invariant.sv"
            link.symlink_to(check.FORMAL / check.INVARIANT)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                rc = validator.main(["validator", str(link)])
            receipt = json.loads(output.getvalue())
        self.assertEqual(rc, 1)
        self.assertTrue(receipt["reason"].startswith("source_no_follow_open_failed"))

    def test_read_only_nested_snapshot_cleanup_leaves_no_residue(self) -> None:
        """Cleanup restores deep sealed modes before removing the private tree."""
        with tempfile.TemporaryDirectory() as raw:
            private = Path(raw) / "private"
            nested = private / "oss-cad-suite" / "examples" / "abstract" / "deep"
            nested.mkdir(parents=True)
            (nested / "model.v").write_text("module model; endmodule\n")
            for entry in sorted(private.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                os.chmod(entry, 0o400 if entry.is_file() else 0o500)
            os.chmod(private, 0o500)
            validator._remove_private_tree(private)
            self.assertFalse(private.exists(), "private snapshot residue remains")

    def test_production_workspace_acquisition_is_transactional(self) -> None:
        """Every acquisition failure leaves neither descriptors nor workspace residue."""
        production = check.FORMAL / check.INVARIANT
        real_open = validator._CleanupTransaction.open_fd
        real_create = validator._CleanupTransaction.create_private_tree

        def fail_open(target):
            def replacement(owner, name, path, flags, mode=0o777, *, dir_fd=None):
                if name == target:
                    raise OSError(f"injected {target} open failure")
                return real_open(owner, name, path, flags, mode, dir_fd=dir_fd)
            return mock.patch.object(validator._CleanupTransaction, "open_fd", replacement)

        def fail_after_open(target):
            def replacement(owner, name, path, flags, mode=0o777, *, dir_fd=None):
                fd = real_open(owner, name, path, flags, mode, dir_fd=dir_fd)
                if name == target:
                    raise RuntimeError(f"injected {target} registration-boundary failure")
                return fd
            return mock.patch.object(validator._CleanupTransaction, "open_fd", replacement)

        def fail_after_create():
            def replacement(owner, *, prefix, dir):
                path = real_create(owner, prefix=prefix, dir=dir)
                raise RuntimeError("injected tree registration-boundary failure")
            return mock.patch.object(
                validator._CleanupTransaction, "create_private_tree", replacement)

        def fail_fstat(target):
            real_fstat = validator._workspace_fstat

            def replacement(name, fd):
                if name == target:
                    raise OSError(f"injected {target} fstat failure")
                return real_fstat(name, fd)
            return mock.patch.object(validator, "_workspace_fstat", side_effect=replacement)

        cases = {
            "mkdtemp": lambda: mock.patch.object(
                validator.tempfile, "mkdtemp", side_effect=OSError("injected mkdtemp failure")),
            "parent_open": lambda: fail_open("parent"),
            "parent_fstat": lambda: fail_fstat("parent"),
            "tree_registration_boundary": fail_after_create,
            "chmod_after_mkdtemp": lambda: mock.patch.object(
                validator, "_workspace_chmod", side_effect=OSError("injected chmod failure")),
            "workspace_open": lambda: fail_open("workspace"),
            "workspace_fstat": lambda: fail_fstat("workspace"),
            "owner_mode_verification": lambda: mock.patch.object(
                validator, "_workspace_policy_valid", return_value=False),
            "parent_registration_boundary": lambda: fail_after_open("parent"),
            "workspace_registration_boundary": lambda: fail_after_open("workspace"),
        }
        for name, patch_factory in cases.items():
            with self.subTest(step=name):
                before_fds = len(os.listdir("/proc/self/fd"))
                before_paths = set(Path("/tmp").glob("blake-pending-contract-*"))
                with patch_factory():
                    valid, reason, meta = validator.validate(production)
                self.assertFalse(valid)
                self.assertTrue(reason.startswith("private_workspace_failed:"), reason)
                self.assertNotIn("cleanup_failure", meta)
                self.assertEqual(len(os.listdir("/proc/self/fd")), before_fds,
                                 f"fd leak after {name}")
                self.assertEqual(set(Path("/tmp").glob("blake-pending-contract-*")),
                                 before_paths, f"workspace residue after {name}")

        before_fds = len(os.listdir("/proc/self/fd"))
        before_paths = set(Path("/tmp").glob("blake-pending-contract-*"))
        real_close = validator._close_owned_fd

        def fail_parent_close(name, fd):
            real_close(name, fd)
            if name == "parent":
                raise OSError("injected acquisition cleanup failure")

        with mock.patch.object(
                validator, "_workspace_chmod",
                side_effect=OSError("injected acquisition primary failure")), \
                mock.patch.object(
                    validator, "_close_owned_fd", side_effect=fail_parent_close):
            valid, reason, meta = validator.validate(production)
        self.assertFalse(valid)
        self.assertIn("injected acquisition primary failure", reason)
        self.assertEqual(meta["cleanup_failure"]["classification"], "secondary")
        self.assertEqual(meta["cleanup_failure"]["failures"][0]["action"], "close_parent")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before_fds)
        self.assertEqual(set(Path("/tmp").glob("blake-pending-contract-*")), before_paths)

    def test_registration_assignment_rollback_is_strongly_exception_safe(self) -> None:
        """Failures inside ownership assignment roll back locals on the production path."""
        production = check.FORMAL / check.INVARIANT
        real_register_fd = validator._CleanupTransaction._register_fd
        real_register_tree = validator._CleanupTransaction._register_private_tree

        def fail_fd_registration(target):
            def replacement(owner, name, fd):
                if name == target:
                    raise RuntimeError(f"injected {target} mapping assignment failure")
                return real_register_fd(owner, name, fd)
            return mock.patch.object(
                validator._CleanupTransaction, "_register_fd", replacement)

        def fail_tree_registration(owner, path):
            del owner, path
            raise RuntimeError("injected private attribute assignment failure")

        cases = {
            "parent_mapping_assignment": lambda: fail_fd_registration("parent"),
            "workspace_mapping_assignment": lambda: fail_fd_registration("workspace"),
            "private_attribute_assignment": lambda: mock.patch.object(
                validator._CleanupTransaction, "_register_private_tree",
                fail_tree_registration),
        }
        for name, patch_factory in cases.items():
            with self.subTest(step=name):
                before_fds = len(os.listdir("/proc/self/fd"))
                before_paths = set(Path("/tmp").glob("blake-pending-contract-*"))
                with patch_factory():
                    valid, reason, meta = validator.validate(production)
                self.assertFalse(valid)
                self.assertTrue(reason.startswith("private_workspace_failed:"), reason)
                self.assertNotIn("cleanup_failure", meta)
                self.assertEqual(len(os.listdir("/proc/self/fd")), before_fds)
                self.assertEqual(set(Path("/tmp").glob("blake-pending-contract-*")),
                                 before_paths)

        before_fds = len(os.listdir("/proc/self/fd"))
        before_paths = set(Path("/tmp").glob("blake-pending-contract-*"))
        real_close = validator._close_owned_fd

        def close_then_fail(name, fd):
            real_close(name, fd)
            if name == "parent":
                raise OSError("injected registration fd rollback failure")

        with fail_fd_registration("parent"), mock.patch.object(
                validator, "_close_owned_fd", side_effect=close_then_fail):
            valid, reason, meta = validator.validate(production)
        self.assertFalse(valid)
        self.assertIn("injected parent mapping assignment failure", reason)
        self.assertEqual(meta["cleanup_failure"]["classification"], "secondary")
        self.assertEqual(meta["cleanup_failure"]["failures"][0]["action"],
                         "rollback_close_parent")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before_fds)
        self.assertEqual(set(Path("/tmp").glob("blake-pending-contract-*")), before_paths)

        real_remove = validator._remove_private_tree

        def remove_then_fail(path):
            real_remove(path)
            raise OSError("injected registration tree rollback failure")

        with mock.patch.object(
                validator._CleanupTransaction, "_register_private_tree",
                fail_tree_registration), mock.patch.object(
                    validator, "_remove_private_tree", side_effect=remove_then_fail):
            valid, reason, meta = validator.validate(production)
        self.assertFalse(valid)
        self.assertIn("injected private attribute assignment failure", reason)
        self.assertEqual(meta["cleanup_failure"]["classification"], "secondary")
        self.assertEqual(meta["cleanup_failure"]["failures"][0]["action"],
                         "rollback_remove_private_tree")
        self.assertEqual(len(os.listdir("/proc/self/fd")), before_fds)
        self.assertEqual(set(Path("/tmp").glob("blake-pending-contract-*")), before_paths)

    def test_primary_success_cleanup_success_preserves_result(self) -> None:
        primary = (True, "primary_success", {})
        cleanup = mock.Mock()
        failure = validator._preserve_primary_across_cleanup(primary, None, cleanup)
        self.assertIsNone(failure)
        self.assertEqual(primary, (True, "primary_success", {}))
        cleanup.assert_called_once_with()

    def test_primary_success_cleanup_failure_makes_cleanup_principal(self) -> None:
        primary = [True, "primary_success", {}]
        failure = validator._preserve_primary_across_cleanup(
            primary, None, mock.Mock(side_effect=RuntimeError("residue")))
        self.assertEqual(failure["classification"], "principal")
        self.assertEqual(failure["message"], "residue")
        self.assertEqual(primary[0:2], [False, "private_workspace_cleanup_failed"])
        self.assertEqual(primary[2]["cleanup_failure"], failure)

    def test_primary_failure_cleanup_success_preserves_primary(self) -> None:
        primary = (False, "primary_failure", {})
        failure = validator._preserve_primary_across_cleanup(primary, None, mock.Mock())
        self.assertIsNone(failure)
        self.assertEqual(primary[1], "primary_failure")
        self.assertNotIn("cleanup_failure", primary[2])

    def test_primary_failure_cleanup_failure_keeps_primary_principal(self) -> None:
        primary = (False, "primary_failure", {})
        failure = validator._preserve_primary_across_cleanup(
            primary, None, mock.Mock(side_effect=RuntimeError("residue")))
        self.assertEqual(primary[1], "primary_failure")
        self.assertEqual(failure["classification"], "secondary")
        self.assertEqual(primary[2]["cleanup_failure"], failure)

        primary_error = ValueError("primary exception")
        failure = validator._preserve_primary_across_cleanup(
            None, primary_error, mock.Mock(side_effect=RuntimeError("residue")))
        self.assertEqual(str(primary_error), "primary exception")
        self.assertEqual(failure["classification"], "secondary")
        self.assertIs(primary_error.cleanup_failure, failure)

    def test_every_cleanup_action_runs_and_failures_are_ordered(self) -> None:
        """Each close/removal position is independent and never stops later cleanup."""
        actions = [f"close_{name}" for name in validator._CleanupTransaction._FD_ORDER]
        actions.append("remove_private_tree")
        for injected in actions:
            with self.subTest(injected=injected), tempfile.TemporaryDirectory() as raw:
                cleanup = validator._CleanupTransaction()
                private = Path(raw) / "private"
                nested = private / "oss-cad-suite" / "examples" / "abstract"
                nested.mkdir(parents=True)
                (nested / "model.v").write_text("module model; endmodule\n")
                cleanup.own_private_tree(private)
                for name in validator._CleanupTransaction._FD_ORDER:
                    cleanup.own_fd(name, os.open(os.devnull, os.O_RDONLY))
                observed = []
                real_close = validator._close_owned_fd
                real_remove = validator._remove_private_tree

                def close(name, fd):
                    observed.append(f"close_{name}")
                    real_close(name, fd)
                    if injected == f"close_{name}":
                        raise OSError(f"injected {name} close failure")

                def remove(path):
                    observed.append("remove_private_tree")
                    real_remove(path)
                    if injected == "remove_private_tree":
                        raise OSError("injected removal failure")

                with mock.patch.object(validator, "_close_owned_fd", side_effect=close), \
                        mock.patch.object(validator, "_remove_private_tree", side_effect=remove):
                    with self.assertRaises(validator._CleanupFailures) as raised:
                        cleanup.run()
                self.assertEqual(observed, actions)
                self.assertEqual(raised.exception.failures[0]["action"], injected)
                self.assertFalse(private.exists(), "removal-capable cleanup left residue")

    def test_cleanup_aggregate_principal_and_secondary_classification(self) -> None:
        cleanup_error = validator._CleanupFailures([
            {"action": "close_output", "type": "OSError", "message": "first"},
            {"action": "close_source", "type": "OSError", "message": "second"},
        ])
        primary = [True, "primary_success", {}]
        failure = validator._preserve_primary_across_cleanup(
            primary, None, mock.Mock(side_effect=cleanup_error))
        self.assertEqual(primary[0:2], [False, "private_workspace_cleanup_failed"])
        self.assertEqual(failure["classification"], "principal")
        self.assertEqual([item["action"] for item in failure["failures"]],
                         ["close_output", "close_source"])

        primary = [False, "primary_failure", {}]
        failure = validator._preserve_primary_across_cleanup(
            primary, None, mock.Mock(side_effect=cleanup_error))
        self.assertEqual(primary[1], "primary_failure")
        self.assertEqual(failure["classification"], "secondary")
        self.assertEqual([item["action"] for item in failure["failures"]],
                         ["close_output", "close_source"])

    def test_internal_double_close_is_reported_as_ebadf(self) -> None:
        cleanup = validator._CleanupTransaction()
        fd = os.open(os.devnull, os.O_RDONLY)
        cleanup.own_fd("output", fd)
        os.close(fd)
        with self.assertRaises(validator._CleanupFailures) as raised:
            cleanup.run()
        failure = raised.exception.failures[0]
        self.assertEqual(failure["action"], "close_output")
        self.assertIn("Bad file descriptor", failure["message"])

    def test_production_validate_classifies_close_failure_without_masking(self) -> None:
        """Exercise the real archive-backed validate path, not only cleanup helpers."""
        production = check.FORMAL / check.INVARIANT
        real_close = validator._close_owned_fd

        def fail_output_close(name, fd):
            real_close(name, fd)
            if name == "output":
                raise OSError("injected production output close failure")

        with mock.patch.object(validator, "_close_owned_fd", side_effect=fail_output_close):
            valid, reason, meta = validator.validate(production)
        self.assertFalse(valid)
        self.assertEqual(reason, "private_workspace_cleanup_failed")
        self.assertEqual(meta["cleanup_failure"]["classification"], "principal")
        self.assertEqual(meta["cleanup_failure"]["failures"][0]["action"], "close_output")

        def primary_failure(*args, **kwargs):
            raise ValueError("injected production primary failure")

        with mock.patch.object(validator, "validate_design", side_effect=primary_failure), \
                mock.patch.object(validator, "_close_owned_fd", side_effect=fail_output_close):
            with self.assertRaisesRegex(ValueError, "injected production primary failure") as raised:
                validator.validate(production)
        self.assertEqual(raised.exception.cleanup_failure["classification"], "secondary")
        self.assertEqual(raised.exception.cleanup_failure["failures"][0]["action"],
                         "close_output")

    def test_hostile_tmpdir_is_ignored(self) -> None:
        production = check.FORMAL / check.INVARIANT
        with tempfile.TemporaryDirectory() as raw:
            hostile = Path(raw) / "hostile"
            hostile.symlink_to("/does/not/exist")
            with mock.patch.dict(os.environ, {"TMPDIR": str(hostile)}):
                valid, reason, meta = validator.validate(production)
        self.assertTrue(valid, reason)
        self.assertEqual(meta["trusted_workspace"]["mode"], "0700")
        self.assertIn("TMPDIR", meta["sanitized_environment"]["removed_variables"])

    def test_deterministic_snapshot_change_is_detected(self) -> None:
        """A test-hook modification is detected; this is not a concurrent-attacker claim."""
        production = check.FORMAL / check.INVARIANT
        original = validator._run_authenticated
        calls = 0

        def swap_runtime(executable, arguments, inherited_fds, env=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                target = Path(env["HOME"]) / "libexec" / "yosys"
                target.parent.chmod(0o700)
                target.chmod(0o700)
                target.unlink()
                target.write_text("forged runtime\n")
                target.chmod(0o500)
                target.parent.chmod(0o500)
            return original(executable, arguments, inherited_fds, env)

        with mock.patch.object(validator, "_run_authenticated", side_effect=swap_runtime):
            valid, reason, _ = validator.validate(production)
        self.assertFalse(valid)
        self.assertEqual(reason, "snapshot_changed_during_elaboration")

    def test_output_path_substitution_cannot_replace_descriptor_result(self) -> None:
        production = check.FORMAL / check.INVARIANT
        original = validator._run_authenticated
        calls = 0

        def substitute_output(executable, arguments, inherited_fds, env=None):
            nonlocal calls
            calls += 1
            if calls == 3:
                output_fd = inherited_fds[2]
                pathname = Path(os.readlink(f"/proc/self/fd/{output_fd}"))
                pathname.unlink()
                pathname.write_text('{"creator":"spoofed","modules":{}}')
            return original(executable, arguments, inherited_fds, env)

        with mock.patch.object(validator, "_run_authenticated", side_effect=substitute_output):
            valid, reason, meta = validator.validate(production)
        self.assertTrue(valid, reason)
        self.assertEqual(meta["output_consumption_route"],
                         "preopened_inherited_descriptor")
        self.assertNotEqual(meta["json_creator"], "spoofed")

    def test_manifest_binds_verified_archive_and_executable(self) -> None:
        self.assertEqual(validator.MANIFEST["archive_bytes"], 737556153)
        self.assertEqual(validator.MANIFEST["archive_sha256"],
                         "7c0f1bb619d03fdf1614b73d84a95a88c64671685c364f87fe0827b7fffc6c4e")
        executable = Path(subprocess.run(["sh", "-c", "command -v yosys"], text=True,
                                         stdout=subprocess.PIPE, check=True).stdout.strip())
        self.assertEqual(validator.sha256(executable), validator.MANIFEST["yosys_sha256"])

    def test_independent_validator_semantics(self) -> None:
        production = (check.FORMAL / check.INVARIANT).read_text()
        pending_block = """    always @(*) begin
        if (blake_result_pending) assert(result_pending);
        cover(blake_result_pending);
    end
"""
        variants = {
            "baseline": (production, True),
            "always_at_star": (production.replace("always @(*) begin", "always @* begin : pending_check"), True),
            "extra_parentheses": (production.replace("assert(result_pending)", "assert(((result_pending)))"), True),
            "weakened": (production.replace(check.PENDING_ASSERTION, check.WEAK_PENDING_ASSERTION), False),
            "removed": (production.replace(check.PENDING_ASSERTION, check.REMOVED_PENDING_ASSERTION), False),
            "disabled_generate": (production.replace(pending_block, """    generate if (1'b0) begin : disabled
        always @* if (blake_result_pending) assert(result_pending);
    end endgenerate
    always @* cover(blake_result_pending);
"""), False),
            "string_literal": (production.replace(pending_block, """    localparam [8*64-1:0] NOTE = "if (blake_result_pending) assert(result_pending);";
    always @* cover(blake_result_pending);
"""), False),
            "unrelated_module": (production.replace(check.PENDING_ASSERTION, "") + "\nmodule decoy(input blake_result_pending, result_pending); always @* if (blake_result_pending) assert(result_pending); endmodule\n", False),
            "benign_control": (production.replace(check.CONTROL_COVER, check.CONTROL_COVER_MUTATION), True),
        }
        with tempfile.TemporaryDirectory() as raw:
            for name, (text, expected) in variants.items():
                path = Path(raw) / f"{name}.sv"
                path.write_text(text)
                valid, reason, _ = validator.validate(path)
                self.assertEqual(valid, expected, f"{name}: {reason}")

    def test_each_mutant_starts_from_the_exact_baseline(self) -> None:
        observations: list[tuple[str, str, bool, bool]] = []

        def fake_run(work, mode):
            frontend = (work / "lsc1_packet_frontend.sv").read_text()
            invariant = (work / check.INVARIANT).read_text()
            observations.append((work.name, mode,
                                 check.UNION_BINDING in frontend,
                                 check.PENDING_ASSERTION in invariant))
            omitted_union = check.UNION_BINDING not in frontend
            return subprocess.CompletedProcess(
                ["sby"], 1 if omitted_union and mode == "bmc" else 0,
                "DONE (FAIL, rc=1)" if omitted_union and mode == "bmc" else "DONE (PASS)",
            )

        output = io.StringIO()
        def fake_validate(work):
            valid, reason, _ = validator.validate(work / check.INVARIANT)
            return subprocess.CompletedProcess(["validator"], 0 if valid else 1,
                                               json.dumps({"valid": valid, "reason": reason}))

        with mock.patch.object(check, "run", side_effect=fake_run), \
             mock.patch.object(check, "validate_contract", side_effect=fake_validate), \
             contextlib.redirect_stdout(output):
            self.assertEqual(check.main(), 0)

        receipt = json.loads(output.getvalue().splitlines()[0])
        self.assertTrue(receipt["baseline_proof"])
        self.assertTrue(receipt["blake_pending_cover"])
        self.assertEqual(
            {(name, mode, union, assertion) for name, mode, union, assertion in observations},
            {
                ("baseline", "bmc", True, True),
                ("baseline", "cover", True, True),
                ("omit_union", "bmc", False, True),
                ("weaken_assertion", "bmc", True, False),
                ("weaken_assertion", "cover", True, False),
                ("remove_assertion", "bmc", True, False),
                ("remove_assertion", "cover", True, False),
            },
        )
        for name, mutation in receipt["mutations"].items():
            self.assertEqual(mutation["anchor_count"], 1)
            self.assertTrue(mutation["isolated"])
            if name != "control_cover_change":
                self.assertTrue(mutation["killed"])
        self.assertTrue(receipt["mutations"]["control_cover_change"]["accepted"])
        self.assertTrue(receipt["mutations"]["weaken_assertion"]["union_intact"])
        self.assertTrue(receipt["mutations"]["remove_assertion"]["union_intact"])


if __name__ == "__main__":
    unittest.main()
