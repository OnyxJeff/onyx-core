"""Offline S6 fixtures; no native service, credential, task or network writes."""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/installation/common'))
import onyx_v100_release_build as b
import onyx_v100_release_install as i

WIN = {'schema_version':1,'platform':'windows','receiver':{'host':'192.168.137.167','port':8765},'collector':{'source':'SQUALL','network_adapter':'Ethernet','interval_seconds':30},'usb':{'adapter_name':'Ethernet 3'},'gateway':{'listen_host':'127.0.0.1','port':18976},'cpu_temperature':{'enabled':True,'endpoint':'http://192.168.137.1:8085/data.json','sensor_path':'/Sensor/SQUALL/AMD Ryzen 7 5800X/Temperatures/Core (Tctl/Tdie)'}}
PI = {'schema_version':1,'platform':'pi-armv6','receiver':{'interface':'usb0','port':8765,'ipv4_subnet':'192.168.137.0/24','source':'SQUALL'},'storage':{'state_dir':i.PI_STATE,'history_name':'telemetry.db','snapshot_name':'latest-snapshot.json'}}
PATHS = {'localappdata':r'C:\Users\Test User\AppData\Local','pythonw':r'C:\Python313\pythonw.exe','systemroot':r'C:\Windows'}

class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = {r:b.archive(ROOT,r) for r in b.BASES}
        cls.files = {r:i.checked_archive(raw,b.sha(raw),r) for r,raw in cls.raw.items()}

    def test_deterministic_archives_and_inventory(self):
        for r,raw in self.raw.items():
            self.assertEqual(raw,b.archive(ROOT,r))
            self.assertEqual(len(self.files[r]),i.COUNTS[r]+1)
            self.assertFalse(any(n.endswith(('.db','.dpapi','.env','.sqlite3','.key')) for n in self.files[r]))
            self.assertFalse(json.loads(self.files[r][i.MANIFEST])['native_qualified'])

    def test_standalone_release_executor_imports(self):
        for role, files in self.files.items():
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                for name,raw in files.items():
                    dest=root.joinpath(*name.split('/')); dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
                module='onyx_v100_release_'+('windows' if role=='windows' else 'pi')+'_activation.py'
                executor=root/'tools/installation/common'/module
                result=subprocess.run([sys.executable,'-I','-B',str(executor),'--help'],capture_output=True,text=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('--approve-active-rollback',result.stdout)
                self.assertIn('--approve-credential-preparation',result.stdout)

    def test_runtime_lineage_and_branding(self):
        for r,files in self.files.items():
            self.assertEqual(json.loads(files[i.MANIFEST])['accepted_runtime_sha256'],i.BASES[r])
        w=self.files['windows']; self.assertIn(b'-RequireLauncher',w['windows/collector/Launch-OnyxTelemetry.vbs'])
        self.assertIn(b'[switch]$RequireLauncher',w['windows/collector/Send-OnyxTelemetry-v100.ps1'])
        a=w['windows/gateway/gateway-dashboard-v100.html']; self.assertEqual(a,w['windows/gateway/gateway-dashboard.html'])
        self.assertIn('WINDOWS / PI CONNECTIVITY — v1.0.0'.encode(),a)
        self.assertNotIn('WINDOWS / PI CONNECTIVITY — v0.8'.encode(),a)

    def test_wrong_role_hash_and_mutation(self):
        raw=self.raw['windows']
        for content,digest,role in ((raw,'0'*64,'windows'),(raw+b'x',b.sha(raw),'windows'),(raw,b.sha(raw),'pi-armv6')):
            with self.assertRaises(ValueError): i.checked_archive(content,digest,role)

    def renamed_zip(self, original, replacement):
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.raw['windows'])) as src, zipfile.ZipFile(out, 'w') as dst:
            for item in src.infolist():
                data = src.read(item)
                if item.filename == original:
                    # Assign after ZipInfo construction to preserve the raw malformed name.
                    item.filename = replacement
                dst.writestr(item, data)
        return out.getvalue()

    def test_unsafe_zip_entries(self):
        for name in ('../evil', 'CON.txt', 'x/../y', 'x\\y', 'x\x00y'):
            raw = self.renamed_zip(i.MANIFEST, name)
            for sep in ('/', '\\'):
                with self.subTest(name=repr(name), separator=sep), patch.object(zipfile.os, 'sep', sep):
                    with self.assertRaisesRegex(ValueError, 'unsafe inventory path|Unsafe ZIP entry|filename normalization'):
                        i.checked_archive(raw, b.sha(raw), 'windows')

    def test_missing_required_manifest(self):
        raw = self.renamed_zip(i.MANIFEST, 'other-manifest.json')
        with self.assertRaisesRegex(ValueError, 'Required release manifest missing'):
            i.checked_archive(raw, b.sha(raw), 'windows')

    def test_backslash_alias_with_manifest_present(self):
        name = next(n for n in self.files['windows'] if '/' in n)
        raw = self.renamed_zip(name, name.replace('/', '\\'))
        with patch.object(zipfile.os, 'sep', '\\'):
            with self.assertRaisesRegex(ValueError, 'ZIP filename normalization refused'):
                i.checked_archive(raw, b.sha(raw), 'windows')

    def test_reference_config_and_cpu_arguments(self):
        i.validate_release_pair(WIN,PI)
        a=i.windows_actions(WIN,**PATHS); g,c=a['tasks']; args=c['argv']
        self.assertEqual(args[args.index('-Receiver')+1],'192.168.137.167')
        self.assertEqual(args[args.index('-CpuSensorPath')+1],WIN['cpu_temperature']['sensor_path'])
        self.assertIn('-UseSavedToken',args); self.assertIn('-Count',args)
        self.assertIn('--v100-monitor-view',g['argv']); self.assertIn('--load-dpapi',g['argv'])
        self.assertTrue(c['execute'].endswith('wscript.exe'))
        self.assertIn('"'+WIN['cpu_temperature']['sensor_path']+'"',c['arguments'])
        self.assertEqual(a['task_settings']['run_level'],'Limited')

    def test_wscript_host_flags_precede_script(self):
        for enabled in (True, False):
            cfg=copy.deepcopy(WIN)
            if not enabled: cfg['cpu_temperature']={'enabled':False}
            gateway,collector=i.windows_actions(cfg,**PATHS)['tasks']
            argv=collector['argv']
            self.assertEqual(argv[:2],['//B','//Nologo'])
            self.assertEqual(argv[2],str(i.windows_path(PATHS['localappdata']) / i.WIN_NAME / 'windows/collector/Launch-OnyxTelemetry.vbs'))
            self.assertTrue(collector['arguments'].startswith('//B //Nologo "'))
            self.assertEqual(collector['arguments'],subprocess.list2cmdline(argv))
            self.assertEqual(gateway['argv'][:2],['-I','-B'])
            self.assertNotIn('//B',gateway['argv'])
            self.assertEqual(argv.count('//B'),1)
            self.assertEqual(argv.count('//Nologo'),1)
            self.assertIn('-UseSavedToken',argv[3:])

    def test_cpu_disabled_omits_flags(self):
        cfg=copy.deepcopy(WIN); cfg['cpu_temperature']={'enabled':False}
        self.assertNotIn('-EnableCpuTemperature',i.windows_actions(cfg,**PATHS)['tasks'][1]['argv'])

    def test_mismatched_source_port_subnet_and_legacy_state(self):
        for key,value in [('port',8766),('source','Other'),('ipv4_subnet','192.168.138.0/24')]:
            cfg=copy.deepcopy(PI); cfg['receiver'][key]=value
            with self.assertRaises(ValueError): i.validate_release_pair(WIN,cfg)
        cfg=copy.deepcopy(PI); cfg['storage']['state_dir']='/var/lib/onyxcore'
        with self.assertRaises(ValueError): i.validate_release_pair(WIN,cfg)

    def test_clean_release_requires_direct_ipv4(self):
        cfg=copy.deepcopy(WIN); cfg['receiver']['host']='svr-onyxcore.local'
        with self.assertRaisesRegex(ValueError,'direct Pi IPv4'): i.validate_release_pair(cfg,PI)

    def test_unsafe_windows_launch_parameters(self):
        for path in (r'C:\bad%PATH%\local',r'C:\bad\..\local',r'\\host\share\local'):
            with self.assertRaises(ValueError): i.windows_actions(WIN,**dict(PATHS,localappdata=path))
        cfg=copy.deepcopy(WIN); cfg['gateway']['port']=18766
        with self.assertRaises(ValueError): i.windows_actions(cfg,**PATHS)

    def test_pi_unit_security_and_external_state(self):
        unit=i.pi_unit(PI)
        for text in ('User=onyxcore-v100','NoNewPrivileges=yes','ProtectSystem=strict','ReadWritePaths='+i.PI_STATE,'EnvironmentFile='+i.PI_CONFIG+'/receiver.env','--installed-root '+i.PI_ROOT,'--run --approve-execution'):
            self.assertIn(text,unit)
        self.assertNotIn('ONYXCORE_TOKEN=',unit)

    def test_clean_inventory_no_receipt_dependency(self):
        for r,cfg in [('windows',WIN),('pi-armv6',PI)]:
            kwargs=PATHS if r=='windows' else {}
            files,plan=i.inventory(self.files[r],cfg,r,b.sha(self.raw[r]),peer=PI if r=='windows' else WIN,**kwargs)
            again,second=i.inventory(dict(reversed(list(self.files[r].items()))),cfg,r,b.sha(self.raw[r]),peer=PI if r=='windows' else WIN,**kwargs)
            self.assertEqual(files,again); self.assertEqual(plan,second)
            self.assertFalse(json.loads(files[i.RECEIPT])['activation_performed'])
            self.assertEqual(json.loads(files['config/'+r+'.config.json']),cfg)
            self.assertFalse(plan['state_modified'])
            self.assertEqual(plan['plan_sha256'],i.sha(i.native.canonical({k:v for k,v in plan.items() if k!='plan_sha256'})))

    def test_plan_changes_with_config(self):
        raw=self.raw['windows']; files=self.files['windows']
        _,a=i.inventory(files,WIN,'windows',b.sha(raw),peer=PI,**PATHS)
        cfg=copy.deepcopy(WIN); cfg['collector']['interval_seconds']=60
        _,z=i.inventory(files,cfg,'windows',b.sha(raw),peer=PI,**PATHS)
        self.assertNotEqual(a['plan_sha256'],z['plan_sha256'])

    def test_peer_configuration_is_bound_to_plan(self):
        raw=self.raw['pi-armv6']; files=self.files['pi-armv6']
        _,before=i.inventory(files,PI,'pi-armv6',b.sha(raw),peer=WIN)
        peer=copy.deepcopy(WIN); peer['collector']['interval_seconds']=60
        _,after=i.inventory(files,PI,'pi-armv6',b.sha(raw),peer=peer)
        self.assertNotEqual(before['plan_sha256'],after['plan_sha256'])
        self.assertNotEqual(before['peer_config_sha256'],after['peer_config_sha256'])

    def test_cli_plan_and_native_approval_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp).resolve(); z=d/'windows.zip'; z.write_bytes(self.raw['windows']); w=d/'w.json'; p=d/'p.json'; w.write_text(json.dumps(WIN)); p.write_text(json.dumps(PI))
            args=['--archive',str(z),'--sha256',b.sha(self.raw['windows']),'--role','windows','--config',str(w),'--peer-config',str(p),'--localappdata',PATHS['localappdata'],'--pythonw',PATHS['pythonw'],'--systemroot',PATHS['systemroot']]
            for op in ('plan','publish','rollback-inactive'):
                result=subprocess.run([sys.executable,'-I','-B',str(ROOT/b.INSTALL),op,*args],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0 if op=='plan' else 2,result.stderr)
                if op=='plan': self.assertFalse(json.loads(result.stdout)['activation_performed'])
            self.assertEqual(set(d.iterdir()),{z,w,p})

    @unittest.skipUnless(sys.platform=='linux','POSIX fixture only')
    def test_inactive_quarantine_preserves_bytes_and_refuses_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve(); target=root/'release'; data,plan=i.inventory(self.files['pi-armv6'],PI,'pi-armv6',b.sha(self.raw['pi-armv6']),peer=WIN)
            fd=os.open(root,i.native.dirflags())
            try: i.native.posix_publish(fd,target.name,data,os.getuid(),os.getgid())
            finally: os.close(fd)
            # Redirect only the native admission/ownership functions in this temp fixture.
            real_audit=i.native.audit_posix
            def audit(fd,files,uid,gid): real_audit(fd,files,os.getuid(),os.getgid())
            def parent(path,gid): return os.open(path,i.native.dirflags())
            with patch.object(i,'PI_ROOT',str(target)),patch.object(i,'pi_guard',return_value=os.getgid()),patch.object(i.native,'posix_parent',side_effect=parent),patch.object(i.native,'audit_posix',side_effect=audit):
                quarantine=target.with_name('release-rollback'); quarantine.mkdir()
                with self.assertRaises(ValueError): i.rollback_inactive('pi-armv6',data,plan,None)
                self.assertTrue(target.exists()); quarantine.rmdir()
                self.assertEqual(i.rollback_inactive('pi-armv6',data,plan,None),quarantine)
                self.assertFalse(target.exists()); i.native.verify_tree(quarantine,data)

    def test_clean_windows_guard_refuses_existing_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'OnyxCore-v100').mkdir()
            with patch.object(i,'win_no_tasks') as check:
                with self.assertRaises(ValueError): i.win_clean_guard(root)
                check.assert_not_called()

if __name__=='__main__': unittest.main()
