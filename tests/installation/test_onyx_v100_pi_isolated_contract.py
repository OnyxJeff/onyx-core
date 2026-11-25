#!/usr/bin/env python3
"""Offline contract tests, deliberately portable across Windows and POSIX."""
import copy
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
import io

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/installation/pi'))
import onyx_v100_pi_isolated_contract as mod
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_onyx_v100_pi_native_safeguards as prior

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='OnyxV100-S7C-')
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / 'config.json'
        self.cfg = json.loads(prior.BASE_CONFIG.read_text(encoding='utf-8'))
        self.cfg['receiver']['source'] = 'SQUALL'
        self.config.write_text(json.dumps(self.cfg), encoding='utf-8')
        self.evidence = copy.deepcopy(prior.EVIDENCE)
    def build(self):
        return mod.build_candidates(prior.BUNDLE, self.config, self.evidence)
    def report(self):
        return self.build()[2]
    def test_deterministic(self):
        self.assertEqual(self.build(), self.build())
    def test_accepted_previous_hashes(self):
        self.assertEqual(self.report()['old_fingerprints'], mod.OLD_HASHES)
    def test_new_config_root_is_sibling(self):
        r = self.report()
        self.assertEqual(r['config_root'], '/etc/onyxcore-v100')
        self.assertEqual(PurePosixPath(r['config_root']).parent, PurePosixPath('/etc'))
        self.assertFalse(r['config_root'].startswith('/etc/onyxcore/'))
    def test_no_native_readiness_claim(self):
        r = self.report()
        for k in ('native_publication_verified','new_path_absence_verified','new_service_identity_verified','installation_authorized','numeric_uid_gid_assigned'):
            self.assertIs(r[k], False)
        self.assertEqual(r['status'], 'DESIGN_READY_NATIVE_PREPARATION_REQUIRED')
    def test_no_side_effect_claims(self):
        r = self.report()
        for k in ('writes_to_pi','service_changes','credential_read_or_enrollment','activation','installer_invoked'):
            self.assertIs(r[k], False)
    def test_dedicated_identity(self):
        self.assertEqual(self.report()['service_identity'], 'onyxcore-v100')
        self.assertNotEqual(self.report()['service_identity'], 'onyxcore')
    def test_exact_external_inventory(self):
        _, external, _ = self.build()
        self.assertEqual(set(external), {'pi-armv6.config.json','config-receipt.json'})
    def test_release_inventory_and_unchanged_runtime(self):
        files, _, r = self.build()
        old, _ = mod.s3c.expected_files(prior.BUNDLE, self.config)
        self.assertEqual(len(files), 15)
        self.assertEqual(set(files), set(old) | {mod.s3c.RECEIPT})
        self.assertEqual([k for k in old if old[k] != files[k]], [mod.s3c.UNIT_CANDIDATE])
        self.assertEqual(r['release_file_count'],15)
    def test_unit_static_and_gated(self):
        files, _, _ = self.build()
        unit = files[mod.s3c.UNIT_CANDIDATE].decode('ascii')
        self.assertNotIn('[Install]',unit)
        self.assertNotIn('WantedBy=',unit)
        for line in ('RefuseManualStart=yes','ConditionPathExists='+mod.MARKER,'User=onyxcore-v100','Group=onyxcore-v100','EnvironmentFile='+mod.CREDENTIAL,'ProtectSystem=strict','NoNewPrivileges=true','InaccessiblePaths=/etc/onyxcore /var/lib/onyxcore','ReadWritePaths='+mod.STATE):
            self.assertIn(line,unit.splitlines())
        self.assertIn('--config '+mod.CONFIG+' --installed-root '+mod.RELEASE,unit)
    def test_release_receipt_inventory(self):
        files, _, r = self.build()
        receipt = json.loads(files[mod.s3c.RECEIPT])
        self.assertEqual(receipt['operation'],'PI_V100_ISOLATED_CODE_CANDIDATE')
        self.assertEqual({row['path'] for row in receipt['files']},set(files)-{mod.s3c.RECEIPT})
        self.assertEqual(len(receipt['files']),14)
        for row in receipt['files']:
            self.assertEqual(row['sha256'],mod.sha(files[row['path']]))
            self.assertEqual(row['size'],len(files[row['path']]))
        self.assertEqual(r['release_receipt_sha256'],mod.sha(files[mod.s3c.RECEIPT]))
    def test_config_receipt_is_candidate(self):
        _, ext, r = self.build()
        receipt = json.loads(ext['config-receipt.json'])
        self.assertEqual(receipt['config_target'],mod.CONFIG)
        self.assertEqual(receipt['config_sha256'],mod.sha(ext['pi-armv6.config.json']))
        self.assertEqual(receipt['service_identity'],mod.IDENTITY)
        self.assertFalse(receipt['native_publication_verified'])
        self.assertEqual(r['config_receipt_sha256'],mod.sha(ext['config-receipt.json']))
    def test_config_schema_and_bytes_unchanged(self):
        _, ext, _ = self.build()
        old, _, _, _ = mod.s3d.proposed(prior.BUNDLE,self.config)
        self.assertEqual(ext['pi-armv6.config.json'],old)
    def test_credential_root_only(self):
        p = self.report()['permission_plan']
        self.assertEqual(p['future_credential_file'],['root','root','0600'])
        self.assertEqual(p['future_activation_marker'],['root','root','0600'])
    def test_permissions_are_separate(self):
        p = self.report()['permission_plan']
        for key in ('release_directory','config_directory'):
            self.assertEqual(p[key],['root','onyxcore-v100','0750'])
        for key in ('release_file','config_file'):
            self.assertEqual(p[key],['root','onyxcore-v100','0640'])
        self.assertEqual(p['state_directory'],['onyxcore-v100','onyxcore-v100','0700'])
    def test_legacy_parent_not_changed(self):
        self.assertEqual(self.report()['legacy_config_policy'],'preserve_root_root_0700')
        self.assertEqual(self.evidence,prior.EVIDENCE)
    def test_other_blocker_refused(self):
        self.evidence['paths']['release_target']='present'
        with self.assertRaises(mod.ContractRefused): self.build()
    def test_changed_source_refused(self):
        self.cfg['receiver']['source']='NOT-SQUALL'
        self.config.write_text(json.dumps(self.cfg),encoding='utf-8')
        with self.assertRaises(ValueError): self.build()
    def test_changed_snapshot_refused(self):
        self.cfg['storage']['snapshot_name']='another.json'
        self.config.write_text(json.dumps(self.cfg),encoding='utf-8')
        with self.assertRaises(ValueError): self.build()
    def test_wrong_unit_refused(self):
        with self.assertRaises(mod.ContractRefused): mod.revised_unit(b'User=onyxcore\n')
    def test_legacy_path_override_refused(self):
        with patch.object(mod,'CONFIG_ROOT','/etc/onyxcore'):
            with self.assertRaises(mod.ContractRefused): self.build()
    def test_windows_host_posix_paths(self):
        r = self.report()
        for key in ('config_root','release_target','state_target','unit_target','activation_marker'):
            self.assertEqual(PureWindowsPath(r[key]).as_posix(),r[key])
    def test_old_native_publishers_not_invoked(self):
        with patch.object(mod.s3d,'native_prepare',side_effect=AssertionError('native call')):
            self.build()
    def test_cli_only_preview(self):
        ev = Path(self.tmp.name)/'ev.json'
        ev.write_text(json.dumps(self.evidence),encoding='utf-8')
        args = ['--bundle',str(prior.BUNDLE),'--config',str(self.config),'--evidence',str(ev)]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(mod.main(args),0)
        self.assertFalse(json.loads(out.getvalue())['installation_authorized'])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            mod.main(args+['--install'])
    def test_pending_native_identity_and_port(self):
        p = self.report()['pending']
        self.assertIn('dedicated_account_no_legacy_group_memberships',p)
        self.assertIn('legacy_port_8765_handover_review',p)

if __name__ == '__main__': unittest.main()
