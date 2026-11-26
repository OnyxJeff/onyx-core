#!/usr/bin/env python3
"""ONYX CORE M2-S3C: inactive, no-replace Pi release-code publication.

Preview by default. Native publication requires Linux ARMv6 Python 3.13,
root privileges, three operator switches, and an existing root-owned /opt/onyxcore.
Only creates /opt/onyxcore/v1.0.0. Never modifies /etc, /var/lib or systemd.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import sys
import uuid

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / 'common'
for folder in (HERE, COMMON):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from onyx_v100_pi_sandbox_install import (  # noqa: E402
    SOURCE_COMMIT, BUNDLE_SHA256, inspect_bundle, canonical_json,
    read_regular, MANIFEST_NAME,
)
from onyx_v100_pi_system_plan import (  # noqa: E402
    RELEASE_ROOT, LEGACY_STATE, _validate_system_config,
    render_unit, NEEDED_TOOLS,
)
from onyx_v100_config import load_config  # noqa: E402

RELEASE_NAME = 'v1.0.0'
PARENT = Path('/opt/onyxcore')
INTERNAL_CONFIG = 'config/pi-armv6.config.json'
UNIT_CANDIDATE = 'installation/onyxcore-v100-receiver.service.candidate'
RECEIPT = 'installation/receipt.json'
RENAME_NOREPLACE = 1
AT_FDCWD = -100

class PublishRefused(ValueError):
    pass


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def expected_files(bundle: Path, config_path: Path, *, python_path='/usr/bin/python3') -> tuple[dict[str, bytes], dict]:
    """Read-only canonical payload and proposed source identity (never credentials)."""
    selected, raw_manifest = inspect_bundle(bundle)
    if len(selected) != 11:
        raise PublishRefused('unexpected Pi runtime dependency inventory')
    config = load_config(config_path, 'pi-armv6')
    _validate_system_config(config)
    if config['storage']['state_dir'] != '/var/lib/onyxcore-v100':
        raise PublishRefused('M2-S3C requires isolated /var/lib/onyxcore-v100 state')
    unit = render_unit(config, python_path=python_path)
    files = dict(selected)
    files[MANIFEST_NAME] = raw_manifest
    files[INTERNAL_CONFIG] = canonical_json(config)
    files[UNIT_CANDIDATE] = unit.encode('utf-8')
    if len(files) != 14 or any('..' in Path(name).parts or name.startswith('/') for name in files):
        raise PublishRefused('unsafe release-code file inventory')
    return files, config


def receipt_bytes(files: dict[str, bytes]) -> bytes:
    entries = [{'path': name, 'size': len(data), 'sha256': digest(data)}
               for name, data in sorted(files.items())]
    return canonical_json({
        'schema_version': 1,
        'operation': 'PI_V100_INACTIVE_CODE_PUBLISHED',
        'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256,
        'files': entries,
        'service_registered': False,
        'service_enabled': False,
        'activation_performed': False,
        'credentials_enrolled': False,
        'external_state_changed': False,
    })


def plan(files: dict[str, bytes], config: dict) -> dict:
    return {
        'schema_version': 1, 'operation': 'PI_V100_CODE_PUBLICATION_PREVIEW',
        'release_root': RELEASE_ROOT, 'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256,
        'file_count': len(files) + 1,
        'state_dir': config['storage']['state_dir'],
        'unit_candidate_sha256': digest(files[UNIT_CANDIDATE]),
        'release_written': False, 'credential_contents_read': False,
        'service_registered': False, 'service_enabled': False,
        'activation_performed': False, 'legacy_state_modified': False,
        'native_armv6_verified': False, 'permissions_applied': False,
    }


def native_prerequisites():
    if (sys.platform != 'linux' or platform.machine().lower() != 'armv6l' or
            sys.version_info[:2] != (3, 13) or os.geteuid() != 0):
        raise PublishRefused('system publication requires root on Linux ARMv6 Python 3.13')
    for tool in NEEDED_TOOLS:
        if shutil.which(tool) is None:
            raise PublishRefused('native prerequisite unavailable: ' + tool)
    import pwd
    import grp
    try:
        service = pwd.getpwnam('onyxcore')
        group = grp.getgrnam('onyxcore')
    except KeyError as exc:
        raise PublishRefused('reviewed onyxcore service user/group absent') from exc
    if service.pw_uid == 0 or service.pw_gid != group.gr_gid or group.gr_gid == 0:
        raise PublishRefused('unexpected service identity')
    return group.gr_gid


def open_root_parent() -> int:
    """Open /opt/onyxcore using fixed-name dirfds, refusing symlinks/unsafe owners."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    rootfd = os.open('/', flags)
    try:
        optfd = os.open('opt', flags, dir_fd=rootfd)
        try:
            pfd = os.open('onyxcore', flags, dir_fd=optfd)
            try:
                for fd in (rootfd, optfd, pfd):
                    st = os.fstat(fd)
                    if st.st_uid != 0 or not stat.S_ISDIR(st.st_mode) or (st.st_mode & 0o022):
                        raise PublishRefused('unsafe release parent ownership or permissions')
                return pfd
            except BaseException:
                os.close(pfd)
                raise
        finally:
            os.close(optfd)
    finally:
        os.close(rootfd)


def rename_noreplace(parentfd: int, old: str, new: str):
    """Linux renameat2(RNAME_NOREPLACE) only. No unsafe os.rename fallback."""
    libc = ctypes.CDLL(None, use_errno=True)
    func = getattr(libc, 'renameat2', None)
    if func is None:
        raise PublishRefused('renameat2 unavailable; no-replace atomic publish required')
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    func.restype = ctypes.c_int
    rc = func(parentfd, old.encode('ascii'), parentfd, new.encode('ascii'), RENAME_NOREPLACE)
    if rc != 0:
        err = ctypes.get_errno()
        raise PublishRefused('atomic no-replace publication failed: ' + errno.errorcode.get(err, 'OSERROR'))


def _secure_write(stage: Path, relative: str, data: bytes, *, owner: int, group: int):
    if not relative or relative.startswith('/') or '\\' in relative or ':' in relative or any(
            p in ('', '.', '..') for p in relative.split('/')):
        raise PublishRefused('unsafe proposed release relative path')
    node = stage
    for part in relative.split('/')[:-1]:
        node = node / part
        if not node.exists():
            node.mkdir(mode=0o750)
            os.chown(node, owner, group)
            os.chmod(node, 0o750)
        elif not node.is_dir() or node.is_symlink():
            raise PublishRefused('unsafe staging directory')
    dest = node / relative.split('/')[-1]
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchown(fd, owner, group)
        os.fchmod(fd, 0o640)
    finally:
        os.close(fd)


def publish_in_parent(parentfd: int, parent: Path, files: dict[str, bytes], *, owner: int, group: int,
                      check_root_parent: bool = True) -> dict:
    """Internal code-only publisher. Unit tests use private temp parents, never system paths."""
    if set(files).intersection({RECEIPT}) or len(files) != 14:
        raise PublishRefused('unexpected publication inventory')
    if check_root_parent and parent != PARENT:
        raise PublishRefused('release publication parent mismatch')
    try:
        os.stat(RELEASE_NAME, dir_fd=parentfd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise PublishRefused('release target already exists; no overwrite')
    stage_name = '.onyx-v100-staging-' + uuid.uuid4().hex
    os.mkdir(stage_name, mode=0o700, dir_fd=parentfd)
    stage = parent / stage_name
    published = False
    try:
        os.chown(stage, owner, group)
        os.chmod(stage, 0o750)
        rows = dict(files)
        rows[RECEIPT] = receipt_bytes(files)
        for name, contents in sorted(rows.items()):
            _secure_write(stage, name, contents, owner=owner, group=group)
        # No attacker can write this root-owned, non-group-writable stage.
        for name, contents in rows.items():
            item = stage.joinpath(*name.split('/'))
            if not item.is_file() or item.is_symlink() or digest(item.read_bytes()) != digest(contents):
                raise PublishRefused('staged release integrity mismatch')
        os.fsync(parentfd)
        rename_noreplace(parentfd, stage_name, RELEASE_NAME)
        published = True
        os.fsync(parentfd)
        return {'schema_version': 1, 'operation': 'PI_V100_INACTIVE_CODE_PUBLISHED',
                'release_root': str(parent / RELEASE_NAME), 'file_count': len(rows),
                'source_commit': SOURCE_COMMIT, 'bundle_sha256': BUNDLE_SHA256,
                'service_registered': False, 'activation_performed': False,
                'credentials_enrolled': False, 'external_state_changed': False}
    finally:
        if not published:
            # Safe only when the staging path still refers to our newly created directory.
            shutil.rmtree(stage, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--python-path', default='/usr/bin/python3')
    ap.add_argument('--install', action='store_true')
    ap.add_argument('--approve-inactive', action='store_true')
    ap.add_argument('--approve-system', action='store_true')
    args = ap.parse_args(argv)
    try:
        files, cfg = expected_files(args.bundle, args.config, python_path=args.python_path)
        approvals = (args.install, args.approve_inactive, args.approve_system)
        if any(approvals) and not all(approvals):
            raise PublishRefused('all THREE approval switches required for system publication')
        if not all(approvals):
            print(canonical_json(plan(files, cfg)).decode('ascii').strip())
            return 0
        group = native_prerequisites()
        parentfd = open_root_parent()
        try:
            result = publish_in_parent(parentfd, PARENT, files, owner=0, group=group)
        finally:
            os.close(parentfd)
        print(canonical_json(result).decode('ascii').strip())
        return 0
    except (PublishRefused, OSError, ValueError, TypeError, KeyError, ImportError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
