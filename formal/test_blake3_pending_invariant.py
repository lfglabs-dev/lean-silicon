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

    def test_extracted_runtime_substitution_is_not_consumed(self) -> None:
        """Mutable loader/libexec/lib/plugin/data neighbors are outside the root of trust."""
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

    def test_authenticated_descriptors_survive_ancestor_swap(self) -> None:
        """Swapped pathname ancestors cannot change either consumed object."""
        pinned = Path(subprocess.run(["sh", "-c", "command -v yosys"], text=True,
                                     stdout=subprocess.PIPE, check=True).stdout.strip())
        production_text = (check.FORMAL / check.INVARIANT).read_text()
        spoof_text = production_text.replace(check.PENDING_ASSERTION, check.REMOVED_PENDING_ASSERTION)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            live = root / "live"
            parked = root / "parked"
            (live / "bin").mkdir(parents=True)
            (live / "invariant.sv").write_text(production_text)
            os.link(pinned, live / "bin" / "yosys")
            suite = pinned.parent.parent
            (live / "lib").symlink_to(suite / "lib", target_is_directory=True)
            (live / "libexec").symlink_to(suite / "libexec", target_is_directory=True)
            original_run = validator._run_authenticated
            calls = 0

            def swap_then_run(executable_fd, arguments, inherited_fds, env=None):
                nonlocal calls
                calls += 1
                if calls != 2:
                    return original_run(executable_fd, arguments, inherited_fds, env)
                live.rename(parked)
                (live / "bin").mkdir(parents=True)
                (live / "invariant.sv").write_text(spoof_text)
                fake = live / "bin" / "yosys"
                fake.write_text("#!/bin/sh\nexit 99\n")
                fake.chmod(0o755)
                try:
                    return original_run(executable_fd, arguments, inherited_fds, env)
                finally:
                    for entry in (live / "bin").iterdir():
                        entry.unlink()
                    (live / "bin").rmdir()
                    (live / "invariant.sv").unlink()
                    live.rmdir()
                    parked.rename(live)

            with mock.patch.object(validator, "_run_authenticated", side_effect=swap_then_run):
                valid, reason, meta = validator.validate(
                    live / "invariant.sv", str(live / "bin" / "yosys"))
        self.assertTrue(valid, reason)
        self.assertEqual(meta["consumption_route"],
                         "fixed_parent_sealed_snapshot_descriptor_runtime_and_io")
        self.assertEqual(calls, 3)  # dependency audit, version, elaboration

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

    def test_runtime_path_swap_after_audit_fails_closed(self) -> None:
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
