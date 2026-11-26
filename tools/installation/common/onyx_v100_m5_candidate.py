#!/usr/bin/env python3
"""M5-S2B: deterministic, inactive runtime candidates, not a native installer.

Build exclusively from the frozen M4 Git commit. No configuration, credentials,
activation, task registration, systemd operations or history writes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import zipfile

COMMIT = 'a8ca64b2d06940952f6181a52b9682c0b75bcad6'
TREE = '15e8e437ec3e4b4bdc9301777ec39d450e29918c'
BRANCH = 'feature/v1.0.0-stable-installation'
MANIFEST = 'm5-candidate-manifest.json'
MAX_FILE = 512 * 1024
MAX_ZIP = 8 * 1024 * 1024
COMMON = ('tools/installation/common/onyx_v100_config.py',)
WINDOWS = (
    'docs/v1.0.0/examples/windows.config.example.json',
    'windows/collector/Send-OnyxTelemetry-v100.ps1',
    'windows/gateway/OnyxGateway_v100.py',
    'windows/gateway/Get-OnyxGatewayToken.ps1',
    'windows/gateway/gateway-dashboard-v100.html',
    'windows/gateway/overlay.html',
    'windows/gateway/overlay-portrait.html',
    'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1',
    'windows/gateway/OnyxV100MonitoringView.py',
    'windows/gateway/OnyxV100MonitoringJournal.py',
    'windows/gateway/OnyxMonitoringView.py',
    'windows/monitoring/OnyxMonitorConfig.py',
    'windows/monitoring/v080/OnyxLiveIncidentHistory.py',
    'windows/monitoring/v080/OnyxContinuousMonitor.py',
    'windows/monitoring/v080/OnyxLiveConnectivity.py',
    'windows/monitoring/v080/OnyxWindowsJobRunner.py',
    'windows/monitoring/v080/OnyxWindowsNativeAdmission.py',
    'windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1',
    'windows/networking/Test-OnyxUsbIcsReadiness.ps1',
    'windows/monitoring/v100/OnyxV100RecoveryAssessment.py',
    'windows/monitoring/v100/OnyxV100SupervisedRecorder.py',
    'windows/monitoring/v100/Test-OnyxV100JournalStorage.ps1',
)
PI = (
    'docs/v1.0.0/examples/pi-armv6.config.example.json',
    'docs/v1.0.0/examples/pi-armv6.system.config.example.json',
    'pi/services/receiver/receiver_v100.py',
    'pi/services/receiver/integrated_store_v100.py',
    'pi/services/receiver/history.py',
    'pi/services/receiver/health.py',
    'pi/services/receiver/dashboard.html',
    'tools/installation/pi/onyx_v100_pi_launch.py',
    'tools/installation/pi/onyx_v100_usb_binding.py',
    'tools/installation/pi/onyx_v100_pi_readiness.py',
)
ROLES = {"windows": COMMON + WINDOWS, "pi-armv6": COMMON + PI}
# SHA256 pins of canonical committed inputs; verified against actual Git blobs at build.
PINS = {
    'docs/v1.0.0/examples/pi-armv6.config.example.json': '6d76bdf7986f015535529971599374839094bb4bcb6cfc51dc0ae5a265a5727c',
    'docs/v1.0.0/examples/pi-armv6.system.config.example.json': 'dbf09eaf825794600679e4e506460ffd791bb82d2b6684e8ce3d52787e37124b',
    'docs/v1.0.0/examples/windows.config.example.json': 'ade191f0e1360fd59f2ecdcdec93cad2419acb7b172d60e131fc6e46b1308fe6',
    'pi/services/receiver/dashboard.html': '7becef3a261c1ff35c1a56efd99e028ef1324bcf7e32a6792d56ba6fb1ca6179',
    'pi/services/receiver/health.py': '2d6f7307afd34d91a6e4e2eb6ea5cb43516e56e73076eb520cd0a44d7c8b5edb',
    'pi/services/receiver/history.py': '79f0279b873aaefa472c5d410181277a2200c0a3a53ce5a9ff18e2b51f45bc76',
    'pi/services/receiver/integrated_store_v100.py': 'eb7fe4f96167dcf85236e4f9cd32be553cf5c7865c5d4cdca548c9942569fca2',
    'pi/services/receiver/receiver_v100.py': '3e5ce8d05530602aeb03b9f6fe02ef2865043da21bc44e53c7c1cea758d5f2e4',
    'tools/installation/common/onyx_v100_config.py': '8795fe458581dfa7d5358ecf6f948937d014efebc1796c2bd722c9d343873e15',
    'tools/installation/pi/onyx_v100_pi_launch.py': '23c0e42e408e73a7770a78d88bc0a751a9cb8fcdf4eeba68b4f75d7974ca605e',
    'tools/installation/pi/onyx_v100_pi_readiness.py': '02dbd69bc1ae6d17e004eb03fa1c3af805d9354d4af2aad6ebadcdb46e38b8ee',
    'tools/installation/pi/onyx_v100_usb_binding.py': '85e93e62f24f59543d6cfc7b63f54b5fb611a17c47ea645e3065f93cd5464d8f',
    'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1': 'd0e92af0f93c0848b18331cbf44ce2c6592d0faf51773c2490b81563ef381e69',
    'windows/collector/Send-OnyxTelemetry-v100.ps1': 'b7f22dc7f6dee64083538fa91dd42333c7f3cb14b93a71c779223443aa558175',
    'windows/gateway/Get-OnyxGatewayToken.ps1': 'bcaf96cb7299907a9db31aee7fe5fc57fdfc8b80fd41948a052fd40eacd8b816',
    'windows/gateway/OnyxGateway_v100.py': '6db53c2ee853f0c7443ec842bc86f7cd75317e4d9741e686512315a7e3946758',
    'windows/gateway/OnyxMonitoringView.py': 'caa4819a25d835f7d11d27a7ca12e84249d6e91e1730c207905c007311ac4580',
    'windows/gateway/OnyxV100MonitoringJournal.py': '1cd0257f355710ea172a609dfe74bb7deb84293cd289d8405cc07d8ac0594492',
    'windows/gateway/OnyxV100MonitoringView.py': '9feedf7e26cb664ba9fe67b23f34bb859e0dcb5b69104fa9587fac97b9253b47',
    'windows/gateway/gateway-dashboard-v100.html': '5788f33c97c4548e6dfa6946daef5b0faaeb0b46307170f67c7b7b5a4ab7eb18',
    'windows/gateway/overlay-portrait.html': 'ff97cefa905371b093aaca470b5a1603c2b1e44a4ac1d88c3495b5492f0fbb1d',
    'windows/gateway/overlay.html': '6592119404f277fa6c424a8a9c700717d101992de45c740d647644226a2da2c5',
    'windows/monitoring/OnyxMonitorConfig.py': '0ca2969ec4fca3fa82680b5c1f20631ec1a9962f0e580b043f139b761ef935be',
    'windows/monitoring/v080/Invoke-OnyxV080WindowsReadiness.ps1': '303d4d12dc466845c46429e3f74368d3c19e17f7d55711b5de0c2f95bf2ee91a',
    'windows/monitoring/v080/OnyxContinuousMonitor.py': '3bcc2b3cf43ac41b06ded0e2501992e3bf8b4db27c3461c0265e39643e084542',
    'windows/monitoring/v080/OnyxLiveConnectivity.py': '09d152c06401dcaf886efa0239cf2587ce508aa76ae3d0a99e46386ca1ad8aea',
    'windows/monitoring/v080/OnyxLiveIncidentHistory.py': '47328b39233178aa6ef93cf710b8458485cb64330fc69097250f3c856b8ff297',
    'windows/monitoring/v080/OnyxWindowsJobRunner.py': '5ad256e7e9695f755bed095b8f953296376e2c4d19c33f2bdf2a59500d61feb5',
    'windows/monitoring/v080/OnyxWindowsNativeAdmission.py': '5ec324674dafe1ad3bd10570a2f9cd5ee788992ae5f25127170067ef39de22a0',
    'windows/monitoring/v100/OnyxV100RecoveryAssessment.py': 'b0f329077111e271a35a5b6a236325b0b67d1c5f15d7f2eeb7216dc5dd4f5d56',
    'windows/monitoring/v100/OnyxV100SupervisedRecorder.py': 'f5cf353fdad2fda7182220dc367888233ca93e26376b64acaac55678a63ba7ad',
    'windows/monitoring/v100/Test-OnyxV100JournalStorage.ps1': '704372c6bd219afd5b1759a8602f35aa8b6c79a2a5d15ebe9aa3f8ac7f347897',
    'windows/networking/Test-OnyxUsbIcsReadiness.ps1': 'b4e012e394945faa5918aad287c06a7a5baa57fe8330add777624bf47708f800',
}


class Refused(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=True, allow_nan=False) + '\n').encode('ascii')


def plain(path):
    if not path.is_absolute() or '..' in path.parts:
        raise Refused('Absolute non-traversing path required')
    for node in (*reversed(path.parents), path):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise Refused('Redirected path refused')


def git(repo, *args):
    env = os.environ.copy()
    if any(k.startswith('GIT_') for k in env):
        raise Refused('Git environment override refused')
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(repo), *args],
                            capture_output=True, timeout=30, env=env)
    if result.returncode:
        raise Refused('Git inspection failed')
    return result.stdout


def source(repo, role):
    plain(repo)
    if not repo.is_dir() or Path(os.fsdecode(git(repo, 'rev-parse', '--show-toplevel')).strip()).resolve() != repo.resolve():
        raise Refused('Expected repository root')
    if (git(repo, 'rev-parse', 'HEAD').strip() != COMMIT.encode() or
            git(repo, 'rev-parse', 'HEAD^{tree}').strip() != TREE.encode() or
            git(repo, 'branch', '--show-current').strip() != BRANCH.encode()):
        raise Refused('Frozen M4 checkpoint required')
    if git(repo, 'diff', '--name-only', 'HEAD', '--') or git(repo, 'diff', '--cached', '--name-only'):
        raise Refused('Tracked or staged changes refused')
    data = {}
    for name in ROLES[role]:
        row = git(repo, 'ls-tree', COMMIT, '--', name).decode('ascii')
        if not row.startswith(('100644 blob ', '100755 blob ')) or not row.endswith('\t' + name + '\n') or len(row.splitlines()) != 1:
            raise Refused('Missing regular committed input: ' + name)
        data[name] = git(repo, 'show', COMMIT + ':' + name)
    check_inputs(role, data)
    return data


def check_inputs(role, data):
    if set(data) != set(ROLES[role]):
        raise Refused('Input inventory differs')
    for name, raw in data.items():
        if len(raw) > MAX_FILE or sha(raw) != PINS[name]:
            raise Refused('Input fingerprint differs: ' + name)


def once(raw, old, new):
    if raw.count(old) != 1 or new in raw:
        raise Refused('Reviewed transformation signature differs')
    return raw.replace(old, new, 1)


# Preserve the M2 isolation transformations; only the M5 artifact receives them.
COLLECTOR = 'windows/collector/Send-OnyxTelemetry-v100.ps1'
HELPER = 'windows/gateway/Get-OnyxGatewayToken.ps1'
LAUNCHER = 'tools/installation/windows/Invoke-OnyxV100WindowsRuntime.ps1'
GATEWAY = 'windows/gateway/OnyxGateway_v100.py'
DASHBOARD = 'windows/gateway/gateway-dashboard-v100.html'
DASH_ALIAS = 'windows/gateway/gateway-dashboard.html'
BOOT = b'''    # Installed M5 candidate: Python -I omits the script directory.
    # Admit only the adjacent non-redirected runtime tree, not cwd/PYTHONPATH.
    import stat
    folder = Path(__file__).absolute().parent
    for node in (*reversed(folder.parents), folder):
        info = node.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Redirected gateway runtime refused')
    # Reject linked/reparse-point module files and redirected dependency directories.
    root = folder.parents[1]
    for relative in ('windows/gateway', 'windows/monitoring', 'windows/monitoring/v080'):
        directory = root / relative
        for node in (*reversed(directory.parents), directory):
            info = node.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Redirected monitoring runtime refused')
        for module in directory.glob('*.py'):
            info = module.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked monitoring module refused')
    sys.path.insert(0, str(folder))
'''


def payload(role, data):
    check_inputs(role, data)
    result = dict(data)
    if role == 'windows':
        result[COLLECTOR] = once(result[COLLECTOR],
            b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore'",
            b"$logDir = Join-Path $env:LOCALAPPDATA 'OnyxCore-v100'")
        result[COLLECTOR] = once(result[COLLECTOR], b"'Local\\OnyxCoreCollector'", b"'Local\\OnyxCoreV100Collector'")
        for name in (HELPER, LAUNCHER):
            result[name] = once(result[name], b"'OnyxCore\\collector-token.dpapi'", b"'OnyxCore-v100\\collector-token.dpapi'")
        # Explicit flag, preview by default. Existing legacy-task refusal remains.
        result[LAUNCHER] = once(result[LAUNCHER], b"        'ONYX CORE - Telemetry Collector',",
            b"        'ONYX CORE v1.0.0 - Telemetry Collector',\n        'ONYX CORE v1.0.0 - Local Gateway',\n        'ONYX CORE - Telemetry Collector',")
        result[LAUNCHER] = once(result[LAUNCHER], b'    [switch]$DryRun,', b'    [switch]$EnableMonitoringView,\n    [switch]$DryRun,')
        result[LAUNCHER] = once(result[LAUNCHER], b'if ($DryRun -and $Component',
            b"if ($EnableMonitoringView -and $Component -ne 'Gateway') { throw 'Monitoring view requires Gateway.' }\nif ($DryRun -and $Component")
        result[LAUNCHER] = once(result[LAUNCHER], b'    dry_run = [bool]$DryRun',
            b'    monitoring_view_enabled = [bool]$EnableMonitoringView\n    dry_run = [bool]$DryRun')
        # Replace only the reviewed gateway invocation, retaining -I, -B and DPAPI.
        old = b'''    & $PythonPath -I -B $Gateway `
        --dashboard $Dashboard `
        --receiver ([string]$Cfg.receiver.host) `
        --receiver-port ([string]$Cfg.receiver.port) `
        --port ([string]$Cfg.gateway.port) `
        --load-dpapi'''
        new = b'''    $GatewayArgs = @('--dashboard', $Dashboard,
        '--receiver', [string]$Cfg.receiver.host,
        '--receiver-port', [string]$Cfg.receiver.port,
        '--port', [string]$Cfg.gateway.port, '--load-dpapi')
    if ($EnableMonitoringView) { $GatewayArgs += '--v100-monitor-view' }
    & $PythonPath -I -B $Gateway @GatewayArgs'''
        result[LAUNCHER] = once(result[LAUNCHER], old, new)
        result[GATEWAY] = once(result[GATEWAY], b'def main():\n', b'def main():\n' + BOOT)
        result[DASH_ALIAS] = result[DASHBOARD]
        example = 'docs/v1.0.0/examples/windows.config.example.json'
        result[example] = once(result[example], b'"port": 18766', b'"port": 18976')
    else:
        # Both shipped examples must point to v100 state, never legacy data.
        example = 'docs/v1.0.0/examples/pi-armv6.config.example.json'
        result[example] = once(result[example], b'"state_dir": "/var/lib/onyxcore"',
                               b'"state_dir": "/var/lib/onyxcore-v100"')
        launcher = 'tools/installation/pi/onyx_v100_pi_launch.py'
        result[launcher] = once(result[launcher], b"    storage = config['storage']\n",
            b"    storage = config['storage']\n    if storage['state_dir'] != '/var/lib/onyxcore-v100':\n        raise LaunchRefused('M5 requires isolated v100 state')\n")
    for name, raw in result.items():
        if name.endswith('.py'):
            compile(raw, name, 'exec')
    return result


def manifest(role, data, result):
    return {'schema_version': 1, 'kind': 'onyxcore-v100-m5-inactive-runtime-candidate',
            'release_version': '1.0.0', 'role': role, 'source_commit': COMMIT,
            'source_tree': TREE, 'activation_performed': False,
            'installation_performed': False, 'native_installation_approved': False,
            'credential_files_included': False,
            'inputs': [{'path': p, 'sha256': sha(data[p])} for p in sorted(data)],
            'files': [{'path': p, 'sha256': sha(result[p]), 'size': len(result[p])} for p in sorted(result)]}


def zip_bytes(role, data):
    import io
    result = payload(role, data)
    result[MANIFEST] = canonical(manifest(role, data, result))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', allowZip64=False) as archive:
        for name in sorted(result):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, result[name])
    raw = buffer.getvalue()
    if len(raw) > MAX_ZIP:
        raise Refused('Candidate too large')
    return raw


def verify(path, role, data):
    plain(path)
    if not path.is_file() or path.stat().st_size > MAX_ZIP:
        raise Refused('Expected bounded candidate archive')
    expected = zip_bytes(role, data)
    if path.read_bytes() != expected:
        raise Refused('Archive differs from deterministic source-derived bytes')
    return {'verified': True, 'role': role, 'source_commit': COMMIT,
            'archive_sha256': sha(expected), 'payload_files': len(payload(role, data)),
            'activation_performed': False, 'installation_performed': False}


def build(path, role, data):
    plain(path)
    if path.exists() or not path.parent.is_dir():
        raise Refused('New output in existing directory required')
    raw = zip_bytes(role, data)
    fd, name = tempfile.mkstemp(prefix='.onyx-m5-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        verify(Path(name), role, data)
        os.link(name, path)  # no replacement, even on concurrent creation
        return verify(path, role, data)
    finally:
        Path(name).unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('plan', 'build', 'verify'))
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--role', required=True, choices=sorted(ROLES))
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--approve-build', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.approve_build != (args.operation == 'build') or (args.archive is None) != (args.operation == 'plan'):
            raise Refused('Build requires explicit approval; build/verify require archive')
        data = source(args.repo, args.role)
        if args.operation == 'plan':
            raw = zip_bytes(args.role, data)
            report = {'role': args.role, 'source_commit': COMMIT, 'payload_files': len(payload(args.role, data)),
                      'prospective_sha256': sha(raw), 'installation_performed': False, 'activation_performed': False}
        else:
            if args.archive.resolve().is_relative_to(args.repo.resolve()):
                raise Refused('Archive must be outside source repository')
            report = (build if args.operation == 'build' else verify)(args.archive, args.role, data)
        print(canonical(report).decode('ascii'), end='')
        return 0
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
