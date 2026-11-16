"""R3 protected-source admission, offline fixtures only; no Windows APIs or probes."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'windows' / 'monitoring' / 'v080'))
import OnyxV080ProtectedLaunch as launch
import OnyxWindowsRuntimeAttestation as att
import OnyxV080ReleaseBinding as binding
import OnyxV080ReleaseProfile as profile

SID = 'S-1-5-21-101-202-303-404'
COMMIT = 'e' * 40


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


class ProtectedLaunchAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.config = self.root / launch.RELEASE_CONFIG
        self.config.parent.mkdir(parents=True, exist_ok=True)
        src = ROOT / 'windows' / 'monitoring' / profile.RELEASE_CONFIG_NAME
        self.config.write_bytes(src.read_bytes())
        hashes = {}
        for name in att.REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            content = ('file:' + name).encode('ascii')
            path.write_bytes(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
        self.document = dict(schema_version=1, source_commit=COMMIT,
                             approved_sid=SID,
                             config_sha256=hashlib.sha256(self.config.read_bytes()).hexdigest(),
                             file_sha256=hashes)

    def admitted(self, *, doc=None, raw=None, hash_override=None):
        raw = canon(doc if doc is not None else self.document) if raw is None else raw
        digest = hashlib.sha256(raw).hexdigest() if hash_override is None else hash_override
        return launch.prepare_reviewed_install(self.root, raw,
                                                pinned_sha256=digest, cycles=2)

    def test_approved_document_connects_to_actual_release_wiring(self):
        result = self.admitted()
        self.assertIsInstance(result.wiring, binding.ReleaseWiring)
        self.assertEqual(result.wiring.source_root, self.root)
        self.assertEqual(result.wiring.approved_sid, SID)
        self.assertEqual(result.wiring.cycles, 2)
        self.assertEqual(result.file_count, len(att.REQUIRED_FILES))
        calls = []
        def fake_bridge(policy, **kw):
            calls.append((policy, kw))
            return 'OFFLINE-ONLY'
        self.assertEqual(binding.run_explicitly_approved_api(
            result.wiring,
            build_authorizer=lambda **kwargs: lambda: True,
            run_bridge=fake_bridge), 'OFFLINE-ONLY')
        self.assertIsNot(calls[0][1]['probe'], binding.m1.run_once)
        from unittest.mock import patch
        with patch.object(binding.contained, 'run_protected_probe', return_value={'synthetic': True}) as isolated:
            self.assertEqual(calls[0][1]['probe']({'profile': 'release'}), {'synthetic': True})
            isolated.assert_called_once()
        self.assertEqual(calls[0][0].cycles, 2)

    def test_manifest_covers_new_runtime_scripts_and_imports(self):
        required = set(att.REQUIRED_FILES)
        for rel in (
            'windows/monitoring/v080/OnyxWindowsJobRunner.py',
            'windows/monitoring/v080/OnyxV080ReleaseBinding.py',
            'windows/monitoring/v080/OnyxV080ReleaseProfile.py',
            'windows/monitoring/v080/OnyxV080ProtectedLaunch.py',
            'windows/monitoring/OnyxMonitorConfig.py',
            'windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1',
            'windows/networking/Test-OnyxUsbIcsReadiness.ps1',
        ):
            self.assertIn(rel, required)
        self.assertEqual(len(required), len(att.REQUIRED_FILES))

    def test_changed_job_runner_refused(self):
        self.admitted()
        (self.root / 'windows/monitoring/v080/OnyxWindowsJobRunner.py').write_bytes(b'changed')
        with self.assertRaises(att.AttestationRefused):
            self.admitted()

    def test_changed_powershell_diagnostic_refused(self):
        self.admitted()
        (self.root / 'windows/networking/Test-OnyxUsbIcsReadiness.ps1').write_bytes(b'changed')
        with self.assertRaises(att.AttestationRefused):
            self.admitted()

    def test_changed_binding_refused(self):
        (self.root / 'windows/monitoring/v080/OnyxV080ReleaseBinding.py').write_bytes(b'changed')
        with self.assertRaises(att.AttestationRefused):
            self.admitted()

    def test_changed_config_refused(self):
        doc=copy.deepcopy(self.document)
        self.config.write_bytes(b'{}')
        with self.assertRaises(att.AttestationRefused):
            self.admitted(doc=doc)

    def test_deleted_dependency_refused(self):
        (self.root / att.REQUIRED_FILES[-1]).unlink()
        with self.assertRaises(att.AttestationRefused):
            self.admitted()

    def test_missing_manifest_dependency_refused(self):
        doc=copy.deepcopy(self.document)
        del doc['file_sha256'][att.REQUIRED_FILES[-1]]
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(doc=doc)

    def test_extra_manifest_dependency_refused(self):
        doc=copy.deepcopy(self.document)
        doc['file_sha256']['windows/monitoring/v080/unknown.py']='a'*64
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(doc=doc)

    def test_wrong_document_hash_refused(self):
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(hash_override='b'*64)

    def test_unpinned_document_refused(self):
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(hash_override=None if False else '')

    def test_duplicate_document_field_refused(self):
        raw=canon(self.document)
        dup=raw.replace(b'{', b'{"schema_version":1,', 1)
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(raw=dup)

    def test_noncanonical_doc_refused(self):
        raw=json.dumps(self.document,indent=2,sort_keys=True).encode('ascii')
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(raw=raw)

    def test_unknown_doc_field_refused(self):
        doc=copy.deepcopy(self.document)
        doc['grant_bytes']='not allowed'
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(doc=doc)

    def test_oversized_doc_refused(self):
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(raw=b'x'*(launch.MAX_APPROVAL_BYTES+1))

    def test_bad_sid_refused(self):
        doc=copy.deepcopy(self.document)
        doc['approved_sid']='env:USER'
        with self.assertRaises(launch.ProtectedLaunchRefused):
            self.admitted(doc=doc)

    def test_config_enforces_release_not_development(self):
        doc=copy.deepcopy(self.document)
        invalid=json.loads(self.config.read_bytes())
        invalid['profile']='development'
        self.config.write_bytes(json.dumps(invalid).encode())
        doc['config_sha256']=hashlib.sha256(self.config.read_bytes()).hexdigest()
        with self.assertRaises(profile.ReleaseProfileRefused):
            self.admitted(doc=doc)

    def test_root_symlink_refused(self):
        link=self.root.parent / (self.root.name+'-link')
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        raw=canon(self.document)
        with self.assertRaises(launch.ProtectedLaunchRefused):
            launch.prepare_reviewed_install(link, raw, pinned_sha256=hashlib.sha256(raw).hexdigest())

    def test_real_audit_is_hard_disabled_without_digest_pin(self):
        with self.assertRaises(launch.ProtectedLaunchRefused):
            launch.audit_pinned_install()

    def test_no_live_cli(self):
        self.assertEqual(launch.main(['--check-inert']),0)
        with self.assertRaises(SystemExit):
            launch.main(['--start'])
        with self.assertRaises(SystemExit):
            launch.main([])

    def test_default_runtime_admission_does_not_read_grant_or_run_probe(self):
        with patch.object(binding.m1, 'run_once', side_effect=AssertionError('live probe')):
            with patch.object(att.consent, 'read_windows_grant', side_effect=AssertionError('credential')):
                self.admitted()


if __name__=='__main__':
    unittest.main()
