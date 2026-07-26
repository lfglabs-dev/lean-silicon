"""The evidence archive must identify the sources that actually produced it.

`docs/ULX3S_SMOKE_AND_UART.md` claimed the bitstreams came from the branch's
pre-feature base revision. That revision contains no `fpga/ulx3s` file at all,
so the claim could not be checked and the artefacts could not be rebuilt from
it: an evidence archive that cannot name its own source proves nothing.

The build inputs are parsed out of the build scripts rather than restated here,
so adding a source to a build without recording it fails instead of silently
widening the gap between what was built and what was declared. No board and no
FPGA toolchain are involved.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECORDER = ROOT / "tools" / "source_provenance.py"
ULX3S = ROOT / "fpga" / "ulx3s"
DOC = ROOT / "docs" / "ULX3S_SMOKE_AND_UART.md"
RESULTS = ROOT / "results" / "ulx3s-smoke-uart-20260725"

BUILDS = {
    "SOURCE_MANIFEST.txt": ULX3S / "build_smoke.sh",
    "SOURCE_MANIFEST_uart.txt": ULX3S / "build_uart.sh",
}


def _shell_var(text: str, name: str) -> str:
    match = re.search(rf"^{name}=(.+)$", text, re.MULTILINE)
    assert match, f"{name} not found in build script"
    return match.group(1).strip().strip('"')


def build_inputs(script: Path) -> set[str]:
    """Repo-relative design inputs a build script feeds to yosys/nextpnr."""
    text = script.read_text()
    names = [_shell_var(text, "LPF")]
    sources = re.search(r'SOURCES="([^"]*)"', text, re.DOTALL)
    if sources:
        names += sources.group(1).replace("\\\n", " ").split()
    else:
        names.append(_shell_var(text, "TOP") + ".sv")
    return {(ULX3S / n).resolve().relative_to(ROOT).as_posix() for n in names}


def manifest_digests(name: str) -> dict[str, str]:
    entries = {}
    for line in (RESULTS / name).read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            entries[parts[1]] = parts[0]
    return entries


def doc_revision(label: str) -> str:
    match = re.search(rf"{label}[^`]*`([0-9a-f]{{7,40}})`", DOC.read_text())
    assert match, f"docs no longer record a revision for {label!r}"
    return match.group(1)


def _has_revision(rev: str) -> bool:
    """False in a shallow CI clone, where old objects are simply absent."""
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{rev}^{{commit}}"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )


def _blob_at(rev: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "cat-file", "blob", f"{rev}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout if result.returncode == 0 else None


class BuildInputParsingTest(unittest.TestCase):
    """Guards every other test here from passing vacuously on an empty set."""

    def test_both_builds_declare_their_sources(self):
        for manifest, script in BUILDS.items():
            with self.subTest(script=script.name):
                inputs = build_inputs(script)
                self.assertGreaterEqual(len(inputs), 2, f"{script.name}: {inputs}")
                self.assertTrue(any(i.endswith(".lpf") for i in inputs))

    def test_declared_sources_exist(self):
        for script in BUILDS.values():
            for rel in build_inputs(script):
                with self.subTest(source=rel):
                    self.assertTrue((ROOT / rel).is_file(), rel)

    def test_uart_build_pulls_in_the_asic_core(self):
        # The bridge is only evidence if it wraps the real core, not a stub.
        inputs = build_inputs(ULX3S / "build_uart.sh")
        self.assertIn("asic_core/rtl/lean_silicon_lsc1.sv", inputs)


class SourceManifestTest(unittest.TestCase):
    """Content anchor: valid without git history, so CI checks it too."""

    def test_manifest_covers_exactly_the_build_inputs(self):
        for manifest, script in BUILDS.items():
            with self.subTest(manifest=manifest):
                self.assertEqual(set(manifest_digests(manifest)), build_inputs(script))

    def test_manifest_digests_match_the_working_tree(self):
        for manifest in BUILDS:
            for rel, digest in manifest_digests(manifest).items():
                with self.subTest(source=rel):
                    self.assertEqual(
                        sha256((ROOT / rel).read_bytes()).hexdigest(),
                        digest,
                        f"{rel} changed since {manifest} was recorded; rebuild",
                    )

    def test_manifest_records_whether_inputs_matched_the_revision(self):
        for manifest in BUILDS:
            with self.subTest(manifest=manifest):
                text = (RESULTS / manifest).read_text()
                self.assertRegex(text, re.compile(r"^revision: [0-9a-f]{40}$", re.M))
                self.assertRegex(
                    text, re.compile(r"^inputs-match-revision: (yes|no)$", re.M)
                )


class RecorderMatchFlagTest(unittest.TestCase):
    """`inputs-match-revision` must never claim more than was actually compared.

    Driven against throwaway trees rather than the repo, because the interesting
    states -- no git at all, and a modified input -- cannot be staged here.
    """

    def _tree(self) -> Path:
        root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        (root / "tools").mkdir()
        shutil.copy(RECORDER, root / "tools")
        (root / "src").mkdir()
        (root / "src" / "a.sv").write_text("module a; endmodule\n")
        return root

    def _record(self, root: Path) -> dict[str, str]:
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(root.parent))
        subprocess.run(
            ["python3", str(root / "tools" / "source_provenance.py"), "out.txt", "a.sv"],
            cwd=root / "src",
            check=True,
            stdout=subprocess.DEVNULL,
            env=env,
        )
        fields = {}
        for line in (root / "src" / "out.txt").read_text().splitlines():
            key, _, value = line.partition(": ")
            if value:
                fields[key] = value
        return fields

    def _git_tree(self) -> Path:
        root = self._tree()
        for args in (
            ["init", "-q"],
            ["config", "user.email", "t@example.invalid"],
            ["config", "user.name", "t"],
            ["add", "-A"],
            ["-c", "commit.gpgsign=false", "commit", "-qm", "x"],
        ):
            result = subprocess.run(["git", *args], cwd=root, capture_output=True)
            if result.returncode != 0:
                self.skipTest(f"git {args[0]} unavailable: {result.stderr!r}")
        return root

    def test_unidentified_revision_is_not_reported_as_a_match(self):
        # The defect: with no revision, every comparison was skipped and the
        # dirty flag stayed false, so the archive claimed its inputs matched a
        # revision that had never been identified.
        fields = self._record(self._tree())
        self.assertEqual(fields["revision"], "unknown")
        self.assertNotEqual(fields["inputs-match-revision"], "yes")

    def test_committed_inputs_report_a_match(self):
        fields = self._record(self._git_tree())
        self.assertRegex(fields["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(fields["inputs-match-revision"], "yes")

    def test_modified_input_reports_no_match(self):
        root = self._git_tree()
        (root / "src" / "a.sv").write_text("module b; endmodule\n")
        fields = self._record(root)
        self.assertRegex(fields["revision"], r"^[0-9a-f]{40}$")
        self.assertEqual(fields["inputs-match-revision"], "no")

    def test_a_match_is_only_ever_claimed_against_a_named_revision(self):
        # Generalises the three cases above: whatever the tree looks like, "yes"
        # is only honest when a real revision was resolved to compare against.
        for name, make in (("no-git", self._tree), ("git", self._git_tree)):
            with self.subTest(tree=name):
                fields = self._record(make())
                if fields["inputs-match-revision"] == "yes":
                    self.assertRegex(fields["revision"], r"^[0-9a-f]{40}$")


class DocumentedRevisionTest(unittest.TestCase):
    """The revision the docs blame for the artefacts must be able to build them."""

    def test_artefact_revision_is_not_the_branch_base(self):
        self.assertNotEqual(
            doc_revision("Artefact source revision"),
            doc_revision("Branch base"),
            "the pre-feature base cannot be the artefact source",
        )

    def test_artefact_revision_contains_every_build_input(self):
        rev = doc_revision("Artefact source revision")
        if not _has_revision(rev):
            self.skipTest(f"{rev} absent (shallow clone)")
        for script in BUILDS.values():
            for rel in build_inputs(script):
                with self.subTest(rev=rev, source=rel):
                    self.assertIsNotNone(
                        _blob_at(rev, rel),
                        f"{rel} does not exist at {rev}, so it cannot have built the artefacts",
                    )

    def test_artefact_revision_holds_the_recorded_bytes(self):
        rev = doc_revision("Artefact source revision")
        if not _has_revision(rev):
            self.skipTest(f"{rev} absent (shallow clone)")
        for manifest in BUILDS:
            for rel, digest in manifest_digests(manifest).items():
                with self.subTest(rev=rev, source=rel):
                    blob = _blob_at(rev, rel)
                    self.assertIsNotNone(blob, rel)
                    self.assertEqual(sha256(blob).hexdigest(), digest, rel)

    def test_design_sources_are_unchanged_since_the_recorded_revision(self):
        # The docs claim every revision from this one onward emits the same
        # bytes. That only holds while no later commit touches a build input.
        since = doc_revision("Design sources unchanged since")
        if not _has_revision(since) or not _has_revision("HEAD"):
            self.skipTest(f"{since} absent (shallow clone)")
        inputs = sorted(set().union(*(build_inputs(s) for s in BUILDS.values())))
        touched = subprocess.run(
            ["git", "log", "--oneline", f"{since}..HEAD", "--", *inputs],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout.decode().strip()
        self.assertEqual(touched, "", f"design sources changed after {since}:\n{touched}")


if __name__ == "__main__":
    unittest.main()
