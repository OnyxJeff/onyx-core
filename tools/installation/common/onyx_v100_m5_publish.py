#!/usr/bin/env python3
"""M5-S2C inactive code-only publication. No activation, state or credential I/O."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import uuid
import zipfile

COMMIT = 'a8ca64b2d06940952f6181a52b9682c0b75bcad6'
TREE = '15e8e437ec3e4b4bdc9301777ec39d450e29918c'
HASHES = {'windows':'059d08c6e5b53141fc5faa4a43e7d4ab03ed6cd849c81eb91ed388688cf51a7c',
          'pi-armv6':'01b258d647ca843eac7f103d6b1c2e73eb1b1cedf7c17c7c4545a62f05149466'}
COUNTS = {'windows':24, 'pi-armv6':11}
MANIFEST = 'm5-candidate-manifest.json'
RECEIPT = 'm5-publication-inventory.json'
OLD_RECEIPT = 'c4c4fc7035d5010770511d254e49007b8ac583556b9ccca919c271092eb810fe'
ACL_HASHES = {'a348c46820ae7a0343c8084fb2d760bbc1301bda7acaac850c4ea37710de7ead',
              '865006780490c0329a922374d31fb40b449c4be43153bf2fc7c54308e66a868e'}
WIN_TARGET = 'OnyxCore-v100-Inactive-M5-a8ca64b'
WIN_OLD = 'OnyxCore-v100-Inactive-Stable100'
PI_PARENT = Path('/opt/onyxcore')
PI_TARGET = 'v1.0.0-m5-a8ca64b'
class Refused(ValueError): pass

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(x): return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode('ascii')
def parts(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',name) or any(p in ('','.','..') or p.endswith('.') for p in name.split('/')):
        raise Refused('unsafe inventory path')
    return name.split('/')

def plain(path):
    if not path.is_absolute() or '..' in path.parts: raise Refused('absolute path required')
    for node in (*reversed(path.parents),path):
        try: s=node.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400: raise Refused('redirected path refused')

def read_regular(path,limit):
    plain(path); s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>limit: raise Refused('unsafe regular input')
    with path.open('rb') as stream: raw=stream.read(limit+1)
    if len(raw)>limit: raise Refused('input exceeds limit')
    return raw

def archive_files(raw,role):
    # Authenticate before interpreting archive metadata; manifest alone is not trust.
    if len(raw)>8*1024*1024 or sha(raw)!=HASHES[role]: raise Refused('accepted archive hash differs')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=z.namelist()
        if len(names)!=COUNTS[role]+1 or len(set(n.lower() for n in names))!=len(names): raise Refused('archive inventory differs')
        for entry in z.infolist():
            parts(entry.filename)
            if entry.is_dir() or entry.external_attr>>16 != 0o100644 or entry.file_size>512*1024: raise Refused('unsafe archive entry')
        files={n:z.read(n) for n in names}
    m=json.loads(files[MANIFEST]); rows=m['files']
    if (m['role']!=role or m['source_commit']!=COMMIT or m['source_tree']!=TREE or m['activation_performed'] is not False or m['installation_performed'] is not False or m['native_installation_approved'] is not False or m['credential_files_included'] is not False): raise Refused('candidate manifest differs')
    if len(rows)!=COUNTS[role] or {r['path'] for r in rows}!=set(files)-{MANIFEST}: raise Refused('manifest inventory differs')
    for r in rows:
        b=files[r['path']]
        if len(b)!=r['size'] or sha(b)!=r['sha256']: raise Refused('manifest payload differs')
    return files

def dirs(files):
    return {'/'.join(parts(n)[:i]) for n in files for i in range(1,len(parts(n)))}

def inventory(files,role,config=None):
    out=dict(files)
    if role=='windows':
        if config is None: raise Refused('verified existing Windows configuration required')
        out['config/windows.config.json']=config
    elif config is not None: raise Refused('Pi configuration must remain external')
    out[RECEIPT]=canonical({'schema_version':1,'operation':'INACTIVE_CODE_PUBLICATION_INVENTORY', 'role':role,'source_commit':COMMIT,'archive_sha256':HASHES[role], 'activation_performed':False,'service_or_task_changes':False,'credential_contents_read':False,'state_modified':False,'files':[{'path':n,'size':len(b),'sha256':sha(b)} for n,b in sorted(out.items())]})
    return out

def plan(files,role):
    report={'role':role,'source_commit':COMMIT,'archive_sha256':HASHES[role], 'target':WIN_TARGET if role=='windows' else (PI_PARENT/PI_TARGET).as_posix(), 'file_count':len(files), 'files':[{ 'path':n,'sha256':sha(b),'size':len(b)} for n,b in sorted(files.items())], 'activation_performed':False,'state_modified':False}
    return dict(report,plan_sha256=sha(canonical(report)))

def windows_config(old):
    raw=read_regular(old/'installation-receipt.json',65536)
    if sha(raw)!=OLD_RECEIPT: raise Refused('old receipt differs')
    receipt=json.loads(raw); rows=receipt['installed_files']
    if len(rows)!=16 or len({r['path'] for r in rows})!=16: raise Refused('rollback inventory differs')
    config=None
    for row in rows:
        rel=row['path']; b=read_regular(old.joinpath(*parts(rel)),512*1024)
        if len(b)!=row['size'] or sha(b)!=row['sha256']: raise Refused('rollback payload differs: '+rel)
        if rel=='config/windows.config.json': config=b
    if config is None: raise Refused('configuration not bound by old receipt')
    return config

def verify_tree(root,files):
    plain(root)
    actual=set(); actual_dirs=set()
    for base, subdirs, names in os.walk(root,followlinks=False):
        for n in subdirs:
            p=Path(base)/n; plain(p); actual_dirs.add(p.relative_to(root).as_posix())
        for n in names:
            p=Path(base)/n; rel=p.relative_to(root).as_posix(); actual.add(rel)
            if rel not in files or read_regular(p,512*1024)!=files[rel]: raise Refused('published payload differs')
    if actual!=set(files) or actual_dirs!=dirs(files): raise Refused('published inventory differs')

def absent(p):
    try: p.lstat()
    except FileNotFoundError: return
    raise Refused('destination already exists')

def win_guard():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,13) or ctypes.windll.shell32.IsUserAnAdmin(): raise Refused('non-elevated native Windows Python 3.13 required')
    root=Path(os.environ['LOCALAPPDATA']); plain(root)
    # SHGetFolderPathW(CSIDL_LOCAL_APPDATA) independently verifies environment.
    buf=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,0x1c,None,0,buf)!=0 or root!=Path(buf.value): raise Refused('LocalAppData identity differs')
    return root

def win_rename_noreplace(stage,target):
    f=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
    f.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32]; f.restype=ctypes.c_int
    if not f(str(stage),str(target),0): raise Refused('no-replace publication failed')

def win_publish(root,files,helper):
    target=root/WIN_TARGET; absent(target)
    if any(p.name.startswith('.OnyxCore-v100-staging-M5-') for p in root.iterdir()): raise Refused('previous M5 stage requires review')
    if sha(read_regular(helper,65536)) not in ACL_HASHES: raise Refused('historical ACL helper differs')
    stage=root/('.OnyxCore-v100-staging-M5-'+uuid.uuid4().hex)
    stage.mkdir()
    ps=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    def acl(mode,node):
        if sha(read_regular(helper,65536)) not in ACL_HASHES: raise Refused('ACL helper changed')
        subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(helper),'-Mode',mode,'-Scope','User','-Root',str(root),'-ContentPath',str(node),'-ApproveInactiveUser','-ApproveUserDacl'],check=True,timeout=120)
    try:
        for n,b in sorted(files.items()):
            p=stage.joinpath(*parts(n)); p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('xb') as f: f.write(b); f.flush(); os.fsync(f.fileno())
        verify_tree(stage,files); acl('Harden',stage); verify_tree(stage,files)
        plain(root); absent(target)
        win_rename_noreplace(stage,target)
        acl('Audit',target); verify_tree(target,files)
    except Exception as exc: raise Refused('INCOMPLETE: preserve staging/target; '+str(exc)) from exc
    return target

# POSIX publication uses descriptor-relative no-follow operations and renameat2.
def dirflags(): return os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC

def no_acl(fd):
    if set(os.listxattr(fd)) & {'system.posix_acl_access','system.posix_acl_default'}: raise Refused('extended ACL requires review')

def check_meta(fd,uid,gid,mode,is_dir):
    s=os.fstat(fd); no_acl(fd)
    if (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(uid,gid,mode) or not (stat.S_ISDIR(s.st_mode) if is_dir else stat.S_ISREG(s.st_mode) and s.st_nlink==1): raise Refused('publication metadata differs')

def posix_parent(path,gid):
    fd=os.open('/',dirflags())
    try:
        for part in ('',*path.parts[1:]):
            if part:
                child=os.open(part,dirflags(),dir_fd=fd); os.close(fd); fd=child
            s=os.fstat(fd); m=stat.S_IMODE(s.st_mode); no_acl(fd)
            if s.st_uid!=0 or m&0o022 or not (m&1 or s.st_gid==gid and m&0o010): raise Refused('unsafe Pi parent')
        return fd
    except BaseException: os.close(fd); raise

def posix_absent(fd,name):
    try: os.stat(name,dir_fd=fd,follow_symlinks=False)
    except FileNotFoundError: return
    raise Refused('Pi destination already exists')

def rename_noreplace(fd,old,new):
    f=getattr(ctypes.CDLL(None,use_errno=True),'renameat2',None)
    if f is None: raise Refused('renameat2 unavailable')
    f.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]; f.restype=ctypes.c_int
    if f(fd,old.encode('ascii'),fd,new.encode('ascii'),1): raise Refused('atomic no-replace publication refused')

def write_posix(fd,files,uid,gid):
    # Each node is created exclusively under the new owner-controlled stage.
    def visit(parent,prefix):
        names=sorted({n[len(prefix):].split('/')[0] for n in files if n.startswith(prefix)})
        for name in names:
            rel=prefix+name
            if rel in files:
                f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
                with os.fdopen(f,'wb') as stream:
                    stream.write(files[rel]); stream.flush(); os.fchown(f,uid,gid); os.fchmod(f,0o640); no_acl(f); os.fsync(f)
            else:
                os.mkdir(name,0o700,dir_fd=parent); child=os.open(name,dirflags(),dir_fd=parent)
                try: visit(child,rel+'/'); os.fchown(child,uid,gid); os.fchmod(child,0o750); no_acl(child); os.fsync(child)
                finally: os.close(child)
        os.fsync(parent)
    visit(fd,''); os.fchown(fd,uid,gid); os.fchmod(fd,0o750); no_acl(fd); os.fsync(fd)

def audit_posix(fd,files,uid,gid):
    def visit(parent,prefix):
        check_meta(parent,uid,gid,0o750,True)
        names={n[len(prefix):].split('/')[0] for n in files if n.startswith(prefix)}
        if set(os.listdir(parent))!=names: raise Refused('Pi inventory differs')
        for name in names:
            rel=prefix+name
            if rel in files:
                f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
                with os.fdopen(f,'rb') as stream:
                    check_meta(f,uid,gid,0o640,False)
                    if stream.read(len(files[rel])+1)!=files[rel]: raise Refused('Pi bytes differ')
            else:
                child=os.open(name,dirflags(),dir_fd=parent)
                try: visit(child,rel+'/')
                finally: os.close(child)
    visit(fd,'')

def posix_publish(fd,target,files,uid,gid):
    posix_absent(fd,target)
    if any(n.startswith('.onyx-v100-m5-stage-') for n in os.listdir(fd)): raise Refused('previous M5 stage requires review')
    stage='.onyx-v100-m5-stage-'+uuid.uuid4().hex
    os.mkdir(stage,0o700,dir_fd=fd)
    try:
        child=os.open(stage,dirflags(),dir_fd=fd)
        try: write_posix(child,files,uid,gid); audit_posix(child,files,uid,gid)
        finally: os.close(child)
        os.fsync(fd); rename_noreplace(fd,stage,target); os.fsync(fd)
        child=os.open(target,dirflags(),dir_fd=fd)
        try: audit_posix(child,files,uid,gid)
        finally: os.close(child)
    except Exception as exc: raise Refused('INCOMPLETE: preserve stage/target; '+str(exc)) from exc

def pi_guard():
    if sys.platform!='linux' or platform.machine()!='armv6l' or sys.version_info[:2]!=(3,13) or os.geteuid()!=0: raise Refused('native root ARMv6 Linux Python 3.13 required')
    if 'VERSION_CODENAME=trixie' not in Path('/etc/os-release').read_text().splitlines(): raise Refused('Trixie required')
    import pwd,grp
    u=pwd.getpwnam('onyxcore-v100'); g=grp.getgrnam('onyxcore-v100')
    if u.pw_uid<=0 or g.gr_gid<=0 or u.pw_gid!=g.gr_gid or u.pw_dir!='/nonexistent' or u.pw_shell not in ('/usr/sbin/nologin','/sbin/nologin','/bin/false','/usr/bin/false') or set(os.getgrouplist(u.pw_name,g.gr_gid))!={g.gr_gid} or set(g.gr_mem)-{u.pw_name} or any(x.pw_name!=u.pw_name and (x.pw_uid==u.pw_uid or x.pw_gid==g.gr_gid) for x in pwd.getpwall()) or any(x.gr_name!=g.gr_name and x.gr_gid==g.gr_gid for x in grp.getgrall()): raise Refused('dedicated account differs')
    for path,uid,mode in [('/opt/onyxcore/v1.0.0',0,0o750),('/etc/onyxcore-v100',0,0o750),('/var/lib/onyxcore-v100',u.pw_uid,0o700)]:
        plain(Path(path)); fd=os.open(path,dirflags())
        try: check_meta(fd,uid,g.gr_gid,mode,True)
        finally: os.close(fd)
    return g.gr_gid

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('mode',choices=['plan','publish']); p.add_argument('--role',required=True,choices=HASHES); p.add_argument('--archive',required=True,type=Path); p.add_argument('--acl-helper',type=Path); p.add_argument('--approve-publication',action='store_true'); p.add_argument('--approved-plan')
    a=p.parse_args(argv)
    try:
        if a.mode=='plan' and (a.approve_publication or a.approved_plan or a.acl_helper): raise Refused('plan does not accept write options')
        if a.mode=='publish' and (not a.approve_publication or not a.approved_plan): raise Refused('explicit publication approval and plan hash required')
        raw=read_regular(a.archive,8*1024*1024); files=archive_files(raw,a.role)
        if a.role=='windows':
            root=win_guard(); config=windows_config(root/WIN_OLD); absent(root/WIN_TARGET)
            files=inventory(files,a.role,config)
        else:
            if a.acl_helper: raise Refused('Pi cannot accept Windows ACL helper')
            files=inventory(files,a.role)
        report=plan(files,a.role)
        if a.mode=='plan': print(canonical(report).decode().strip()); return 0
        if report['plan_sha256']!=a.approved_plan: raise Refused('approved plan differs')
        if a.role=='windows':
            if a.acl_helper is None: raise Refused('reviewed ACL helper required')
            target=win_publish(root,files,a.acl_helper)
        else:
            gid=pi_guard(); fd=posix_parent(PI_PARENT,gid)
            try: posix_publish(fd,PI_TARGET,files,0,gid)
            finally: os.close(fd)
            target=PI_PARENT/PI_TARGET
        print(canonical({'status':'INACTIVE_PUBLICATION_VERIFIED','target':str(target),'plan_sha256':report['plan_sha256'],'file_count':len(files),'activation_performed':False,'state_modified':False,'credential_contents_read':False}).decode().strip()); return 0
    except (OSError,ValueError,KeyError,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print('STOP: '+str(exc),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
