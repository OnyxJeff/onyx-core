"""Offline M5-S2C tests. No Windows task, Pi service or live application access."""
import importlib.util
import json
import os
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
p=load('publisher',ROOT/'tools/installation/common/onyx_v100_m5_publish.py')
c=load('candidate',ROOT/'tools/installation/common/onyx_v100_m5_candidate.py')
class PublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw={r:c.zip_bytes(r,{n:(ROOT/n).read_bytes().replace(b'\r\n',b'\n') for n in c.ROLES[r]}) for r in p.HASHES}
    def test_accepted_package_hashes(self):
        for role,raw in self.raw.items():
            self.assertEqual(p.sha(raw),p.HASHES[role]); self.assertEqual(len(p.archive_files(raw,role)),p.COUNTS[role]+1)
            with self.assertRaises(p.Refused): p.archive_files(raw+b'x',role)
        with self.assertRaises(p.Refused): p.archive_files(self.raw['windows'],'pi-armv6')
    def test_inventory_and_plan(self):
        cfg=b'{"fixture":true}\n'
        w=p.inventory(p.archive_files(self.raw['windows'],'windows'),'windows',cfg)
        q=p.inventory(p.archive_files(self.raw['pi-armv6'],'pi-armv6'),'pi-armv6')
        self.assertEqual((len(w),len(q)),(27,13)); self.assertEqual(w['config/windows.config.json'],cfg)
        self.assertFalse(any(n.startswith('config/') for n in q))
        with self.assertRaises(p.Refused): p.inventory(q,'pi-armv6',cfg)
        self.assertEqual(p.plan(w,'windows'),p.plan(dict(reversed(list(w.items()))),'windows'))
        self.assertNotEqual(p.plan(w,'windows')['plan_sha256'],p.plan({**w,'config/windows.config.json':b'other'},'windows')['plan_sha256'])
        for data in (w,q): self.assertFalse(json.loads(data[p.RECEIPT])['activation_performed'])
    def test_pi_plan_portable_target(self):
        files=p.inventory(p.archive_files(self.raw['pi-armv6'],'pi-armv6'),'pi-armv6')
        expected='0e6cb6905cb2a20e956a4d29081d8f057da05a6b178b140f4799e06eb6bc8f8f'
        native=p.plan(files,'pi-armv6')
        self.assertEqual(native['target'],'/opt/onyxcore/v1.0.0-m5-a8ca64b')
        self.assertEqual(native['plan_sha256'],expected)
        with patch.object(p,'PI_PARENT',PureWindowsPath('/opt/onyxcore')):
            self.assertEqual(p.plan(files,'pi-armv6'),native)
    def test_rollback_config_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp).resolve(); config=b'fixture config'
            items={'config/windows.config.json':config,**{f'code{i}.py':b'fixture' for i in range(15)}}
            rows=[]
            for n,b in items.items():
                f=old/n; f.parent.mkdir(parents=True,exist_ok=True); f.write_bytes(b); rows.append({'path':n,'size':len(b),'sha256':p.sha(b)})
            raw=p.canonical({'installed_files':rows}); (old/'installation-receipt.json').write_bytes(raw)
            with patch.object(p,'OLD_RECEIPT',p.sha(raw)):
                self.assertEqual(p.windows_config(old),config)
                (old/'code0.py').write_bytes(b'changed')
                with self.assertRaises(p.Refused): p.windows_config(old)
            with self.assertRaises(p.Refused): p.windows_config(old)
    def test_tree_audit_extra_tampered_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); f=root/'a'; f.write_bytes(b'x'); p.verify_tree(root,{'a':b'x'})
            f.write_bytes(b'y')
            with self.assertRaises(p.Refused): p.verify_tree(root,{'a':b'x'})
            f.write_bytes(b'x'); (root/'extra').mkdir()
            with self.assertRaises(p.Refused): p.verify_tree(root,{'a':b'x'})
            (root/'extra').rmdir(); f.unlink()
            with self.assertRaises(p.Refused): p.verify_tree(root,{'a':b'x'})
    def test_refuse_unsafe_relative_path(self):
        for n in ('../file','a/../file','/abs','a\\b','a:b','a//b','a./b'):
            with self.subTest(n=n), self.assertRaises(p.Refused): p.parts(n)
    def test_no_write_without_approval(self):
        self.assertEqual(p.main(['publish','--role','pi-armv6','--archive','/nonexistent']),2)
        self.assertEqual(p.main(['plan','--role','pi-armv6','--archive','/nonexistent','--approve-publication']),2)
    @unittest.skipUnless(sys.platform=='win32','Windows native fixture only')
    def test_native_windows_temp_rename_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); stage=root/'stage'; target=root/'target'
            stage.mkdir(); (stage/'witness').write_bytes(b'new')
            p.win_rename_noreplace(stage,target)
            self.assertFalse(stage.exists()); self.assertEqual((target/'witness').read_bytes(),b'new')
            stage.mkdir(); (stage/'witness').write_bytes(b'other')
            with self.assertRaises(p.Refused): p.win_rename_noreplace(stage,target)
            self.assertEqual((stage/'witness').read_bytes(),b'other')
            self.assertEqual((target/'witness').read_bytes(),b'new')
    @unittest.skipUnless(sys.platform=='linux','Linux native fixture only')
    def test_native_posix_temp_publish_and_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fd=os.open(root,p.dirflags())
            try:
                files=p.inventory(p.archive_files(self.raw['pi-armv6'],'pi-armv6'),'pi-armv6')
                p.posix_publish(fd,'candidate',files,os.getuid(),os.getgid())
                target=os.open('candidate',p.dirflags(),dir_fd=fd)
                try: p.audit_posix(target,files,os.getuid(),os.getgid())
                finally: os.close(target)
                with self.assertRaises(p.Refused): p.posix_publish(fd,'candidate',files,os.getuid(),os.getgid())
                (root/'other').mkdir(); (root/'other'/'witness').write_bytes(b'x')
                with self.assertRaises(p.Refused): p.rename_noreplace(fd,'other','candidate')
                self.assertEqual((root/'other'/'witness').read_bytes(),b'x')
            finally: os.close(fd)
    @unittest.skipUnless(sys.platform=='linux','Linux native fixture only')
    def test_native_posix_abandoned_stage_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); fd=os.open(root,p.dirflags())
            try:
                (root/'.onyx-v100-m5-stage-abandoned').mkdir()
                with self.assertRaises(p.Refused): p.posix_publish(fd,'candidate',{'x':b'x'},os.getuid(),os.getgid())
                (root/'.onyx-v100-m5-stage-abandoned').rmdir(); (root/'candidate').symlink_to(root/'missing')
                with self.assertRaises(p.Refused): p.posix_publish(fd,'candidate',{'x':b'x'},os.getuid(),os.getgid())
            finally: os.close(fd)
if __name__=='__main__': unittest.main()
