"""Synthetic activation tests; no native command, socket, or credential access."""
import contextlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/installation/common'))
import onyx_v100_release_pi_activation as a
from test_onyx_v100_release_install import WIN, PI

class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.data,self.report=a.install.inventory({},PI,'pi-armv6','a'*64,peer=WIN)
        self.unit=a.install.PI_UNIT
        self.absent={'LoadState':'not-found','ActiveState':'inactive','SubState':'dead','UnitFileState':'',
                     'FragmentPath':'','DropInPaths':'','NeedDaemonReload':'no','User':'','Group':'',
                     'NoNewPrivileges':'no','ProtectSystem':'no','MainPID':'0'}
        self.owned=dict(self.absent,LoadState='loaded',FragmentPath=str(a.UNIT_DIR/self.unit),
                        User='onyxcore-v100',Group='onyxcore-v100',NoNewPrivileges='yes',
                        ProtectSystem='strict',UnitFileState='disabled')
        self.active=dict(self.owned,ActiveState='active',SubState='running',MainPID='621',UnitFileState='enabled')
        self.mock=MagicMock()
        self.stack=contextlib.ExitStack(); self.addCleanup(self.stack.close)
        for name in ('identity','checked_dirs','service','bind_address','write_new','read_exact','ctl','health'):
            self.stack.enter_context(patch.object(a,name,getattr(self.mock,name)))
        for name in ('posix_absent','rename_noreplace'):
            self.stack.enter_context(patch.object(a.native,name,getattr(self.mock,name)))
        self.stack.enter_context(patch.object(a.os,'fsync',self.mock.fsync))
        self.stack.enter_context(patch.object(a.socket,'socket',self.mock.socket))
        self.mock.identity.return_value=(100,100)
        self.mock.checked_dirs.side_effect=lambda *args,**kw: contextlib.nullcontext((11,12))
        self.mock.bind_address.return_value='192.168.137.167'

    def test_activation_order(self):
        self.mock.service.side_effect=[self.absent,self.absent,self.owned,self.owned,self.active]
        self.assertEqual(a.activate(self.data,self.report,PI,WIN),'PI_ACTIVATED')
        names=[c[0] for c in self.mock.mock_calls]
        self.assertLess(names.index('write_new'),names.index('ctl'))
        self.assertEqual(self.mock.write_new.call_args_list[0].args[1],a.INTENT)
        self.assertEqual(self.mock.write_new.call_args_list[1].args[1],self.unit)
        self.assertEqual([c.args for c in self.mock.ctl.call_args_list],[('daemon-reload',),('start',self.unit),('enable',self.unit)])

    def test_conflict_refused_before_write(self):
        self.mock.service.return_value=self.active
        with self.assertRaises(ValueError): a.activate(self.data,self.report,PI,WIN)
        self.mock.write_new.assert_not_called(); self.mock.ctl.assert_not_called()

    def test_port_conflict_refused_before_write(self):
        self.mock.service.return_value=self.absent
        self.mock.socket.return_value.__enter__.return_value.bind.side_effect=OSError('occupied')
        with self.assertRaises(OSError): a.activate(self.data,self.report,PI,WIN)
        self.mock.write_new.assert_not_called(); self.mock.ctl.assert_not_called()

    def test_health_failure_leaves_intent_no_enable(self):
        self.mock.service.side_effect=[self.absent,self.absent,self.owned]
        self.mock.health.side_effect=ValueError('health failed')
        with self.assertRaises(ValueError): a.activate(self.data,self.report,PI,WIN)
        self.assertEqual(self.mock.write_new.call_count,2)
        self.assertEqual([c.args for c in self.mock.ctl.call_args_list],[('daemon-reload',),('start',self.unit)])

    def test_rollback_order_and_preservation(self):
        self.mock.service.side_effect=[self.active,dict(self.owned,UnitFileState='enabled'),self.owned,self.absent]
        self.assertIn('ROLLED_BACK',a.rollback(self.data,self.report))
        self.assertEqual([c.args for c in self.mock.ctl.call_args_list],[('stop',self.unit),('disable',self.unit),('daemon-reload',)])
        self.mock.rename_noreplace.assert_called_once_with(12,self.unit,self.unit+'.rollback')
        self.mock.write_new.assert_not_called()
        self.assertEqual(self.mock.read_exact.call_args_list[0].args[1],a.INTENT)

    def test_rollback_wrong_intent_no_stop(self):
        self.mock.read_exact.side_effect=ValueError('changed receipt')
        with self.assertRaises(ValueError): a.rollback(self.data,self.report)
        self.mock.ctl.assert_not_called(); self.mock.rename_noreplace.assert_not_called()

    def test_rollback_collision_no_stop(self):
        self.mock.posix_absent.side_effect=ValueError('collision')
        with self.assertRaises(ValueError): a.rollback(self.data,self.report)
        self.mock.ctl.assert_not_called()

    def test_rollback_dropin_no_stop(self):
        self.mock.service.return_value=dict(self.active,DropInPaths='/etc/systemd/system/x.conf')
        with self.assertRaises(ValueError): a.rollback(self.data,self.report)
        self.mock.ctl.assert_not_called()

    def test_rollback_failed_stop_no_disable_or_rename(self):
        self.mock.service.return_value=self.active
        with self.assertRaises(ValueError): a.rollback(self.data,self.report)
        self.mock.ctl.assert_called_once_with('stop',self.unit)
        self.mock.rename_noreplace.assert_not_called()

    def test_intent_bound_to_plan(self):
        self.assertNotEqual(a.intent(self.report),a.intent(dict(self.report,plan_sha256='b'*64)))

    def test_approval_refused_before_archive_read(self):
        args=['activate','--archive','missing.zip','--sha256','a'*64,'--config','missing.json',
              '--peer-config','missing-peer.json','--approved-plan','b'*64]
        with patch.object(a.native,'read_regular') as read:
            self.assertEqual(a.main(args),2); read.assert_not_called()

class FileTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='linux','POSIX fixture only')
    def test_exclusive_unit_write_and_exact_read(self):
        with tempfile.TemporaryDirectory() as temp:
            fd=os.open(temp,a.native.dirflags())
            try:
                a.write_new(fd,'unit',b'test',os.getuid(),os.getgid(),0o600)
                a.read_exact(fd,'unit',b'test',os.getuid(),os.getgid(),0o600)
                with self.assertRaises(ValueError): a.write_new(fd,'unit',b'other',os.getuid(),os.getgid(),0o600)
                with self.assertRaises(ValueError): a.read_exact(fd,'unit',b'other',os.getuid(),os.getgid(),0o600)
                self.assertEqual((Path(temp)/'unit').read_bytes(),b'test')
            finally: os.close(fd)

    @unittest.skipUnless(sys.platform=='linux' and os.geteuid()==0,'Root POSIX temporary fixture only')
    def test_prepare_creates_exclusive_protected_state_and_refuses_repeat(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            root=Path(temp); runtime=root/'release'; runtime.mkdir(); units=root/'units'; units.mkdir()
            config=root/'config'; state=root/'state'; token='x'*48
            data,report=a.install.inventory({},PI,'pi-armv6','a'*64,peer=WIN)
            absent={'LoadState':'not-found','ActiveState':'inactive','FragmentPath':'','DropInPaths':'','MainPID':'0'}
            for key,value in {'PI_ROOT':str(runtime),'PI_CONFIG':str(config),'PI_STATE':str(state)}.items():
                stack.enter_context(patch.object(a.install,key,value))
            stack.enter_context(patch.object(a,'UNIT_DIR',units))
            stack.enter_context(patch.object(a,'identity',return_value=(os.getuid(),os.getgid())))
            stack.enter_context(patch.object(a,'service',return_value=absent))
            stack.enter_context(patch.object(a.native,'posix_parent',side_effect=lambda p,gid:os.open(p,a.native.dirflags())))
            stack.enter_context(patch.object(a.native,'audit_posix'))
            stack.enter_context(patch.object(a.sys.stdin,'isatty',return_value=True))
            prompt=stack.enter_context(patch.object(a.getpass,'getpass',side_effect=[token,'y'*48,token,token]))
            with self.assertRaisesRegex(ValueError,'Matching URL-safe token'):
                a.prepare(data,report)
            self.assertFalse(config.exists()); self.assertFalse(state.exists())
            self.assertEqual(a.prepare(data,report),'PI_STATE_AND_CREDENTIAL_PREPARED')
            self.assertEqual((config/'receiver.env').read_bytes(),('ONYXCORE_TOKEN='+token+'\n').encode('ascii'))
            self.assertEqual((config/'receiver.env').stat().st_mode&0o777,0o600)
            self.assertEqual(config.stat().st_mode&0o777,0o750)
            self.assertEqual(state.stat().st_mode&0o777,0o700)
            self.assertEqual(list(state.iterdir()),[])
            with self.assertRaises(ValueError): a.prepare(data,report)
            self.assertEqual(prompt.call_count,4)

if __name__=='__main__': unittest.main()
