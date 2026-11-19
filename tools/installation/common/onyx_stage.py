#!/usr/bin/env python3
"""ONYX CORE v0.9.0 M2: verify and stage release archives in an OS temp sandbox.

NOT a Windows/Pi system installer. Never registers tasks/services, modifies the
USB link, reads credentials, or replaces existing targets. Preview is default.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

# The source is reviewed together with the existing v0.9 release verifier.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'release'))
from onyx_release import verify_archive  # noqa: E402

SHA256 = re.compile(r'[a-fA-F0-9]{64}\Z')
COMMIT = re.compile(r'[a-f0-9]{40}\Z')


class StageRefused(ValueError):
    pass


def check_destination(target: Path) -> Path:
    """Only a new, direct child of OS temp named OnyxV090-... is permitted."""
    tmp = Path(tempfile.gettempdir()).resolve(strict=True)
    if not target.is_absolute() or target.name.startswith('.'):
        raise StageRefused('sandbox target must be an absolute, visible path')
    if not re.fullmatch(r'OnyxV090-[A-Za-z0-9_-]{1,50}', target.name):
        raise StageRefused('sandbox target must be a direct OnyxV090-* child of OS temp')
    try:
        parent = target.parent.resolve(strict=True)
    except OSError as exc:
        raise StageRefused('sandbox parent does not exist') from exc
    if parent != tmp:
        raise StageRefused('target must be directly under this process OS temp directory')
    if target.exists() or target.is_symlink():
        raise StageRefused('sandbox target already exists; no overwrite')
    return target


def inspect(archive: Path, *, platform: str, expected_commit: str,
            expected_version: str, expected_sha256: str) -> dict:
    if not COMMIT.fullmatch(expected_commit):
        raise StageRefused('expected full lowercase Git commit required')
    if not SHA256.fullmatch(expected_sha256):
        raise StageRefused('expected independent archive SHA256 required')
    if not archive.is_file() or archive.is_symlink():
        raise StageRefused('package must be an existing regular archive file')
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual.lower() != expected_sha256.lower():
        raise StageRefused('archive SHA256 mismatch')
    m = verify_archive(archive)
    if m['platform'] != platform or m['source_commit'] != expected_commit or m['version'] != expected_version:
        raise StageRefused('package identity (platform/version/commit) mismatch')
    return m


def stage(archive: Path, dest: Path, manifest: dict) -> None:
    check_destination(dest)
    base = Path(tempfile.gettempdir()).resolve(strict=True)
    temporary = Path(tempfile.mkdtemp(prefix='.OnyxV090-staging-', dir=str(base)))
    try:
        with zipfile.ZipFile(archive, 'r') as zf:
            for row in manifest['files']:
                name = row['path']
                output = temporary.joinpath(*name.split('/'))
                output.parent.mkdir(parents=True, exist_ok=True)
                # verify_archive has verified the member path, size and hash.
                # Verify again on extraction instead of trusting the earlier read.
                content = zf.read(name)
                if len(content) != row['size'] or hashlib.sha256(content).hexdigest() != row['sha256']:
                    raise StageRefused('archive member changed during staging')
                output.write_bytes(content)
                if os.name != 'nt' and output.suffix == '.sh':
                    output.chmod(0o755)
        # Keep package provenance in the sandbox, alongside the extracted files.
        (temporary / 'manifest.json').write_bytes(_manifest_bytes(archive))
        # Validate no existing destination immediately before final rename.
        check_destination(dest)
        temporary.rename(dest)
        temporary = None
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def _manifest_bytes(archive: Path) -> bytes:
    with zipfile.ZipFile(archive, 'r') as zf:
        return zf.read('manifest.json')


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--platform', choices=('windows', 'pi-armv6'), required=True)
    p.add_argument('--expected-commit', required=True)
    p.add_argument('--expected-version', required=True)
    p.add_argument('--expected-sha256', required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--stage', action='store_true', help='extract ONLY to the disposable sandbox')
    args = p.parse_args(argv)
    try:
        manifest = inspect(args.archive, platform=args.platform,
                           expected_commit=args.expected_commit,
                           expected_version=args.expected_version,
                           expected_sha256=args.expected_sha256)
        check_destination(args.target)
        print(f"PASS archive: {args.platform} v{args.expected_version}; "
              f"{len(manifest['files'])} files; commit {args.expected_commit}")
        print(f'Sandbox: {args.target}')
        if not args.stage:
            print('PREVIEW ONLY: nothing extracted, installed, registered, or started.')
            return 0
        stage(args.archive, args.target, manifest)
        print('PASS: verified archive staged in disposable sandbox only.')
        print('No system installation, Scheduled Tasks, systemd, credentials, or network changes.')
        return 0
    except (StageRefused, ValueError, OSError, zipfile.BadZipFile, KeyError) as exc:
        print(f'STOP: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
