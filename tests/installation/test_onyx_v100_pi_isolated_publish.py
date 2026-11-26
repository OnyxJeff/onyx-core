#!/usr/bin/env python3
"""Focused portable plan and real Linux filesystem regression tests."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack, redirect_stderr
from types import SimpleNamespace
import io

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/installation/pi'))
import onyx_v100_pi_isolated_publish as mod
import onyx_v100_pi_isolated_contract as contract
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_onyx_v100_pi_native_safeguards as prior

class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='Onyx-S7D-'); self.addCleanup(self.tmp.cleanup)
        self.config=Path(self.tmp.name)/'config.json'
        self.cfg=json.loads(prior.BASE_CONFIG.read_text()); self.cfg['receiver']['source']='SQUALL'
        self.config.write_text(json.dumps(self.cfg))
    def build(self): return mod.candidates(prior.BUNDLE,self.config)
    def test_accepted_contract_runtime_and_unit_preserved(self):
        old=contract.build_candidates(prior.BUNDLE,self.config,copy.deepcopy(prior.EVIDENCE))
        release,ext,state=self.build()
        self.assertEqual({k:v for k,v in release.items() if k!=mod.RECEIPT}, {k:v for k,v in old[0].items() if k!=mod.RECEIPT})
        self.assertEqual(ext['pi-armv6.config.json'],old[1]['pi-armv6.config.json'])
        self.assertEqual(state,{})
        self.assertEqual(mod.sha(release[mod.UNIT_CANDIDATE]),old[2]['unit_candidate_sha256'])
    def test_other_compatible_host(self):
        self.cfg['receiver']['source']='OTHER-PC'; self.cfg['receiver']['ipv4_subnet']='10.12.194.0/28'
        self.config.write_text(json.dumps(self.cfg)); release,ext,state=self.build()
        self.assertEqual(json.loads(ext['pi-armv6.config.json'])['receiver']['source'],'OTHER-PC')
        self.assertEqual(len(release),15)
    def test_stable_plan_and_inactive_receipts(self):
        p=self.build(); r=mod.plan(p); self.assertEqual(r,mod.plan(self.build()))
        self.assertEqual(r['targets'],list(mod.TARGETS)); self.assertEqual(r['file_counts'],[15,2,0])
        for k in ('activation_performed','service_registered','credentials_enrolled'): self.assertFalse(r[k])
        receipt=json.loads(p[0][mod.RECEIPT]); self.assertEqual({x['path'] for x in receipt['files']},set(p[0])-{mod.RECEIPT})
        for row in receipt['files']: self.assertEqual(row['sha256'],mod.sha(p[0][row['path']]))
    def test_reject_legacy_state_and_wrong_bundle(self):
        self.cfg['storage']['state_dir']='/var/lib/onyxcore'; self.config.write_text(json.dumps(self.cfg))
        with self.assertRaises(ValueError): self.build()
        bad=Path(self.tmp.name)/'bad.zip'; bad.write_bytes(b'bad')
        with self.assertRaises(ValueError): mod.candidates(bad,self.config)
    def test_incomplete_approval_never_calls_native(self):
        with patch.object(mod,'native_publish') as call, redirect_stderr(io.StringIO()):
            self.assertEqual(mod.main(['--bundle',str(prior.BUNDLE),'--config',str(self.config),'--install-inactive']),2)
            self.assertEqual(mod.main(['--bundle',str(prior.BUNDLE),'--config',str(self.config),'--approve-plan-sha256',mod.plan(self.build())['plan_sha256']]),2)
            call.assert_not_called()
    def test_native_gate_refuses_non_armv6(self):
        with patch.object(mod.platform,'machine',return_value='x86_64'),self.assertRaises(mod.Refused):
            mod.native_guard()
    def test_unsafe_relative_names(self):
        for rel in ('/absolute','../escape','a/../b','a\\b','C:bad','a//b'):
            with self.subTest(rel=rel),self.assertRaises(mod.Refused): mod.safe_parts(rel)

@unittest.skipUnless(sys.platform=='linux','native Linux directory descriptors and renameat2 required')
class LinuxTests(unittest.TestCase):
    build=PlanTests.build
    # Restrict native fixture ownership to own uid/gid unless root; when root use
    # unused numeric IDs to prove separation, not real system account creation.
    def setUp(self):
        PlanTests.setUp(self); self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.owner=os.geteuid(); self.uid=60001 if self.owner==0 else self.owner
        self.gid=60002 if self.owner==0 else os.getegid()
        self.parents=[]; self.fds=[]
        for i in range(3):
            p=Path(self.tmp.name)/str(i); p.mkdir(mode=0o755); self.parents.append(p)
            fd=os.open(p,mod.DIR); self.fds.append(fd); self.stack.callback(os.close,fd)
        self.payload=self.build(); self.digest=mod.plan(self.payload)['plan_sha256']
    def go(self,digest=None):
        return mod.publish(self.fds,self.payload,owner=self.owner,uid=self.uid,gid=self.gid,approved_plan=digest or self.digest)
    def test_native_full_install(self):
        result=self.go(); self.assertEqual(result['files'],17)
        for i,p in enumerate(self.parents):
            target=p/mod.NAMES[i]; self.assertEqual(target.stat().st_uid,self.uid if i==2 else self.owner)
            self.assertEqual(target.stat().st_gid,self.gid)
            self.assertEqual(target.stat().st_mode&0o777,0o700 if i==2 else 0o750)
            self.assertEqual({x.relative_to(target).as_posix():x.read_bytes() for x in target.rglob('*') if x.is_file()},self.payload[i])
        with self.assertRaises(mod.Refused): self.go()
    def test_existing_target_no_write(self):
        target=self.parents[1]/mod.NAMES[1]; target.mkdir(); witness=target/'witness'; witness.write_bytes(b'keep')
        with self.assertRaises(mod.Refused): self.go()
        self.assertEqual(witness.read_bytes(),b'keep'); self.assertFalse(list(self.parents[0].iterdir()))
    def test_symlink_collision(self):
        target=self.parents[0]/mod.NAMES[0]; target.symlink_to('/nonexistent')
        with self.assertRaises(mod.Refused): self.go()
        self.assertTrue(target.is_symlink())
    def test_wrong_digest_and_abandoned_stage(self):
        with self.assertRaises(mod.Refused): self.go('0'*64)
        self.assertFalse(list(self.parents[0].iterdir()))
        (self.parents[0]/(mod.PREFIX+'old')).mkdir()
        with self.assertRaises(mod.Refused): self.go()
    def test_atomic_race_and_partial_evidence(self):
        real=mod.rename_noreplace
        def race(fd,old,new):
            if fd==self.fds[1]:
                os.mkdir(new,0o700,dir_fd=fd)
                (self.parents[1]/new/'witness').write_bytes(b'keep')
            return real(fd,old,new)
        with patch.object(mod,'rename_noreplace',side_effect=race),self.assertRaisesRegex(mod.Refused,'INCOMPLETE'):
            self.go()
        self.assertTrue((self.parents[0]/mod.NAMES[0]).is_dir())
        self.assertEqual((self.parents[1]/mod.NAMES[1]/'witness').read_bytes(),b'keep')
        self.assertTrue(any(p.name.startswith(mod.PREFIX) for p in self.parents[2].iterdir()))
        with self.assertRaises(mod.Refused): self.go()
    def test_unsafe_parent(self):
        self.parents[0].chmod(0o777)
        with self.assertRaises(mod.Refused): self.go()
        self.assertFalse(list(self.parents[0].iterdir()))
    def test_identity_requires_exclusive_nonlogin_account(self):
        import pwd,grp
        user=SimpleNamespace(pw_name=contract.IDENTITY,pw_uid=60001,pw_gid=60002,
                             pw_dir='/nonexistent',pw_shell='/usr/sbin/nologin')
        group=SimpleNamespace(gr_name=contract.IDENTITY,gr_gid=60002,gr_mem=[])
        with patch.object(pwd,'getpwnam',return_value=user),patch.object(grp,'getgrnam',return_value=group), \
             patch.object(pwd,'getpwall',return_value=[user]),patch.object(grp,'getgrall',return_value=[group]), \
             patch.object(os,'getgrouplist',return_value=[60002]) as groups:
            self.assertEqual(mod.identity(),(60001,60002))
            groups.return_value=[60002,985]
            with self.assertRaises(mod.Refused): mod.identity()
            groups.return_value=[60002]; user.pw_shell='/bin/bash'
            with self.assertRaises(mod.Refused): mod.identity()
    def test_unit_presence_fails_closed(self):
        result=SimpleNamespace(returncode=0,stdout='LoadState=not-found\nActiveState=inactive\n')
        with patch.object(mod,'open_parent',side_effect=lambda *a: os.dup(self.fds[0])), \
             patch.object(mod.subprocess,'run',return_value=result):
            mod.check_unit_absent(self.gid)
            result.stdout='LoadState=loaded\nActiveState=inactive\n'
            with self.assertRaises(mod.Refused): mod.check_unit_absent(self.gid)
    def test_audit_tamper(self):
        self.go(); target=self.parents[1]/mod.NAMES[1]; (target/'pi-armv6.config.json').write_bytes(b'tamper')
        fd=os.open(target,mod.DIR)
        try:
            with self.assertRaises(mod.Refused): mod.audit_tree(fd,self.payload[1],self.owner,self.gid,0o750)
        finally: os.close(fd)

if __name__=='__main__': unittest.main()
