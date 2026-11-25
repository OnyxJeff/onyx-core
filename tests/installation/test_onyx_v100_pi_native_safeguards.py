#!/usr/bin/env python3
"""M2-S7B offline source/receipt/collision/permission gate regression tests."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/installation/pi'))
import onyx_v100_pi_native_safeguards as mod
import onyx_v100_pi_config_state as s3d
import onyx_v100_pi_code_publish as s3c

BUNDLE = Path(os.environ['ONYX_V100_BUNDLE'])
BASE_CONFIG = ROOT / 'docs/v1.0.0/examples/pi-armv6.system.config.example.json'
EVIDENCE = {
 'hostname':'svr-onyxcore', 'architecture':'armv6l', 'python_version':'3.13.5',
 'os_codename':'trixie', 'usb0_ipv4':['10.12.194.1/28','192.168.137.167/24'],
 'service_uid':999,'service_gid':985,'legacy_receiver_state':'active','legacy_listen_ports':[8765],
 'paths':{
  'release_parent':{'kind':'dir','uid':0,'gid':0,'mode':'0755'},
  'configuration_parent':{'kind':'dir','uid':0,'gid':0,'mode':'0700'},
  'legacy_state':{'kind':'dir','uid':999,'gid':985,'mode':'0750'},
  'release_target':'absent','configuration_target':'absent',
  'v1_state_target':'absent','v1_unit_target':'absent','v1_activation_marker':'absent',
 }
}

class SafeguardsTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if hashlib.sha256(BUNDLE.read_bytes()).hexdigest()!=mod.BUNDLE_HASH:
   raise AssertionError('pinned runtime candidate mismatch')
  cls.tmp=tempfile.TemporaryDirectory(prefix='OnyxV100-S7B-')
  cls.config=Path(cls.tmp.name)/'squall-pi.config.json'
  cfg=json.loads(BASE_CONFIG.read_text(encoding='utf-8'))
  cfg['receiver']['source']='SQUALL'
  cls.config.write_text(json.dumps(cfg,sort_keys=True),encoding='utf-8')

 @classmethod
 def tearDownClass(cls):
  cls.tmp.cleanup()

 def review(self,evidence=None,config=None,bundle=None):
  return mod.snapshot_review(bundle or BUNDLE, config or self.config,
                             copy.deepcopy(EVIDENCE if evidence is None else evidence))

 def test_s7a_privileged_path_absences_are_explicit_not_inferred(self):
  result=self.review()
  self.assertEqual(result['native_readiness'],'BLOCKED')
  self.assertEqual(result['blockers'],['s3d_service_cannot_traverse_protected_config_parent'])

 def test_offline_output_has_no_install_action(self):
  x=self.review()
  for key in ('writes_to_pi','service_changes','credential_read_or_enrollment',
              'activation','filesystem_publication','installer_invoked'):
   self.assertIs(x[key],False,key)
  self.assertTrue(x['evidence_not_live_reattested'])
  self.assertEqual(x['evidence_source'],'operator_reported_M2_S7A_plus_root_metadata_check')

 def test_expected_runtime_count_and_exact_legacy_isolation(self):
  x=self.review()
  self.assertEqual(x['release_file_count'],15)
  self.assertEqual(x['release_target'],'/opt/onyxcore/v1.0.0')
  self.assertEqual(x['config_target'],'/etc/onyxcore/v1.0.0/pi-armv6.config.json')
  self.assertEqual(x['state_target'],'/var/lib/onyxcore-v100')
  self.assertEqual(x['source_identity'],'SQUALL')

 def test_fixed_release_path_is_host_independent(self):
  baseline=self.review()
  for parent in (PurePosixPath('/opt/onyxcore'), PureWindowsPath('/opt/onyxcore')):
   with self.subTest(parent=parent), patch.object(mod,'PARENT',parent):
    self.assertEqual(self.review(),baseline)

 def test_changed_fixed_release_path_refused_on_both_path_flavors(self):
  for flavor in (PurePosixPath,PureWindowsPath):
   for parent in ('/opt/other','opt/onyxcore','/opt/onyxcore/../onyxcore'):
    with self.subTest(flavor=flavor,parent=parent), patch.object(mod,'PARENT',flavor(parent)):
     with self.assertRaisesRegex(mod.SafeguardsRefused,'reviewed fixed paths changed'):
      self.review()
  for parent in (PureWindowsPath('C:/opt/onyxcore'),PureWindowsPath('//server/share/opt/onyxcore')):
   with self.subTest(parent=parent), patch.object(mod,'PARENT',parent):
    with self.assertRaisesRegex(mod.SafeguardsRefused,'reviewed fixed paths changed'):
     self.review()

 def test_release_and_config_receipts_reproducible(self):
  a=self.review(); b=self.review()
  self.assertEqual(a,b)
  files,cfg=s3c.expected_files(BUNDLE,self.config)
  config_bytes,receipt,cfg2,selected=s3d.proposed(BUNDLE,self.config)
  self.assertEqual(files,selected)
  self.assertEqual(cfg,cfg2)
  self.assertEqual(a['release_receipt_sha256'],hashlib.sha256(s3c.receipt_bytes(files)).hexdigest())
  self.assertEqual(a['config_receipt_sha256'],hashlib.sha256(receipt).hexdigest())
  self.assertEqual(a['config_sha256'],hashlib.sha256(config_bytes).hexdigest())
  self.assertEqual(a['unit_candidate_sha256'],hashlib.sha256(files[s3c.UNIT_CANDIDATE]).hexdigest())

 def test_s3d_existing_parent_is_safe_but_untraversable(self):
  p=EVIDENCE['paths']['configuration_parent']
  mode=int(p['mode'],8)
  self.assertEqual((p['uid'],p['gid']),(0,0))
  self.assertFalse(mode & 0o022)
  self.assertFalse(mode & 0o001)
  self.assertFalse(p['gid']==985 and mode & 0o010)
  x=self.review()
  self.assertIn('s3d_service_cannot_traverse_protected_config_parent',x['blockers'])

 def test_simulated_traversable_parent_does_not_authorize_install(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['configuration_parent']={'kind':'dir','uid':0,'gid':985,'mode':'0710'}
  r=self.review(sample)
  self.assertEqual(r['native_readiness'],'REVIEW_ONLY')
  self.assertFalse(r['filesystem_publication'])
  self.assertIn('actual_pi_installation_not_authorized',r['pending'])

 def test_unknown_config_target_fails_closed(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['configuration_target']='unknown'
  self.assertIn('v1_target_not_proven_absent_configuration_target',self.review(sample)['blockers'])

 def test_activation_marker_existing_fails_closed(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['v1_activation_marker']='present'
  self.assertIn('v1_target_not_proven_absent_v1_activation_marker',self.review(sample)['blockers'])

 def test_v1_state_collision_fails_closed(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['v1_state_target']='present'
  self.assertIn('v1_target_not_proven_absent_v1_state_target',self.review(sample)['blockers'])

 def test_release_symlink_fails_closed(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['release_target']='redirected'
  self.assertIn('v1_target_not_proven_absent_release_target',self.review(sample)['blockers'])

 def test_wrong_host_and_service_id_refused(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['architecture']='aarch64';sample['service_uid']=0
  r=self.review(sample)
  self.assertIn('s7a_host_arch_python_os_or_usb_not_verified',r['blockers'])
  self.assertIn('unexpected_service_identity',r['blockers'])

 def test_modified_usb_refused(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['usb0_ipv4']=['10.12.194.1/28']
  self.assertIn('s7a_host_arch_python_os_or_usb_not_verified',self.review(sample)['blockers'])

 def test_legacy_state_changed_requires_review(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['legacy_state']['mode']='0777'
  self.assertIn('legacy_state_metadata_changed',self.review(sample)['blockers'])

 def test_invalid_parent_fails(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['release_parent']['mode']='0777'
  self.assertIn('release_parent_permissions_require_review',self.review(sample)['blockers'])

 def test_unknown_parent_refused(self):
  sample=copy.deepcopy(EVIDENCE)
  sample['paths']['configuration_parent']='unknown'
  self.assertIn('configuration_parent_metadata_unknown',self.review(sample)['blockers'])

 def test_wrong_path_evidence_inventory_refused(self):
  sample=copy.deepcopy(EVIDENCE)
  del sample['paths']['release_target']
  with self.assertRaisesRegex(mod.SafeguardsRefused,'inventory'):
   self.review(sample)

 def test_config_example_mywindowspc_refused(self):
  with self.assertRaisesRegex(mod.SafeguardsRefused,'SQUALL'):
   self.review(config=BASE_CONFIG)

 def test_wrong_source_in_config_refused(self):
  cfg=json.loads(self.config.read_text())
  cfg['receiver']['source']='AnotherMachine'
  path=Path(self.tmp.name)/'wrong-source.json'
  path.write_text(json.dumps(cfg))
  with self.assertRaisesRegex(mod.SafeguardsRefused,'SQUALL'):
   self.review(config=path)

 def test_legacy_state_config_refused(self):
  cfg=json.loads(self.config.read_text())
  cfg['storage']['state_dir']='/var/lib/onyxcore'
  path=Path(self.tmp.name)/'legacy-state.json'
  path.write_text(json.dumps(cfg))
  with self.assertRaises(ValueError):
   self.review(config=path)

 def test_modified_bundle_refused(self):
  path=Path(self.tmp.name)/'tampered-bundle.zip'
  path.write_bytes(BUNDLE.read_bytes()+b'tamper')
  with self.assertRaisesRegex(mod.SafeguardsRefused,'SHA256'):
   self.review(bundle=path)

 def test_missing_evidence_fields_no_false_ready(self):
  sample=copy.deepcopy(EVIDENCE)
  del sample['service_gid']
  r=self.review(sample)
  self.assertEqual(r['native_readiness'],'BLOCKED')
  self.assertIn('unexpected_service_identity',r['blockers'])

 def test_report_warns_legacy_port_and_nonatomic_publication(self):
  r=self.review()
  self.assertIn('legacy_receiver_occupies_port_8765_future_activation_requires_handover',r['pending'])
  self.assertIn('two_directory_nonatomic_publication_requires_incomplete_state_review',r['pending'])
  self.assertEqual(r['rollback_policy'],'stop_preserve_partial_state_manual_reconciliation')

 def test_no_install_cli_flag(self):
  with tempfile.TemporaryDirectory() as tmp:
   evidence=Path(tmp)/'evidence.json'
   evidence.write_text(json.dumps(EVIDENCE))
   with redirect_stderr(io.StringIO()):
    with self.assertRaises(SystemExit) as ctx:
     mod.main(['--bundle',str(BUNDLE),'--config',str(self.config),
               '--evidence',str(evidence),'--install'])
   self.assertNotEqual(ctx.exception.code,0)

 def test_cli_prints_blocked_without_pi_access(self):
  with tempfile.TemporaryDirectory() as tmp:
   evidence=Path(tmp)/'evidence.json'
   evidence.write_text(json.dumps(EVIDENCE))
   with redirect_stdout(io.StringIO()) as output:
    result=mod.main(['--bundle',str(BUNDLE),'--config',str(self.config),'--evidence',str(evidence)])
   self.assertEqual(result,0)
   self.assertEqual(json.loads(output.getvalue())['native_readiness'],'BLOCKED')

 @unittest.skipUnless(os.name == 'posix', 'POSIX permission fixture')
 def test_s3d_provision_refuses_0700_config_parent(self):
  # Mirrors actual S3D implementation: verify a root:root 0700 configuration
  # parent cannot be traversed by gid=985, even though it is root-secure.
  import tempfile
  with tempfile.TemporaryDirectory() as root:
   d=Path(root)/'configparent'; d.mkdir()
   fd=os.open(d,os.O_RDONLY)
   try:
    os.chmod(d,0o700)
    with self.assertRaisesRegex(s3d.ProvisionRefused,'cannot traverse'):
     s3d._service_can_traverse(fd,985)
   finally: os.close(fd)

if __name__=='__main__':
 unittest.main(verbosity=2)
