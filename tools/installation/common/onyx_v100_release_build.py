#!/usr/bin/env python3
"""S6 deterministic release builder. Source and output are offline only."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import onyx_v100_m5_candidate as candidate
import onyx_v100_m5_collector_hotfix as hotfix
import onyx_v100_m5_publish as publish

MANIFEST = 'release-manifest.json'
BASES = {'windows': hotfix.BASE_SHA, 'pi-armv6': publish.HASHES['pi-armv6']}
S5 = 'ae15a99f7fdbd90e5f0fe339260abcc89729a671633c0d913f7709324b7298ef'
COMMON = 'tools/installation/common/'
INSTALL = COMMON + 'onyx_v100_release_install.py'
GUIDE = 'docs/v1.0.0/M5_S6_INSTALLATION.md'
HELPER = 'tools/installation/windows/Set-OnyxV100SafeUserDacl.ps1'
PUBLISH = COMMON + 'onyx_v100_m5_publish.py'
FIXED = {PUBLISH: 'c00e8f7f72212a7f3b2023c5400dd8b3f71167bc16aa382f182a1014dd0f4c5f',
         HELPER: '865006780490c0329a922374d31fb40b449c4be43153bf2fc7c54308e66a868e'}


def read(repo, name):
    return publish.read_regular(repo.joinpath(*name.split('/')), 512*1024).replace(b'\r\n', b'\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def payload(repo, role):
    if role not in BASES:
        raise ValueError('Unsupported role')
    data = {n: read(repo, n) for n in candidate.ROLES[role]}
    base = candidate.zip_bytes(role, data)
    if sha(base) != BASES[role]:
        raise ValueError('Accepted M5 bytes differ')
    if role == 'windows':
        base = hotfix.candidate(base, read(repo, hotfix.SOURCE_LAUNCHER))
        if sha(base) != S5:
            raise ValueError('Accepted S5 bytes differ')
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        result = {n: z.read(n) for n in z.namelist() if n != candidate.MANIFEST}
    if role == 'windows':
        for name in (candidate.DASHBOARD, candidate.DASH_ALIAS):
            result[name] = candidate.once(result[name], b'WINDOWS / PI CONNECTIVITY \xe2\x80\x94 v0.8',
                                          b'WINDOWS / PI CONNECTIVITY \xe2\x80\x94 v1.0.0')
    extras = [INSTALL, GUIDE, PUBLISH] + (
        [HELPER, COMMON+'onyx_v100_release_windows_activation.py',
         'tools/installation/windows/Invoke-OnyxV100ReleaseActivation.ps1'] if role == 'windows' else
        [COMMON+'onyx_v100_release_pi_activation.py'])
    for name in extras:
        raw = read(repo, name)
        if name in FIXED and sha(raw) != FIXED[name]:
            raise ValueError('Reviewed installation dependency differs: ' + name)
        result[name] = raw
    manifest = {'schema_version': 1, 'release_version': '1.0.0',
                'kind': 'onyxcore-v100-release-candidate', 'role': role,
                'runtime_source_commit': candidate.COMMIT,
                'runtime_source_tree': candidate.TREE,
                'accepted_runtime_sha256': sha(base),
                'credential_files_included': False, 'native_qualified': False,
                'files': [{'path': n, 'size': len(b), 'sha256': sha(b)} for n,b in sorted(result.items())]}
    result[MANIFEST] = publish.canonical(manifest)
    return result


def archive(repo, role):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', allowZip64=False) as z:
        for name, raw in sorted(payload(repo, role).items()):
            info = zipfile.ZipInfo(name, (1980,1,1,0,0,0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, raw)
    return out.getvalue()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('build','verify'))
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--role', choices=sorted(BASES), required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    try:
        publish.plain(a.repo); publish.plain(a.output)
        if a.output.resolve().is_relative_to(a.repo.resolve()):
            raise ValueError('Output must be outside source')
        raw = archive(a.repo, a.role)
        if a.operation == 'build':
            with a.output.open('xb') as f:
                f.write(raw)
        if publish.read_regular(a.output, 8*1024*1024) != raw:
            raise ValueError('Artifact differs')
        print(json.dumps({'role': a.role, 'archive_sha256': sha(raw), 'bytes': len(raw), 'native_qualified': False}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print('STOP: '+str(exc), file=sys.stderr); return 2

if __name__ == '__main__':
    sys.exit(main())
