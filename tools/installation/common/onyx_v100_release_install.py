#!/usr/bin/env python3
"""S6 clean-install plan and explicitly approved inactive publication.
No task/service activation, account creation, credential enrollment, or history I/O.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import onyx_v100_m5_publish as native
from onyx_v100_config import validate_config, validate_pair, load_config

MANIFEST = 'release-manifest.json'
RECEIPT = 'release-installation-receipt.json'
WIN_NAME = 'OnyxCore-v100-Inactive-Release100'
PI_ROOT = '/opt/onyxcore/v1.0.0-release'
PI_STATE = '/var/lib/onyxcore-v100'
PI_CONFIG = '/etc/onyxcore-v100'
PI_UNIT = 'onyxcore-v100-receiver.service'
WIN_TASKS = ('ONYX CORE v1.0.0 - Local Gateway', 'ONYX CORE v1.0.0 - Telemetry Collector')
M4 = 'a8ca64b2d06940952f6181a52b9682c0b75bcad6'
TREE = '15e8e437ec3e4b4bdc9301777ec39d450e29918c'
BASES = {'windows':'ae15a99f7fdbd90e5f0fe339260abcc89729a671633c0d913f7709324b7298ef',
         'pi-armv6':'01b258d647ca843eac7f103d6b1c2e73eb1b1cedf7c17c7c4545a62f05149466'}
COUNTS = {'windows':31, 'pi-armv6':15}
HELPER = 'tools/installation/windows/Set-OnyxV100SafeUserDacl.ps1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_archive(raw, expected_sha, role):
    # Independent digest is mandatory, not a digest supplied by the archive itself.
    if role not in COUNTS or not re.fullmatch('[0-9a-f]{64}', expected_sha) or len(raw) > 8*1024*1024 or sha(raw) != expected_sha:
        raise ValueError('Trusted release archive hash required')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        if len(infos) != COUNTS[role]+1 or len({i.filename.casefold() for i in infos}) != len(infos):
            raise ValueError('Unexpected release inventory')
        for i in infos:
            # ZipInfo normalizes backslashes on Windows and truncates NUL names.
            # Reject the original spelling before trusting any normalized path.
            if i.orig_filename != i.filename:
                raise ValueError('ZIP filename normalization refused')
            parts = native.parts(i.orig_filename)
            if (i.is_dir() or i.external_attr >> 16 != 0o100644 or i.file_size > 512*1024 or
                i.compress_type != zipfile.ZIP_STORED or any(p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{k}' for k in range(1,10)),*(f'LPT{k}' for k in range(1,10))} for p in parts)):
                raise ValueError('Unsafe ZIP entry')
        files = {i.filename:z.read(i) for i in infos}
    if MANIFEST not in files:
        raise ValueError('Required release manifest missing')
    m = json.loads(files[MANIFEST])
    if (m['schema_version'], m['release_version'], m['kind'], m['role'], m['runtime_source_commit'], m['runtime_source_tree'], m['accepted_runtime_sha256']) != (1,'1.0.0','onyxcore-v100-release-candidate',role,M4,TREE,BASES[role]):
        raise ValueError('Release identity differs')
    if m['credential_files_included'] is not False or m['native_qualified'] is not False:
        raise ValueError('Release status differs')
    rows = m['files']
    if len(rows) != COUNTS[role] or {r['path'] for r in rows} != set(files)-{MANIFEST}:
        raise ValueError('Manifest inventory differs')
    for r in rows:
        b = files[r['path']]
        if r['size'] != len(b) or r['sha256'] != sha(b):
            raise ValueError('Manifest file differs')
    return files


def config_bytes(cfg, role):
    validate_config(cfg, role)
    if role == 'pi-armv6' and cfg['storage']['state_dir'] != PI_STATE:
        raise ValueError('v1 state directory is fixed and isolated')
    if role == 'windows' and cfg['gateway']['port'] in (18766,18767,18768):
        raise ValueError('Monitoring-enabled gateway cannot use legacy ports')
    return native.canonical(cfg)


def validate_release_pair(windows, pi):
    validate_pair(windows, pi)
    config_bytes(windows, 'windows'); config_bytes(pi, 'pi-armv6')
    try:
        address = ipaddress.IPv4Address(windows['receiver']['host'])
    except ipaddress.AddressValueError:
        raise ValueError('Clean release requires the direct Pi IPv4 address') from None
    network = ipaddress.IPv4Network(pi['receiver']['ipv4_subnet'])
    if address not in network or address in (network.network_address, network.broadcast_address):
        raise ValueError('Receiver address outside configured Pi subnet')


def windows_path(value):
    p = PureWindowsPath(value)
    if (not p.is_absolute() or not re.fullmatch(r'[A-Za-z]:',p.drive) or '..' in p.parts or
        any(not re.fullmatch(r'[A-Za-z0-9 _().#-]+',x) or x.endswith(('.', ' ')) for x in p.parts[1:])):
        raise ValueError('Unsafe Windows absolute path')
    return p


def windows_actions(cfg, localappdata, pythonw, systemroot):
    config_bytes(cfg,'windows')
    root = windows_path(localappdata) / WIN_NAME
    py = windows_path(pythonw)
    if py.name.lower() != 'pythonw.exe':
        raise ValueError('Expected pythonw.exe')
    wscript = windows_path(systemroot) / 'System32' / 'wscript.exe'
    c = cfg['collector']; r = cfg['receiver']; sensor = cfg.get('cpu_temperature',{'enabled':False})
    collector = ['//B', '//Nologo', str(root/'windows/collector/Launch-OnyxTelemetry.vbs'), '-IntervalSeconds', str(c['interval_seconds']), '-Count','0', '-Receiver',r['host'],'-ReceiverPort',str(r['port']),'-Source',c['source'],'-AdapterName',c['network_adapter'],'-UseSavedToken']
    if sensor['enabled']:
        collector += ['-EnableCpuTemperature','-CpuSensorEndpoint',sensor['endpoint'],'-CpuSensorPath',sensor['sensor_path']]
    # WScript re-quotes and expands percent variables; enforce its admitted argument domain.
    if any(not a or len(a)>512 or '"' in a or '%' in a or a.endswith('\\') or any(ord(x)<32 or ord(x)>126 for x in a) for a in collector):
        raise ValueError('Argument outside qualified launcher domain')
    if sum(len(a)+3 for a in collector)+256 > 1800:
        raise ValueError('Collector command too long for qualified launcher')
    gateway = ['-I','-B',str(root/'windows/gateway/OnyxGateway_v100.py'),'--dashboard',str(root/'windows/gateway/gateway-dashboard.html'),'--receiver',r['host'],'--receiver-port',str(r['port']),'--port',str(cfg['gateway']['port']),'--load-dpapi','--v100-monitor-view']
    def action(name, exe, argv):
        return {'task_name': name, 'execute': str(exe), 'argv':argv,
                'arguments': subprocess.list2cmdline(argv), 'working_directory':str(root)}
    return {'root':str(root), 'tasks':[action(WIN_TASKS[0],py,gateway),action(WIN_TASKS[1],wscript,collector)],
            'task_settings':{'logon_type':'Interactive','run_level':'Limited','trigger':'AtLogOn','execution_time_limit':'PT0S','restart_count':3,'restart_interval':'PT1M','start_when_available':True,'multiple_instances':'IgnoreNew'},
            'credential_path':str(windows_path(localappdata)/'OnyxCore-v100/collector-token.dpapi'),
            'monitoring_journal':str(windows_path(localappdata)/'OnyxCore-v100/Monitoring/incident-history.sqlite3')}


def pi_unit(cfg):
    config_bytes(cfg,'pi-armv6')
    return '\n'.join(('[Unit]', 'Description=ONYX CORE v1.0.0 USB receiver', 'Wants=network-online.target', 'After=NetworkManager.service network-online.target', '',
        '[Service]', 'Type=simple', 'User=onyxcore-v100', 'Group=onyxcore-v100', 'EnvironmentFile='+PI_CONFIG+'/receiver.env', 'WorkingDirectory='+PI_STATE,
        'ExecStart=/usr/bin/python3 -I -B '+PI_ROOT+'/tools/installation/pi/onyx_v100_pi_launch.py --config '+PI_ROOT+'/config/pi-armv6.config.json --installed-root '+PI_ROOT+' --run --approve-execution',
        'Restart=on-failure','RestartSec=15','UMask=0077','NoNewPrivileges=yes','PrivateTmp=yes','ProtectSystem=strict','ProtectHome=yes','ReadWritePaths='+PI_STATE,
        'InaccessiblePaths=-/etc/onyxcore -/var/lib/onyxcore','CapabilityBoundingSet=','AmbientCapabilities=','', '[Install]','WantedBy=multi-user.target',''))


def inventory(files, cfg, role, digest, *, peer, localappdata=None, pythonw=None, systemroot=None):
    data = dict(files)
    cfg_raw = config_bytes(cfg,role)
    validate_release_pair(cfg,peer) if role=='windows' else validate_release_pair(peer,cfg)
    peer_digest = sha(config_bytes(peer,'pi-armv6' if role=='windows' else 'windows'))
    cfg_path = 'config/'+role+'.config.json'
    if cfg_path in data or RECEIPT in data or 'activation-plan.json' in data:
        raise ValueError('Reserved installation filename')
    data[cfg_path] = cfg_raw
    if role == 'windows':
        activation = windows_actions(cfg,localappdata,pythonw,systemroot)
    else:
        activation = {'root':PI_ROOT,'unit_name':PI_UNIT,'unit_contents':pi_unit(cfg),'credential_path':PI_CONFIG+'/receiver.env','state_path':PI_STATE}
    activation.update({'activation_performed':False, 'requires_separate_approval':True, 'rollback_policy':'stop and remove only exact release-owned definitions; preserve state, credentials and runtime for investigation'})
    data['activation-plan.json'] = native.canonical(activation)
    rows = [{'path':n,'sha256':sha(b),'size':len(b)} for n,b in sorted(data.items())]
    data[RECEIPT] = native.canonical({'schema_version':1,'role':role,'archive_sha256':digest,'config_sha256':sha(cfg_raw),'peer_config_sha256':peer_digest,'files':rows,'activation_performed':False,'state_modified':False,'credential_enrolled':False})
    report = {'role':role,'archive_sha256':digest,'peer_config_sha256':peer_digest,'target':activation['root'],'files':[{'path':n,'sha256':sha(b),'size':len(b)} for n,b in sorted(data.items())], 'activation_performed':False,'state_modified':False,'activation':activation}
    return data, dict(report, plan_sha256=sha(native.canonical(report)))


def pi_guard():
    if sys.platform!='linux' or platform.machine()!='armv6l' or sys.version_info[:2]!=(3,13) or os.geteuid()!=0:
        raise ValueError('Native root ARMv6 Linux Python 3.13 required')
    if 'VERSION_CODENAME=trixie' not in Path('/etc/os-release').read_text().splitlines():
        raise ValueError('Trixie required')
    import pwd, grp
    u=pwd.getpwnam('onyxcore-v100'); g=grp.getgrnam('onyxcore-v100')
    if (u.pw_uid<=0 or g.gr_gid<=0 or u.pw_gid!=g.gr_gid or u.pw_dir!='/nonexistent' or u.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false','/usr/bin/false') or set(os.getgrouplist(u.pw_name,g.gr_gid))!={g.gr_gid} or set(g.gr_mem)-{u.pw_name} or any(x.pw_name!=u.pw_name and (x.pw_uid==u.pw_uid or x.pw_gid==g.gr_gid) for x in pwd.getpwall()) or any(x.gr_name!=g.gr_name and x.gr_gid==g.gr_gid for x in grp.getgrall())):
        raise ValueError('Dedicated service identity required')
    # Clean publication deliberately refuses pre-existing live service/state/credential.
    for p in (PI_STATE,PI_CONFIG,'/etc/systemd/system/'+PI_UNIT,'/opt/onyxcore/v1.0.0','/opt/onyxcore/v1.0.0-m5-a8ca64b','/etc/systemd/system/onyxcore-receiver.service','/var/lib/onyxcore','/etc/onyxcore'):
        native.absent(Path(p))
    return g.gr_gid


def win_no_tasks():
    ps = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    command = "$ErrorActionPreference='Stop'; if (@(Get-ScheduledTask | Where-Object {$_.TaskName -like 'ONYX CORE*'}).Count -ne 0) {exit 3}; exit 0"
    subprocess.run([str(ps),'-NoProfile','-NonInteractive','-Command',command],check=True,timeout=30)


def win_clean_guard(root):
    # Refuse existing release state, runtime roots or ONYX tasks. Read-only task enumeration.
    for p in root.iterdir():
        if p.name.lower().startswith(('onyxcore','.onyxcore')):
            raise ValueError('Existing ONYX installation requires migration workflow')
    win_no_tasks()


def publish_clean(role, data, report, helper):
    if role=='windows':
        root = native.win_guard(); win_clean_guard(root)
        if str(root/WIN_NAME).casefold()!=report['target'].casefold():
            raise ValueError('Native user root differs from approved plan')
        plan = report['activation']
        if not Path(plan['tasks'][0]['execute']).is_file() or not Path(plan['tasks'][1]['execute']).is_file():
            raise ValueError('Native executable missing')
        if Path(plan['tasks'][1]['execute']).parent.parent != Path(os.environ['SystemRoot']):
            raise ValueError('Native SystemRoot differs')
        for task in plan['tasks']:
            native.plain(Path(task['execute']))
        if helper is None or sha(native.read_regular(helper,65536)) not in native.ACL_HASHES:
            raise ValueError('Reviewed ACL helper required')
        if native.read_regular(helper,65536).replace(b'\r\n',b'\n') != data[HELPER]:
            raise ValueError('ACL helper differs from release')
        old = native.WIN_TARGET
        try:
            native.WIN_TARGET = WIN_NAME
            return native.win_publish(root,data,helper)
        finally:
            native.WIN_TARGET = old
    if helper is not None:
        raise ValueError('Windows helper forbidden on Pi')
    gid = pi_guard()
    root = Path(PI_ROOT)
    fd = native.posix_parent(root.parent,gid)
    try:
        native.posix_publish(fd,root.name,data,0,gid)
    finally:
        os.close(fd)
    return root


def rollback_inactive(role, data, report, helper):
    """Quarantine only the authenticated, still-inactive clean publication.

    Existing runtime or task/service definitions are never removed or changed.
    Rollback after activation requires a separate implementation and approval.
    """
    if role == 'windows':
        root = native.win_guard()
        target = root/WIN_NAME
        quarantine = root/(WIN_NAME+'-Rollback')
        if str(target).casefold()!=report['target'].casefold():
            raise ValueError('Native user root differs from approved plan')
        # Require no credential/state root or ONYX task, including legacy tasks.
        native.absent(root/'OnyxCore-v100'); native.absent(quarantine)
        win_no_tasks()
        if helper is None or sha(native.read_regular(helper,65536)) not in native.ACL_HASHES:
            raise ValueError('Reviewed ACL helper required')
        native.verify_tree(target,data)
        ps = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(helper),'-Mode','Audit','-Scope','User','-Root',str(root),'-ContentPath',str(target),'-ApproveInactiveUser','-ApproveUserDacl'],check=True,timeout=120)
        native.verify_tree(target,data); win_no_tasks()
        native.win_rename_noreplace(target,quarantine)
        native.verify_tree(quarantine,data)
        return quarantine
    if helper is not None:
        raise ValueError('Windows helper forbidden on Pi')
    gid = pi_guard()
    target = Path(PI_ROOT); quarantine = target.with_name(target.name+'-rollback')
    fd = native.posix_parent(target.parent,gid)
    try:
        native.posix_absent(fd,quarantine.name)
        node = os.open(target.name,native.dirflags(),dir_fd=fd)
        try: native.audit_posix(node,data,0,gid)
        finally: os.close(node)
        native.rename_noreplace(fd,target.name,quarantine.name); os.fsync(fd)
        node = os.open(quarantine.name,native.dirflags(),dir_fd=fd)
        try: native.audit_posix(node,data,0,gid)
        finally: os.close(node)
    finally: os.close(fd)
    return quarantine


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('plan','publish','rollback-inactive'))
    p.add_argument('--archive',type=Path,required=True); p.add_argument('--sha256',required=True)
    p.add_argument('--role',choices=sorted(BASES),required=True); p.add_argument('--config',type=Path,required=True)
    p.add_argument('--peer-config',type=Path,required=True)
    p.add_argument('--localappdata'); p.add_argument('--pythonw'); p.add_argument('--systemroot')
    p.add_argument('--acl-helper',type=Path); p.add_argument('--approve-publication',action='store_true'); p.add_argument('--approved-plan'); p.add_argument('--approve-inactive-rollback',action='store_true')
    a=p.parse_args()
    try:
        if a.operation=='publish' and (not a.approve_publication or a.approve_inactive_rollback or not a.approved_plan):
            raise ValueError('Separate native publication approval and exact plan hash required')
        if a.operation=='rollback-inactive' and (not a.approve_inactive_rollback or a.approve_publication or not a.approved_plan):
            raise ValueError('Separate inactive rollback approval and exact plan hash required')
        if a.operation=='plan' and (a.approve_publication or a.approve_inactive_rollback or a.approved_plan or a.acl_helper):
            raise ValueError('Plan cannot accept native write options')
        if a.role=='windows' and not all((a.localappdata,a.pythonw,a.systemroot)) or a.role!='windows' and any((a.localappdata,a.pythonw,a.systemroot)):
            raise ValueError('Role-specific target paths required')
        raw=native.read_regular(a.archive,8*1024*1024)
        files=checked_archive(raw,a.sha256,a.role)
        native.read_regular(a.config,65536); native.read_regular(a.peer_config,65536)
        cfg=load_config(a.config,a.role); peer=load_config(a.peer_config,'pi-armv6' if a.role=='windows' else 'windows')
        windows,pi=(cfg,peer) if a.role=='windows' else (peer,cfg)
        validate_release_pair(windows,pi)
        data,report=inventory(files,cfg,a.role,a.sha256,peer=peer,localappdata=a.localappdata,pythonw=a.pythonw,systemroot=a.systemroot)
        if a.operation in ('publish','rollback-inactive'):
            if report['plan_sha256']!=a.approved_plan:
                raise ValueError('Approved plan differs')
            target=(publish_clean if a.operation=='publish' else rollback_inactive)(a.role,data,report,a.acl_helper)
            print(json.dumps({'status':'INACTIVE_RELEASE_PUBLISHED' if a.operation=='publish' else 'INACTIVE_RELEASE_QUARANTINED','target':str(target),'plan_sha256':a.approved_plan,'activation_performed':False},sort_keys=True))
        else:
            print(json.dumps(report,sort_keys=True))
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print('STOP: '+str(exc),file=sys.stderr); return 2

if __name__=='__main__':
    sys.exit(main())
