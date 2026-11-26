#!/usr/bin/env python3
"""Authenticated clean Windows preparation, activation and rollback dispatcher.

Native executor is part of the authenticated installed release; it is not a
standalone operator interface. Never use this clean workflow on an existing host.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import onyx_v100_release_install as install
from onyx_v100_config import load_config

DRIVER='tools/installation/windows/Invoke-OnyxV100ReleaseActivation.ps1'
native=install.native
APPROVALS={'prepare':(True,False,False),'activate':(False,True,False),'rollback':(False,False,True)}


def require(condition,message):
    if not condition:
        raise ValueError(message)


def driver_input(report,cfg,peer):
    require(report['role']=='windows','Windows plan required')
    require(report['activation']['root']==report['target'],'Runtime target differs')
    require([t['task_name'] for t in report['activation']['tasks']]==list(install.WIN_TASKS),'Task names differ')
    # No credential or user-supplied command language in this transport.
    return {'schema_version':1,'plan_sha256':report['plan_sha256'],'activation':report['activation'],
        'source':cfg['collector']['source'],'gateway_port':cfg['gateway']['port'],
        'network_adapter':cfg['collector']['network_adapter'],'usb_adapter':cfg['usb']['adapter_name'],
        'receiver':cfg['receiver'],'cpu_temperature_enabled':cfg.get('cpu_temperature',{}).get('enabled',False),
        'pi_subnet':peer['receiver']['ipv4_subnet']}


def execute(operation,data,report,cfg,peer):
    root=native.win_guard()
    require(sys.getwindowsversion().build>=22000,'Windows 11 required')
    target=root/install.WIN_NAME
    require(str(target).casefold()==report['target'].casefold(),'Native user root differs')
    native.verify_tree(target,data)
    for p in root.iterdir():
        if p.name.lower().startswith(('onyxcore','.onyxcore')) and p.name.casefold() not in {install.WIN_NAME.casefold(),'onyxcore-v100'}:
            raise ValueError('Other ONYX installation or incomplete stage requires review')
    helper=target.joinpath(*install.HELPER.split('/'))
    driver=target.joinpath(*DRIVER.split('/'))
    require(native.read_regular(helper,65536)==data[install.HELPER],'ACL helper differs')
    require(native.read_regular(driver,128*1024)==data[DRIVER],'Activation driver differs')
    systemroot=Path(os.environ['SystemRoot'])
    ps=systemroot/'System32/WindowsPowerShell/v1.0/powershell.exe'
    for p in (ps,*(Path(t['execute']) for t in report['activation']['tasks'])):
        native.plain(p); require(p.is_file(),'Native executable missing')
    require(Path(report['activation']['tasks'][1]['execute']).parent.parent==systemroot,'Native SystemRoot differs')
    subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(helper),'-Mode','Audit','-Scope','User',
                    '-Root',str(root),'-ContentPath',str(target),'-ApproveInactiveUser','-ApproveUserDacl'],
                   check=True,timeout=120)
    native.verify_tree(target,data)
    # State must not redirect to another location; no credential contents read here.
    state=root/'OnyxCore-v100'; native.plain(state)
    if operation=='prepare': native.absent(state)
    else:
        credential=state/'collector-token.dpapi'; native.plain(credential)
        s=credential.lstat(); require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and 32<=s.st_size<=4096,'Credential metadata differs')
    # Native tasks are not installed on an existing ONYX host. The driver independently
    # checks task ownership, DACLs and exact registration identities before each write.
    encoded=base64.b64encode(json.dumps(driver_input(report,cfg,peer),ensure_ascii=True,separators=(',',':')).encode('ascii')).decode('ascii')
    args=[str(ps),'-NoProfile']+([] if operation=='prepare' else ['-NonInteractive'])
    args+=['-File',str(driver),'-Operation',operation,'-ApprovedPlan',report['plan_sha256'],'-PlanBase64',encoded,'-ApproveNativeOperation']
    # Interactive preparation inherits the terminal for a secure prompt. The token
    # never appears in arguments, input JSON, environment, or captured output.
    subprocess.run(args,check=True,timeout=600 if operation=='prepare' else 240)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=tuple(APPROVALS))
    p.add_argument('--archive',type=Path,required=True); p.add_argument('--sha256',required=True)
    p.add_argument('--config',type=Path,required=True); p.add_argument('--peer-config',type=Path,required=True)
    p.add_argument('--localappdata',required=True); p.add_argument('--pythonw',required=True); p.add_argument('--systemroot',required=True)
    p.add_argument('--approved-plan',required=True); p.add_argument('--approve-credential-preparation',action='store_true')
    p.add_argument('--approve-activation',action='store_true'); p.add_argument('--approve-active-rollback',action='store_true')
    a=p.parse_args(argv)
    try:
        require((a.approve_credential_preparation,a.approve_activation,a.approve_active_rollback)==APPROVALS[a.operation],
                'Separate explicit operation approval required')
        require(re.fullmatch('[0-9a-f]{64}',a.approved_plan) is not None,'Exact plan digest required')
        files=install.checked_archive(native.read_regular(a.archive,8*1024*1024),a.sha256,'windows')
        native.read_regular(a.config,65536); native.read_regular(a.peer_config,65536)
        cfg=load_config(a.config,'windows'); peer=load_config(a.peer_config,'pi-armv6')
        install.validate_release_pair(cfg,peer)
        data,report=install.inventory(files,cfg,'windows',a.sha256,peer=peer,localappdata=a.localappdata,pythonw=a.pythonw,systemroot=a.systemroot)
        require(report['plan_sha256']==a.approved_plan,'Approved plan differs')
        execute(a.operation,data,report,cfg,peer)
        return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print('STOP: '+(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)+'; preserve any partial changes for review',file=sys.stderr)
        return 2

if __name__=='__main__':
    sys.exit(main())
