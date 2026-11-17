"""Focused offline release-engineering tests. Run independently of telemetry suites."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

MODULE_PATH = Path(__file__).with_name("onyx_release.py")
spec = importlib.util.spec_from_file_location("onyx_release", MODULE_PATH)
rel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rel)


class ReleaseEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Package Test")
        self.git("config", "user.email", "package-test@example.invalid")
        self.add_file("windows/collector/Send-OnyxTelemetry.ps1", b"# telemetry\r\n")
        self.add_file("windows/gateway/OnyxGateway.py", b"print('gateway')\n")
        self.add_file("pi/services/receiver/receiver.py", b"print('receiver')\n")
        self.add_file("pi/services/receiver/launch-receiver.sh", b"#!/bin/sh\nexit 0\n")
        self.add_file("docs/installation/install.md", b"# Install\n")
        self.add_file("docs/recovery/offline-microsd.md", b"# Historical recovery docs\n")
        self.git("add", ".")
        self.git("commit", "-qm", "source")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True)

    def add_file(self, path, contents):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(contents)

    def test_builds_are_byte_identical(self):
        a, b = self.root / "a", self.root / "b"
        rel.build(self.repo, self.commit, "0.9.0-rc1", a)
        rel.build(self.repo, self.commit, "0.9.0-rc1", b)
        for platform in rel.PLATFORMS:
            name = f"ONYX_CORE-v0.9.0-rc1-{platform}.zip"
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())
            info = rel.verify_archive(a / name)
            self.assertEqual(info["source_commit"], self.commit)
            self.assertEqual(info["platform"], platform)

    def test_build_ignores_uncommitted_runtime_changes(self):
        self.add_file("windows/collector/Send-OnyxTelemetry.ps1", b"NOT COMMITTED\n")
        out = self.root / "out"
        rel.build(self.repo, self.commit, "0.9.0-dev1", out)
        with zipfile.ZipFile(out / "ONYX_CORE-v0.9.0-dev1-windows.zip") as zf:
            self.assertEqual(zf.read("windows/collector/Send-OnyxTelemetry.ps1"), b"# telemetry\r\n")

    def test_rejects_wrong_commit_and_invalid_version(self):
        with self.assertRaises(ValueError):
            rel.build(self.repo, "0" * 40, "0.9.0-rc1", self.root / "bad")
        with self.assertRaises(ValueError):
            rel.build(self.repo, self.commit, "bad", self.root / "bad")

    def test_refuses_tracked_credentials(self):
        self.add_file("windows/monitoring/private.env", b"SECRET=not-real\n")
        self.git("add", "-f", "windows/monitoring/private.env")
        self.git("commit", "-qm", "add intentionally disallowed env")
        newer = self.git("rev-parse", "HEAD").strip()
        with self.assertRaisesRegex(ValueError, "unsafe or private tracked content"):
            rel.build(self.repo, newer, "0.9.0-dev1", self.root / "out")

    def test_corrupt_archive_is_detected(self):
        raw = rel.encode_zip("pi-armv6", "0.9.0-rc1", self.commit,
                             rel.tracked_payload(self.repo, self.commit))
        p = self.root / "bad.zip"
        with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(p, "w") as dest:
            for member in src.infolist():
                content = src.read(member.filename)
                if member.filename == "pi/services/receiver/receiver.py":
                    content = b"malicious replacement"
                dest.writestr(member, content)
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            rel.verify_archive(p)

    def test_rejects_duplicate_zip_members(self):
        p = self.root / "duplicate.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("manifest.json", b"{}")
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                zf.writestr("manifest.json", b"{}")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            rel.verify_archive(p)

    def test_refuses_overwrite_of_different_artifact(self):
        out = self.root / "out"
        rel.build(self.repo, self.commit, "0.9.0-rc1", out)
        f = out / "ONYX_CORE-v0.9.0-rc1-windows.zip"
        f.write_bytes(b"wrong")
        with self.assertRaisesRegex(ValueError, "refusing overwrite"):
            rel.build(self.repo, self.commit, "0.9.0-rc1", out)

    def test_rejects_zip_slip_paths(self):
        self.assertFalse(rel.admissible_path("../evil.ps1"))
        self.assertFalse(rel.admissible_path("windows\\evil.ps1"))
        self.assertFalse(rel.admissible_path("/tmp/evil"))
        self.assertTrue(rel.admissible_path("windows/collector/Send-OnyxTelemetry.ps1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
