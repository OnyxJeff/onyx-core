#!/usr/bin/env python3
"""ONYX CORE v0.9.0: verify inactive installation and print proposed launch plan.

This script cannot register tasks, start services, enroll credentials or change
config. It only reads an M3 installation receipt, validates every staged file,
and prints canonical JSON for human review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

COMMIT=re.compile(r'[0-9a-f]{40}\Z')
SHA=re.compile(r'[0-9a-f]{64}\Z')
RELEASE=re.compile(r'0\.9\.0(?:[-.][A-Za-z0-9.-]+)?\Z')

class PlanRefused(ValueError):pass


def _canonical(x):
    return (json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=True)+'\n').encode('ascii')


def _sha(file):
    h=hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def _no_redirects(path, root):
    if not path.is_relative_to(root):raise PlanRefused('path outside installed root')
    cur=path
    while True:
        if cur.is_symlink() or (hasattr(cur,'is_junction') and cur.is_junction()):
            raise PlanRefused('redirected installation file')
        if cur==root:break
        cur=cur.parent


def audit_install(root, expected_commit, platform):
    root=Path(root)
    if not root.is_absolute() or '..' in root.parts or root.is_symlink() or (hasattr(root,'is_junction') and root.is_junction()):
        raise PlanRefused('absolute, nonredirected installation root required')
    if not COMMIT.fullmatch(expected_commit):raise PlanRefused('full expected commit required')
    if platform not in ('windows','pi-armv6'):raise PlanRefused('unknown platform')
    for name in ('manifest.json','installation-receipt.json'):
        _no_redirects(root/name,root)
    manifest_raw=(root/'manifest.json').read_bytes()
    receipt_raw=(root/'installation-receipt.json').read_bytes()
    manifest=json.loads(manifest_raw)
    receipt=json.loads(receipt_raw)
    if type(manifest)!=dict or set(manifest)!={'schema_version','product','version','platform','source_commit','files'} or _canonical(manifest)!=manifest_raw:
        raise PlanRefused('invalid installed manifest')
    if (manifest['schema_version']!=1 or manifest['product']!='ONYX CORE' or
        manifest['platform']!=platform or manifest['source_commit']!=expected_commit or
        type(manifest['version'])!=str or not RELEASE.fullmatch(manifest['version'])):
        raise PlanRefused('installed platform/version/source mismatch')
    if type(receipt)!=dict or set(receipt)!={'status','platform','version','source_commit','archive_sha256','target','file_count','activated','mode'} or _canonical(receipt)!=receipt_raw:
        raise PlanRefused('invalid inactive install receipt')
    if (receipt['status']!='PREPARED' or receipt['activated'] is not False or receipt['mode']!='inactive-code-only' or
        receipt['platform']!=platform or receipt['version']!=manifest['version'] or
        receipt['source_commit']!=expected_commit or receipt['target']!=str(root) or
        type(receipt['archive_sha256'])!=str or not SHA.fullmatch(receipt['archive_sha256'])):
        raise PlanRefused('untrusted or activated installation receipt')
    rows=manifest['files']
    if type(rows)!=list or not rows or type(receipt['file_count'])!=int or receipt['file_count']!=len(rows):
        raise PlanRefused('invalid staged inventory')
    names=[]
    for row in rows:
        if type(row)!=dict or set(row)!={'path','size','sha256'}:raise PlanRefused('invalid staged inventory entry')
        name=row['path']
        if (type(name)!=str or not name or name.startswith('/') or '\\' in name or
            any(s in ('','.','..') for s in name.split('/')) or name in names or
            type(row['size'])!=int or row['size']<0 or type(row['sha256'])!=str or not SHA.fullmatch(row['sha256'])):
            raise PlanRefused('invalid staged file entry')
        file=root.joinpath(*name.split('/'))
        _no_redirects(file,root)
        if not file.is_file() or file.stat().st_size!=row['size'] or _sha(file)!=row['sha256']:
            raise PlanRefused('source file differs from package manifest')
        names.append(name)
    if names!=sorted(names):raise PlanRefused('unsorted staged inventory')
    allowed={*names,'manifest.json','installation-receipt.json'}
    extras={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if extras!=allowed:raise PlanRefused('unexpected installation file or missing manifest entry')
    essential={
        'windows':('windows/collector/Send-OnyxTelemetry.ps1','windows/collector/Launch-OnyxTelemetry.vbs',
                   'windows/gateway/OnyxGateway.py','windows/gateway/gateway-dashboard.html'),
        'pi-armv6':('pi/services/receiver/receiver.py','pi/services/receiver/integrated_store.py',
                    'pi/services/receiver/history.py','pi/services/receiver/health.py',
                    'tools/installation/pi/launch-onyx-v090-receiver.sh',
                    'tools/installation/pi/onyxcore-v090-receiver.service',
                    'tools/installation/pi/90-onyx-v090-receiver')}
    if any(name not in names for name in essential[platform]):
        raise PlanRefused('required versioned startup component missing')
    return {'root':str(root),'source_commit':expected_commit,'version':manifest['version'],
            'archive_sha256':receipt['archive_sha256'],'platform':platform,'files_verified':len(rows)}


def plan(root,expected_commit,platform):
    audit=audit_install(root,expected_commit,platform)
    root=str(root)
    if platform=='pi-armv6':
        result={
          'proposed_systemd_unit':'onyxcore-v090-receiver.service',
          'unit_source':str(Path(root)/'tools/installation/pi/onyxcore-v090-receiver.service'),
          'dispatcher_source':str(Path(root)/'tools/installation/pi/90-onyx-v090-receiver'),
          'unit_target':'/etc/systemd/system/onyxcore-v090-receiver.service',
          'dispatcher_target':'/etc/NetworkManager/dispatcher.d/90-onyx-v090-receiver',
          'script_target':'/opt/onyxcore/v0.9.0/tools/installation/pi/launch-onyx-v090-receiver.sh',
          'database_path':'/var/lib/onyxcore/telemetry.db',
          'snapshot_path':'/var/lib/onyxcore/latest-snapshot.json',
          'token_path':'/etc/onyxcore/receiver.env',
          'port':8765,
          'cutover_condition':'Stop legacy receiver before any candidate receiver activation; never bind both to port 8765'}
    else:
        result={
          'candidate_task_names':['ONYX CORE v0.9 - Telemetry Collector (Candidate)',
                                  'ONYX CORE v0.9 - Local Gateway (Candidate)'],
          'collector_source':str(Path(root)/'windows/collector/Launch-OnyxTelemetry.vbs'),
          'gateway_source':str(Path(root)/'windows/gateway/OnyxGateway.py'),
          'dashboard_source':str(Path(root)/'windows/gateway/gateway-dashboard.html'),
          'python_runtime':'C:\\Python313\\python.exe',
          'powershell_requirement':'Windows PowerShell 5.1',
          'credential_mode':'DPAPI CurrentUser; no credential copy or reenrollment',
          'candidate_gateway_loopback_port':18769,
          'production_gateway_reserved_port':18766,
          'monitoring_activation':'DISABLED; protected v0.8 operator cannot be relabeled as v0.9',
          'cutover_condition':'No existing task replaced; operator approval and native-host acceptance required'}
    return {'schema_version':1,'operation':'READ_ONLY_ACTIVATION_PLAN','activated':False,
            'audit':audit,'proposal':result}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--installed-root',type=Path,required=True)
    p.add_argument('--platform',choices=('windows','pi-armv6'),required=True)
    p.add_argument('--expected-commit',required=True)
    a=p.parse_args(argv)
    try:
        print(_canonical(plan(a.installed_root,a.expected_commit,a.platform)).decode('ascii').strip())
        return 0
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        print('STOP: '+str(exc),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
