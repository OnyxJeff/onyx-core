#!/usr/bin/env python3
"""S7D inactive Pi publisher. Preview is portable; system install is explicit.
No account provisioning, credentials, service registration or activation.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import onyx_v100_pi_isolated_contract as contract
from onyx_v100_pi_code_publish import (expected_files, receipt_bytes, canonical_json,
    rename_noreplace, RECEIPT, UNIT_CANDIDATE, BUNDLE_SHA256, SOURCE_COMMIT)

TARGETS = (contract.RELEASE, contract.CONFIG_ROOT, contract.STATE)
PARENTS = ('/opt/onyxcore', '/etc', '/var/lib')
NAMES = ('v1.0.0', 'onyxcore-v100', 'onyxcore-v100')
PREFIX = '.onyx-v100-s7d-stage-'
DIR = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
FILE = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
class Refused(ValueError): pass

def sha(data): return hashlib.sha256(data).hexdigest()

def candidates(bundle: Path, config: Path):
    """Use frozen runtime and accepted unit transformation, not SQUALL evidence.
    New receipts describe intended file inventory, not a completed transaction.
    """
    files, cfg = expected_files(bundle, config)
    files[UNIT_CANDIDATE] = contract.revised_unit(files[UNIT_CANDIDATE])
    data = canonical_json(cfg)
    receipt = json.loads(receipt_bytes(files))
    receipt.update(operation='PI_V100_INACTIVE_RELEASE_INVENTORY',
                   contract_revision='M2-S7D', service_identity=contract.IDENTITY,
                   config_target=contract.CONFIG, verification='requires_native_post_publish_audit')
    files[RECEIPT] = canonical_json(receipt)
    ext = {'pi-armv6.config.json':data, 'config-receipt.json':canonical_json({
        'schema_version':1, 'operation':'PI_V100_INACTIVE_CONFIG_INVENTORY',
        'contract_revision':'M2-S7D','source_commit':SOURCE_COMMIT,'bundle_sha256':BUNDLE_SHA256,
        'config_sha256':sha(data), 'config_target':contract.CONFIG, 'state_target':contract.STATE,
        'service_identity':contract.IDENTITY,'credential_enrolled':False,'unit_registered':False,
        'activation_performed':False,'existing_history_migrated':False,
        'verification':'requires_native_post_publish_audit'})}
    if len(files)!=15 or len(ext)!=2: raise Refused('unexpected payload counts')
    return (files, ext, {})

def plan(payloads):
    if len(payloads)!=3 or tuple(map(len,payloads))!=(15,2,0): raise Refused('bad payload counts')
    report={'schema_version':1,'operation':'M2_S7D_INACTIVE_PUBLICATION_PLAN',
            'targets':list(TARGETS),'identity':contract.IDENTITY,'bundle_sha256':BUNDLE_SHA256,
            'file_counts':[15,2,0], 'inventories':[{k:sha(v) for k,v in sorted(p.items())} for p in payloads],
            'permissions':{'release_and_config_dirs':'root:onyxcore-v100 0750',
                           'release_and_config_files':'root:onyxcore-v100 0640',
                           'state':'onyxcore-v100:onyxcore-v100 0700'},
            'service_registered':False,'credentials_enrolled':False,'activation_performed':False}
    return dict(report,plan_sha256=sha(canonical_json(report)))

def native_guard():
    if sys.platform!='linux' or platform.machine()!='armv6l' or sys.version_info[:2]!=(3,13) or os.geteuid()!=0:
        raise Refused('native system operation requires root Linux ARMv6 Python 3.13')
    if 'VERSION_CODENAME=trixie' not in Path('/etc/os-release').read_text().splitlines():
        raise Refused('Trixie required for this candidate')

def identity():
    import pwd,grp
    try: u=pwd.getpwnam(contract.IDENTITY); g=grp.getgrnam(contract.IDENTITY)
    except KeyError as exc: raise Refused('dedicated account and group must be provisioned separately') from exc
    if (u.pw_uid<=0 or g.gr_gid<=0 or u.pw_gid!=g.gr_gid or
        u.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false','/usr/bin/false') or
        u.pw_dir!='/nonexistent' or set(os.getgrouplist(u.pw_name,g.gr_gid))!={g.gr_gid} or
        set(g.gr_mem)-{u.pw_name} or
        any(x.pw_name!=u.pw_name and (x.pw_uid==u.pw_uid or x.pw_gid==g.gr_gid) for x in pwd.getpwall()) or
        any(x.gr_name!=g.gr_name and x.gr_gid==g.gr_gid for x in grp.getgrall())):
        raise Refused('unsafe dedicated identity or group membership')
    return u.pw_uid,g.gr_gid

def no_acl(fd):
    if any(n in ('system.posix_acl_access','system.posix_acl_default') for n in os.listxattr(fd)):
        raise Refused('extended POSIX ACL requires review')

def parent_check(fd, owner, gid):
    s=os.fstat(fd); mode=stat.S_IMODE(s.st_mode)
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=owner or mode & 0o022:
        raise Refused('unsafe publication parent')
    if not (mode & 1 or s.st_gid==gid and mode & 0o010):
        raise Refused('service cannot traverse publication parent')
    no_acl(fd)

def open_parent(path, gid):
    fd=os.open('/',DIR)
    try:
        parent_check(fd,0,gid)
        for part in Path(path).parts[1:]:
            nxt=os.open(part,DIR,dir_fd=fd)
            os.close(fd); fd=nxt
            parent_check(fd,0,gid)
        result=fd; fd=-1; return result
    finally:
        if fd!=-1: os.close(fd)

def absent(fd,name):
    try: os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError: return
    raise Refused('existing target refused: '+name)

def check_targets(fds,owner,gid):
    if len(fds)!=3: raise Refused('three publication parents required')
    for fd,name in zip(fds,NAMES):
        parent_check(fd,owner,gid); absent(fd,name)
        if any(n.startswith(PREFIX) for n in os.listdir(fd)):
            raise Refused('abandoned S7D staging directory; review before retry')

def safe_parts(name):
    if not isinstance(name,str) or '\\' in name or ':' in name or any(p in ('','.','..') for p in name.split('/')):
        raise Refused('unsafe relative file path')
    return name.split('/')

def directory_paths(files):
    dirs=set()
    for n in files:
        p=safe_parts(n)
        dirs.update('/'.join(p[:i]) for i in range(1,len(p)))
    return dirs

def set_meta(fd,uid,gid,mode):
    os.fchown(fd,uid,gid); os.fchmod(fd,mode); no_acl(fd); os.fsync(fd)

def check_meta(fd,uid,gid,mode,directory):
    s=os.fstat(fd)
    if (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(uid,gid,mode) or not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink==1):
        raise Refused('published metadata mismatch')
    no_acl(fd)

def write_tree(fd,files,uid,gid):
    # Traverse only newly created, root-owned directories using no-follow FDs.
    for rel in sorted(directory_paths(files),key=lambda x:(x.count('/'),x)):
        parts=safe_parts(rel)
        with ExitStack() as stack:
            pfd=fd
            for part in parts[:-1]:
                pfd=os.open(part,DIR,dir_fd=pfd); stack.callback(os.close,pfd)
            os.mkdir(parts[-1],0o700,dir_fd=pfd)
            nfd=os.open(parts[-1],DIR,dir_fd=pfd); stack.callback(os.close,nfd)
            set_meta(nfd,uid,gid,0o750); os.fsync(pfd)
    for rel,data in sorted(files.items()):
        parts=safe_parts(rel)
        with ExitStack() as stack:
            pfd=fd
            for part in parts[:-1]:
                pfd=os.open(part,DIR,dir_fd=pfd); stack.callback(os.close,pfd)
            out=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=pfd)
            with os.fdopen(out,'wb') as stream:
                stream.write(data); stream.flush(); set_meta(stream.fileno(),uid,gid,0o640)
            os.fsync(pfd)

def audit_tree(fd,files,uid,gid,mode):
    dirs=directory_paths(files)
    def visit(dfd,prefix):
        check_meta(dfd,uid,gid,mode if not prefix else 0o750,True)
        names={n[len(prefix):].split('/')[0] for n in dirs|set(files) if n.startswith(prefix)}
        if set(os.listdir(dfd))!=names: raise Refused('unexpected publication inventory')
        for name in sorted(names):
            rel=prefix+name
            if rel in dirs:
                child=os.open(name,DIR,dir_fd=dfd)
                try: visit(child,rel+'/')
                finally: os.close(child)
            else:
                child=os.open(name,FILE|os.O_NONBLOCK,dir_fd=dfd)
                with os.fdopen(child,'rb') as stream:
                    check_meta(stream.fileno(),uid,gid,0o640,False)
                    if stream.read(len(files[rel])+1)!=files[rel]: raise Refused('published bytes mismatch: '+rel)
    visit(fd,'')

def publish(fds,payloads,*,owner,uid,gid,approved_plan):
    """Shared native/fixture engine. Each directory atomic, transaction not atomic.
    Retain stages and published targets on any failure; never delete or retry.
    """
    if sys.platform!='linux' or plan(payloads)['plan_sha256']!=approved_plan:
        raise Refused('Linux and exact approved plan required')
    if len(fds)!=3 or len({(os.fstat(f).st_dev,os.fstat(f).st_ino) for f in fds})!=3:
        raise Refused('distinct parent directories required')
    check_targets(fds,owner,gid)
    stages=[]; published=[]
    try:
        for i,(fd,files) in enumerate(zip(fds,payloads)):
            name=PREFIX+uuid.uuid4().hex
            os.mkdir(name,0o700,dir_fd=fd); stages.append((i,name))
            stage=os.open(name,DIR,dir_fd=fd)
            try:
                if i==2: set_meta(stage,uid,gid,0o700)
                else:
                    write_tree(stage,files,owner,gid); set_meta(stage,owner,gid,0o750)
                audit_tree(stage,files,uid if i==2 else owner,gid,0o700 if i==2 else 0o750)
            finally: os.close(stage)
            os.fsync(fd)
        for i,name in stages:
            fd=fds[i]; rename_noreplace(fd,name,NAMES[i]); published.append(i); os.fsync(fd)
        for i,(fd,files) in enumerate(zip(fds,payloads)):
            child=os.open(NAMES[i],DIR,dir_fd=fd)
            try: audit_tree(child,files,uid if i==2 else owner,gid,0o700 if i==2 else 0o750)
            finally: os.close(child)
        return {'status':'INACTIVE_PUBLICATION_VERIFIED','plan_sha256':approved_plan,
                'files':17,'directories_published':3,'service_registered':False,
                'credential_enrolled':False,'activation_performed':False}
    except Exception as exc:
        raise Refused('INCOMPLETE: published indices='+str(published)+'; stages='+str(stages)+'; preserve evidence; '+str(exc)) from exc

def check_unit_absent(gid):
    fd=open_parent('/etc/systemd/system',gid)
    try: absent(fd,Path(contract.UNIT).name)
    finally: os.close(fd)
    # Detect a loaded, generated, linked or vendor unit as well as the fixed file.
    proc=subprocess.run(['/usr/bin/systemctl','show','--no-pager',
                         '--property=LoadState','--property=ActiveState',
                         Path(contract.UNIT).name],capture_output=True,text=True,timeout=8)
    if proc.returncode not in (0,1) or set(proc.stdout.splitlines())!={'LoadState=not-found','ActiveState=inactive'}:
        raise Refused('v1 unit not proven absent and inactive')

def native_preflight():
    """Root metadata-only check. Missing dedicated account is expected pending work."""
    native_guard()
    import pwd,grp
    found=[]
    for lookup in (pwd.getpwnam,grp.getgrnam):
        try: lookup(contract.IDENTITY); found.append(True)
        except KeyError: found.append(False)
    if found==[False,False]: uid,gid=None,None
    elif found==[True,True]: uid,gid=identity()
    else: raise Refused('partial dedicated service identity exists')
    # Use a sentinel gid when no service identity exists, so traversal must be
    # available to other users. Revalidate with actual gid before publication.
    check_gid=gid if gid is not None else -1
    with ExitStack() as stack:
        fds=[]
        for parent in PARENTS:
            fd=open_parent(parent,check_gid); stack.callback(os.close,fd); fds.append(fd)
        check_targets(fds,0,check_gid); check_unit_absent(check_gid)
    return {'status':'NATIVE_PREREQUISITES_READY' if uid is not None else 'ACCOUNT_PROVISIONING_REQUIRED',
            'hostname':platform.node(),'architecture':platform.machine(),
            'targets_absent':list(TARGETS),'unit_absent':True,'service_uid':uid,'service_gid':gid,
            'filesystem_writes':False,'service_changes':False,'credential_contents_read':False}

def native_publish(payloads,approved_plan):
    native_guard(); uid,gid=identity()
    with ExitStack() as stack:
        fds=[]
        for parent in PARENTS:
            fd=open_parent(parent,gid); stack.callback(os.close,fd); fds.append(fd)
        check_unit_absent(gid)
        return publish(fds,payloads,owner=0,uid=uid,gid=gid,approved_plan=approved_plan)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True); p.add_argument('--config',type=Path,required=True)
    p.add_argument('--install-inactive',action='store_true'); p.add_argument('--approve-plan-sha256')
    p.add_argument('--native-preflight',action='store_true')
    a=p.parse_args(argv)
    try:
        payloads=candidates(a.bundle,a.config); preview=plan(payloads)
        if a.native_preflight:
            if a.install_inactive or a.approve_plan_sha256: raise Refused('preflight cannot be combined with installation')
            preview=dict(preview,native_preflight=native_preflight())
        elif a.install_inactive or a.approve_plan_sha256:
            if not a.install_inactive or a.approve_plan_sha256!=preview['plan_sha256']:
                raise Refused('explicit install and exact plan hash required')
            preview=native_publish(payloads,a.approve_plan_sha256)
        print(json.dumps(preview,sort_keys=True,separators=(',',':'))); return 0
    except (ValueError,OSError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
        print('STOP: '+str(exc),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
