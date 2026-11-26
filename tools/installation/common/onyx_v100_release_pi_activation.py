#!/usr/bin/env python3
"""Clean Pi release activation/rollback. Native writes require separate approval.

No migration, credential rotation, history deletion, network configuration or
monitoring. A durable intent precedes unit publication; ambiguous failure stops.
"""
from __future__ import annotations
import argparse
import contextlib
import json
import getpass
import warnings
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import onyx_v100_release_install as install
from onyx_v100_config import load_config

native = install.native
UNIT_DIR = Path('/etc/systemd/system')
INTENT = 'activation-intent.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def intent(report):
    require(report['role'] == 'pi-armv6', 'Pi plan required')
    return native.canonical({'schema_version': 1, 'kind': 'pi-clean-activation-intent',
        'plan_sha256': report['plan_sha256'], 'unit_name': install.PI_UNIT,
        'unit_sha256': install.sha(report['activation']['unit_contents'].encode('utf-8')),
        'preserve_runtime_state_credentials': True})


def write_new(fd, name, data, uid, gid, mode):
    """Publish complete file, without replacing anything, under trusted parent."""
    native.posix_absent(fd, name)
    temp = '.onyx-activation-' + uuid.uuid4().hex
    f = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(f, 'wb') as stream:
        os.fchown(stream.fileno(), uid, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
        native.check_meta(stream.fileno(), uid, gid, mode, False)
    native.rename_noreplace(fd, temp, name)
    os.fsync(fd)


def read_exact(fd, name, expected, uid, gid, mode):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(f, 'rb') as stream:
        native.check_meta(stream.fileno(), uid, gid, mode, False)
        require(stream.read(len(expected)+1) == expected, 'Owned file identity differs: '+name)


def identity():
    require(sys.platform == 'linux' and platform.machine() == 'armv6l' and
            sys.version_info[:2] == (3,13) and os.geteuid() == 0, 'Native root ARMv6 Python 3.13 required')
    require('VERSION_CODENAME=trixie' in Path('/etc/os-release').read_text().splitlines(), 'Trixie required')
    import pwd, grp
    u = pwd.getpwnam('onyxcore-v100'); g = grp.getgrnam('onyxcore-v100')
    require(u.pw_uid > 0 and g.gr_gid > 0 and u.pw_gid == g.gr_gid and u.pw_dir == '/nonexistent' and
            u.pw_shell in ('/usr/sbin/nologin','/sbin/nologin','/bin/false','/usr/bin/false') and
            set(os.getgrouplist(u.pw_name,g.gr_gid)) == {g.gr_gid} and not set(g.gr_mem)-{u.pw_name} and
            not any(x.pw_name != u.pw_name and (x.pw_uid == u.pw_uid or x.pw_gid == g.gr_gid) for x in pwd.getpwall()) and
            not any(x.gr_name != g.gr_name and x.gr_gid == g.gr_gid for x in grp.getgrall()), 'Dedicated service identity required')
    for p in ('/opt/onyxcore/v1.0.0','/opt/onyxcore/v1.0.0-m5-a8ca64b',
              '/etc/systemd/system/onyxcore-receiver.service','/var/lib/onyxcore','/etc/onyxcore'):
        native.absent(Path(p))
    parent=native.posix_parent(Path(install.PI_ROOT).parent,g.gr_gid)
    try:
        require(set(os.listdir(parent)) == {Path(install.PI_ROOT).name},'Other ONYX runtime or incomplete stage requires review')
    finally: os.close(parent)
    for verb in ('list-unit-files','list-units'):
        raw=ctl(verb,'onyxcore*','--no-legend','--plain',*(['--all'] if verb=='list-units' else []))
        require(all(line.split()[0]==install.PI_UNIT for line in raw.splitlines() if line.strip()),
                'Other ONYX unit requires review')
    return u.pw_uid, g.gr_gid


def ctl(*args):
    return subprocess.run(['/usr/bin/systemctl', '--no-pager', *args], check=True,
                          capture_output=True, text=True, timeout=60).stdout


def service(name=install.PI_UNIT):
    keys = ('LoadState','ActiveState','SubState','UnitFileState','FragmentPath','DropInPaths',
            'NeedDaemonReload','User','Group','NoNewPrivileges','ProtectSystem','MainPID')
    result = subprocess.run(['/usr/bin/systemctl','--no-pager','show','--all',name,
        *[arg for key in keys for arg in ('-p',key)]], capture_output=True,text=True,timeout=60)
    props = dict(line.split('=',1) for line in result.stdout.splitlines())
    require(result.returncode==0 or (result.returncode==1 and props.get('LoadState')=='not-found'),
            'Systemd inspection failed')
    require(set(props) == set(keys), 'Incomplete systemd identity')
    return props


def require_absent(props):
    require(props['LoadState'] == 'not-found' and props['ActiveState'] == 'inactive' and
            not props['FragmentPath'] and not props['DropInPaths'] and props['MainPID'] == '0',
            'Existing systemd definition or process refused')


def require_owned(props):
    require(props['LoadState'] == 'loaded' and props['FragmentPath'] == str(UNIT_DIR/install.PI_UNIT) and
            not props['DropInPaths'] and props['NeedDaemonReload'] == 'no' and
            props['User'] == props['Group'] == 'onyxcore-v100' and
            props['NoNewPrivileges'] == 'yes' and props['ProtectSystem'] == 'strict' and
            props['UnitFileState'] in ('enabled','disabled'), 'Loaded unit identity differs')


@contextlib.contextmanager
def checked_dirs(data, report, uid, gid, *, clean):
    # Root-controlled parents are independently checked; state is service-owned.
    with contextlib.ExitStack() as stack:
        def directory(path, owner, group, mode):
            path = Path(path); parent = native.posix_parent(path.parent,gid)
            stack.callback(os.close,parent)
            fd = os.open(path.name,native.dirflags(),dir_fd=parent)
            stack.callback(os.close,fd)
            native.check_meta(fd,owner,group,mode,True)
            return fd
        runtime = directory(install.PI_ROOT,0,gid,0o750)
        native.audit_posix(runtime,data,0,gid)
        config = directory(install.PI_CONFIG,0,gid,0o750)
        import fcntl
        fcntl.flock(config,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = directory(install.PI_STATE,uid,gid,0o700)
        credential = os.open('receiver.env',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=config)
        try:
            native.check_meta(credential,0,0,0o600,False)
            require(32 <= os.fstat(credential).st_size <= 4096,'Credential metadata differs')
        finally: os.close(credential)
        units = native.posix_parent(UNIT_DIR,gid); stack.callback(os.close,units)
        if clean:
            require(set(os.listdir(config)) == {'receiver.env'},'Existing config/intent requires review')
            require(not os.listdir(state),'Existing history requires migration workflow')
        yield config, units


def bind_address(cfg, peer):
    # Use the already qualified pure parser; no changes to interface addresses.
    sys.path.insert(0,str(Path(install.PI_ROOT)/'tools/installation/pi'))
    from onyx_v100_usb_binding import selected_ipv4_from_json
    r=cfg['receiver']
    raw=subprocess.run(['/usr/sbin/ip','-j','-4','address','show','dev',r['interface']],check=True,
                       capture_output=True,text=True,timeout=5).stdout
    address=selected_ipv4_from_json(raw,r['interface'],r['ipv4_subnet'])
    # First clean release requires direct IPv4 identity; DNS may be supported later.
    require(peer['receiver']['host']==address,'Windows receiver must match native Pi IPv4')
    return address


def health(address, port):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        try:
            with opener.open(f'http://{address}:{port}/healthz',timeout=3) as response:
                if response.status==200 and json.loads(response.read(1024))=={'status':'ok'}:
                    return
        except (OSError,ValueError): pass
        time.sleep(2)
    raise ValueError('Receiver health not established; preserve intent and review')


def prepare(data, report):
    """Explicit clean-host credential/state preparation; never rotates a token."""
    uid,gid=identity()
    with contextlib.ExitStack() as stack:
        runtime=Path(install.PI_ROOT)
        parent=native.posix_parent(runtime.parent,gid); stack.callback(os.close,parent)
        fd=os.open(runtime.name,native.dirflags(),dir_fd=parent); stack.callback(os.close,fd)
        native.audit_posix(fd,data,0,gid)
        require_absent(service()); require_absent(service('onyxcore-receiver.service'))
        units=native.posix_parent(UNIT_DIR,gid); stack.callback(os.close,units)
        native.posix_absent(units,install.PI_UNIT); native.posix_absent(units,install.PI_UNIT+'.rollback')
        targets=[]
        for path,owner,group,mode in ((install.PI_CONFIG,0,gid,0o750),(install.PI_STATE,uid,gid,0o700)):
            p=Path(path); parent=native.posix_parent(p.parent,gid); stack.callback(os.close,parent)
            native.posix_absent(parent,p.name)
            require(not any(n.startswith('.onyx-release-prepare-') for n in os.listdir(parent)),
                    'Previous preparation stage requires review')
            targets.append((p,parent,owner,group,mode))
        require(sys.stdin.isatty(),'Interactive terminal required for credential entry')
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            token=getpass.getpass('Receiver token (not echoed): ')
            again=getpass.getpass('Confirm receiver token (not echoed): ')
        require(token==again and re.fullmatch(r'[A-Za-z0-9_-]{32,128}',token) is not None,
                'Matching URL-safe token of 32-128 characters required')
        try:
            for p,parent,owner,group,mode in targets:
                stage='.onyx-release-prepare-'+uuid.uuid4().hex
                os.mkdir(stage,0o700,dir_fd=parent)
                node=os.open(stage,native.dirflags(),dir_fd=parent)
                try:
                    if str(p)==install.PI_CONFIG:
                        write_new(node,'receiver.env',('ONYXCORE_TOKEN='+token+'\n').encode('ascii'),0,0,0o600)
                    os.fchown(node,owner,group); os.fchmod(node,mode)
                    native.check_meta(node,owner,group,mode,True); os.fsync(node)
                finally: os.close(node)
                native.rename_noreplace(parent,stage,p.name); os.fsync(parent)
        finally:
            token=again=None
    return 'PI_STATE_AND_CREDENTIAL_PREPARED'


def activate(data, report, cfg, peer):
    uid,gid=identity(); unit=report['activation']['unit_contents'].encode('utf-8')
    with checked_dirs(data,report,uid,gid,clean=True) as (config,units):
        native.posix_absent(units,install.PI_UNIT)
        native.posix_absent(units,install.PI_UNIT+'.rollback')
        require_absent(service()); require_absent(service('onyxcore-receiver.service'))
        address=bind_address(cfg,peer); port=cfg['receiver']['port']
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            sock.bind((address,port))  # refuse occupied receiver port before any write
        write_new(config,INTENT,intent(report),0,0,0o600)
        write_new(units,install.PI_UNIT,unit,0,0,0o644)
        ctl('daemon-reload'); require_owned(service())
        ctl('start',install.PI_UNIT)
        health(address,port)
        require_owned(service()); ctl('enable',install.PI_UNIT)
        props=service(); require_owned(props)
        require(props['UnitFileState']=='enabled' and props['ActiveState']=='active' and
                props['SubState']=='running' and int(props['MainPID'])>0,'Receiver not active and enabled')
        read_exact(units,install.PI_UNIT,unit,0,0,0o644)
    return 'PI_ACTIVATED'


def rollback(data, report):
    uid,gid=identity(); unit=report['activation']['unit_contents'].encode('utf-8')
    with checked_dirs(data,report,uid,gid,clean=False) as (config,units):
        read_exact(config,INTENT,intent(report),0,0,0o600)
        native.posix_absent(units,install.PI_UNIT+'.rollback')
        read_exact(units,install.PI_UNIT,unit,0,0,0o644)
        require_owned(service())
        ctl('stop',install.PI_UNIT)
        props=service(); require_owned(props)
        require(props['ActiveState']=='inactive' and props['MainPID']=='0','Receiver did not stop')
        ctl('disable',install.PI_UNIT)
        props=service(); require_owned(props)
        require(props['UnitFileState']=='disabled' and props['ActiveState']=='inactive' and props['MainPID']=='0',
                'Receiver did not disable')
        read_exact(units,install.PI_UNIT,unit,0,0,0o644)
        # Quarantine rather than delete the exact unit; never touch runtime/state/credential.
        native.rename_noreplace(units,install.PI_UNIT,install.PI_UNIT+'.rollback')
        os.fsync(units)
        ctl('daemon-reload'); require_absent(service())
    return 'PI_ROLLED_BACK_RUNTIME_AND_STATE_RETAINED'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('prepare','activate','rollback'))
    p.add_argument('--archive',type=Path,required=True); p.add_argument('--sha256',required=True)
    p.add_argument('--config',type=Path,required=True); p.add_argument('--peer-config',type=Path,required=True)
    p.add_argument('--approved-plan',required=True); p.add_argument('--approve-activation',action='store_true')
    p.add_argument('--approve-active-rollback',action='store_true'); p.add_argument('--approve-credential-preparation',action='store_true')
    a=p.parse_args(argv)
    try:
        require((a.approve_activation,a.approve_active_rollback,a.approve_credential_preparation)==
                {'activate':(True,False,False),'rollback':(False,True,False),'prepare':(False,False,True)}[a.operation],
                'Separate explicit operation approval required')
        require(re.fullmatch('[0-9a-f]{64}',a.approved_plan) is not None,'Exact plan digest required')
        files=install.checked_archive(native.read_regular(a.archive,8*1024*1024),a.sha256,'pi-armv6')
        native.read_regular(a.config,65536); native.read_regular(a.peer_config,65536)
        cfg=load_config(a.config,'pi-armv6'); peer=load_config(a.peer_config,'windows')
        install.validate_release_pair(peer,cfg)
        data,report=install.inventory(files,cfg,'pi-armv6',a.sha256,peer=peer)
        require(report['plan_sha256']==a.approved_plan,'Approved plan differs')
        result=prepare(data,report) if a.operation=='prepare' else (activate(data,report,cfg,peer) if a.operation=='activate' else rollback(data,report))
        print(json.dumps({'status':result,'plan_sha256':a.approved_plan,'history_deleted':False,'credential_created':a.operation=='prepare','credential_replaced':False}))
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError,getpass.GetPassWarning) as exc:
        # Do not echo stderr from native services, which may contain credential material.
        print('STOP: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)+'; preserve any intent/partial changes for review',file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
