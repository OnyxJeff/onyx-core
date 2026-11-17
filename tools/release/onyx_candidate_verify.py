#!/usr/bin/env python3
"""Build the exact same committed ONYX CORE release twice, verify both archives.

Offline release qualification helper; never installs, commits, publishes or reads
credentials. A build from uncommitted local development files is intentionally
impossible: onyx_release.build only consumes immutable Git commit objects.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
import onyx_release


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_repeatable(repo: Path, commit: str, version: str) -> dict:
    onyx_release.assert_commit(repo, commit)
    if not onyx_release.VERSION.fullmatch(version) or not version.startswith('0.9.0'):
        raise ValueError('v0.9.0 candidate version required')
    results = {}
    with tempfile.TemporaryDirectory(prefix='OnyxV090-Candidate-') as d:
        base = Path(d)
        for run in ('one', 'two'):
            out = base / run
            onyx_release.build(repo, commit, version, out)
            results[run] = {}
            for platform in onyx_release.PLATFORMS:
                package = out / f'ONYX_CORE-v{version}-{platform}.zip'
                identity = onyx_release.verify_archive(package)
                if identity['source_commit'] != commit or identity['version'] != version or identity['platform'] != platform:
                    raise ValueError('candidate package identity mismatch')
                expected_sidecar = f'{digest(package)}  {package.name}\n'.encode('ascii')
                if (out / (package.name + '.sha256')).read_bytes() != expected_sidecar:
                    raise ValueError('candidate sidecar mismatch')
                results[run][platform] = {'sha256': digest(package), 'files': len(identity['files'])}
        if results['one'] != results['two']:
            raise ValueError('two independent candidate builds differ')
    return {'status': 'REPRODUCIBLE', 'source_commit': commit,
            'version': version, 'artifacts': results['one'],
            'scope': 'offline-package-only-no-install-or-activation'}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--version', required=True)
    args = p.parse_args(argv)
    try:
        print(json.dumps(check_repeatable(args.repo, args.commit, args.version), sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
