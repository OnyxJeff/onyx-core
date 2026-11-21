#!/usr/bin/env python3
"""M2-S3D: prepare isolated v1 Pi state and config, never credentials or systemd.

Preview is default on all hosts. Actual publication requires three approvals,
Linux ARMv6 Python 3.13 as root, verified installed release and known service UID.
Two distinct directories cannot be committed atomically together; partial state
publication is reported as INCOMPLETE and never silently rolled back.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import sys
import uuid

HERE = Path(__file__).resolve().parent
for directory in (HERE, HERE.parent / 'common'):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from onyx_v100_pi_code_publish import (  # noqa: E402
    expected_files, receipt_bytes, RELEASE_NAME, PARENT,
    rename_noreplace, PublishRefused,
)
from onyx_v100_pi_system_plan import (  # noqa: E402
    CONFIG_PATH, CREDENTIAL_PATH, ACTIVATION_MARKER, UNIT_PATH,
    RELEASE_ROOT,
)
from onyx_v100_pi_sandbox_install import (  # noqa: E402
    SOURCE_COMMIT, BUNDLE_SHA256, canonical_json,
)

CONFIG_PARENT = Path('/etc/onyxcore')
CONFIG_NAME = 'v1.0.0'
CONFIG_FILENAME = 'pi-armv6.config.json'
CONFIG_RECEIPT = 'config-receipt.json'
STATE_PARENT = Path('/var/lib')
STATE_NAME = 'onyxcore-v100'
# The JSON/config contract is always POSIX even during Windows previews.
STATE_TARGET = str(PurePosixPath('/var/lib') / STATE_NAME)
NOFOLLOW_DIR = (os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0))


class ProvisionRefused(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def proposed(bundle: Path, config_file: Path) -> tuple[bytes, bytes, dict, dict]:
    """Construct bytes from the approved bundle and STRICT config, no disk writes."""
    selected, cfg = expected_files(bundle, config_file)
    if cfg['storage']['state_dir'] != STATE_TARGET:
        raise ProvisionRefused('state target is not the isolated v1 directory')
    data = canonical_json(cfg)
    receipt = canonical_json({
        'schema_version': 1,
        'operation': 'PI_V100_INACTIVE_CONFIG_PREPARED',
        'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256,
        'config_sha256': digest(data),
        'config_target': CONFIG_PATH,
        'state_target': STATE_TARGET,
        'credential_enrolled': False,
        'unit_registered': False,
        'activation_performed': False,
        'existing_history_migrated': False,
    })
    return data, receipt, cfg, selected


def preview(bundle: Path, config_file: Path) -> dict:
    config_bytes, receipt, cfg, _ = proposed(bundle, config_file)
    return {
        'schema_version': 1,
        'operation': 'PI_V100_CONFIG_STATE_PREVIEW',
        'source_commit': SOURCE_COMMIT,
        'bundle_sha256': BUNDLE_SHA256,
        'config_target': CONFIG_PATH,
        'config_sha256': digest(config_bytes),
        'receipt_sha256': digest(receipt),
        'state_target': STATE_TARGET,
        'receiver_source': cfg['receiver']['source'],
        'receiver_port': cfg['receiver']['port'],
        'config_directory_mode': '0750',
        'config_file_mode': '0640',
        'state_directory_mode': '0700',
        'state_owner': 'onyxcore',
        'state_group': 'onyxcore',
        'config_written': False,
        'state_written': False,
        'credential_contents_read': False,
        'credential_enrolled': False,
        'unit_registered': False,
        'service_enabled': False,
        'activation_performed': False,
        'legacy_state_modified': False,
        'native_armv6_verified': False,
    }


def _check_parent(fd: int, *, owner: int = 0) -> None:
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != owner or st.st_mode & 0o022:
        raise ProvisionRefused('unsafe parent ownership, type or write permission')


def _absent(fd: int, name: str):
    if name not in (CONFIG_NAME, STATE_NAME):
        raise ProvisionRefused('unreviewed publication target')
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ProvisionRefused('target already exists; never overwrite or merge')


def _new_stage(fd: int, prefix: str, uid: int, gid: int, mode: int) -> str:
    name = prefix + uuid.uuid4().hex
    os.mkdir(name, mode=0o700, dir_fd=fd)
    try:
        stagefd = os.open(name, NOFOLLOW_DIR, dir_fd=fd)
        try:
            os.fchown(stagefd, uid, gid)
            os.fchmod(stagefd, mode)
            os.fsync(stagefd)
        finally:
            os.close(stagefd)
        return name
    except BaseException:
        # A failed chmod/chown must not leave an untracked hidden staging dir.
        os.rmdir(name, dir_fd=fd)
        raise


def _write_file(dirfd: int, filename: str, data: bytes, uid: int, gid: int) -> None:
    if filename not in (CONFIG_FILENAME, CONFIG_RECEIPT):
        raise ProvisionRefused('unexpected config file')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(filename, flags, 0o600, dir_fd=dirfd)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o640)
    finally:
        os.close(fd)


def _safe_cleanup(parent: Path, stage: str | None) -> None:
    # The staging directories are 0700 or 0750, owned by trusted installer UID.
    if stage:
        item = parent / stage
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item)


def publish_in_parents(configfd: int, configparent: Path, statefd: int,
                       stateparent: Path, config_data: bytes, receipt_data: bytes,
                       *, root_uid: int, group_gid: int, service_uid: int,
                       service_gid: int) -> dict:
    """Testable POSIX publisher. Caller supplies already vetted directory FDs.

    Two no-replace directory publishes; on second failure, new state is left
    intact with an explicit INCOMPLETE error for manual reconciliation.
    """
    if os.name != 'posix':
        raise ProvisionRefused('POSIX filesystem publication required')
    _check_parent(configfd, owner=root_uid)
    _check_parent(statefd, owner=root_uid)
    _absent(configfd, CONFIG_NAME)
    _absent(statefd, STATE_NAME)
    configstage = None
    statestage = None
    state_published = False
    config_published = False
    try:
        configstage = _new_stage(configfd, '.onyx-v100-config-stage-', root_uid, group_gid, 0o750)
        cfd = os.open(configstage, NOFOLLOW_DIR, dir_fd=configfd)
        try:
            _write_file(cfd, CONFIG_FILENAME, config_data, root_uid, group_gid)
            _write_file(cfd, CONFIG_RECEIPT, receipt_data, root_uid, group_gid)
            os.fsync(cfd)
        finally:
            os.close(cfd)
        statestage = _new_stage(statefd, '.onyx-v100-state-stage-', service_uid, service_gid, 0o700)
        os.fsync(statefd)
        os.fsync(configfd)
        rename_noreplace(statefd, statestage, STATE_NAME)
        state_published = True
        statestage = None
        os.fsync(statefd)
        rename_noreplace(configfd, configstage, CONFIG_NAME)
        config_published = True
        configstage = None
        os.fsync(configfd)
        return {
            'schema_version': 1, 'operation': 'PI_V100_INACTIVE_CONFIG_STATE_PREPARED',
            'config_target': str(configparent / CONFIG_NAME),
            'state_target': str(stateparent / STATE_NAME),
            'config_sha256': digest(config_data),
            'credential_enrolled': False, 'unit_registered': False,
            'service_enabled': False, 'activation_performed': False,
            'existing_history_migrated': False,
        }
    except Exception as exc:
        if state_published:
            stage = ('both directories published but durability confirmation failed'
                     if config_published else
                     'isolated state directory published, config not published')
            raise ProvisionRefused(
                'INCOMPLETE: ' + stage + '; stop and review before any retry'
            ) from exc
        raise
    finally:
        _safe_cleanup(configparent, configstage)
        _safe_cleanup(stateparent, statestage)


def _open_fixed_directory(absolute: Path) -> int:
    """Open a fixed path from / using no-follow dirfds and verified ancestors."""
    if not absolute.is_absolute():
        raise ProvisionRefused('absolute fixed directory required')
    parts = absolute.parts[1:]
    fd = os.open('/', NOFOLLOW_DIR)
    try:
        _check_parent(fd)
        for part in parts:
            nextfd = os.open(part, NOFOLLOW_DIR, dir_fd=fd)
            _check_parent(nextfd)
            os.close(fd)
            fd = nextfd
        result = fd
        fd = -1
        return result
    finally:
        if fd != -1:
            os.close(fd)


def _service_can_traverse(directory_fd: int, service_gid: int) -> None:
    st = os.fstat(directory_fd)
    mode = stat.S_IMODE(st.st_mode)
    if not ((mode & 0o001) or (st.st_gid == service_gid and (mode & 0o010))):
        raise ProvisionRefused('service cannot traverse configuration parent')


def _native_identities() -> tuple[int, int]:
    if (sys.platform != 'linux' or platform.machine().lower() != 'armv6l' or
            sys.version_info[:2] != (3, 13) or os.geteuid() != 0):
        raise ProvisionRefused('native preparation requires root, Linux ARMv6, Python 3.13')
    import pwd
    import grp
    try:
        user = pwd.getpwnam('onyxcore')
        group = grp.getgrnam('onyxcore')
    except KeyError as exc:
        raise ProvisionRefused('onyxcore service identity missing') from exc
    if user.pw_uid == 0 or group.gr_gid == 0 or user.pw_gid != group.gr_gid:
        raise ProvisionRefused('unsafe service UID/GID')
    return user.pw_uid, group.gr_gid


def _verify_installed_code(files: dict[str, bytes]) -> None:
    """Read-only proof of S3C release before publishing external v1 state.

    Refuse redirected or writable ancestor directories, including ones inside
    the release; no installer-controlled read can be redirected to legacy state.
    """
    root = PARENT / RELEASE_NAME
    if root != Path(RELEASE_ROOT):
        raise ProvisionRefused('unreviewed release root')
    expected = {**files, 'installation/receipt.json': receipt_bytes(files)}
    for relative, raw in expected.items():
        node = root.joinpath(*relative.split('/'))
        for parent in reversed(node.parents):
            if not parent.is_relative_to('/opt') and parent != Path('/'):
                continue
            meta = parent.lstat()
            if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or
                    meta.st_mode & 0o022):
                raise ProvisionRefused('unsafe installed-release ancestor')
        # Check the root and every nested directory even if not listed as a file.
        current = root
        for part in relative.split('/')[:-1]:
            meta = current.lstat()
            if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or
                    meta.st_mode & 0o022):
                raise ProvisionRefused('redirected or writable installed release')
            current = current / part
        meta = current.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != 0 or
                meta.st_mode & 0o022):
            raise ProvisionRefused('unsafe release path')
        info = node.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                info.st_mode & 0o022 or node.read_bytes() != raw):
            raise ProvisionRefused('installed v1 code differs from approved release')


def _metadata_absent(path: str) -> bool:
    try:
        Path(path).lstat()
    except FileNotFoundError:
        return True
    return False


def native_prepare(config_bytes: bytes, receipt: bytes, files: dict[str, bytes]) -> dict:
    service_uid, service_gid = _native_identities()
    # No native filesystem writes until all independently owned targets pass preflight.
    if not (_metadata_absent(CONFIG_PATH) and _metadata_absent(CREDENTIAL_PATH)
            and _metadata_absent(ACTIVATION_MARKER) and _metadata_absent(UNIT_PATH)
            and _metadata_absent(STATE_TARGET)):
        raise ProvisionRefused('v1 config, state, unit or activation target already exists')
    _verify_installed_code(files)
    etcfd = _open_fixed_directory(Path('/etc'))
    varfd = _open_fixed_directory(STATE_PARENT)
    configfd = -1
    created_parent = False
    try:
        try:
            configfd = os.open('onyxcore', NOFOLLOW_DIR, dir_fd=etcfd)
        except FileNotFoundError:
            # A clean host needs an /etc/onyxcore root; never modify an existing one.
            os.mkdir('onyxcore', 0o755, dir_fd=etcfd)
            created_parent = True
            configfd = os.open('onyxcore', NOFOLLOW_DIR, dir_fd=etcfd)
        _check_parent(configfd)
        _service_can_traverse(configfd, service_gid)
        # Parent directory could have appeared between preflight and open.
        _absent(configfd, CONFIG_NAME)
        _absent(varfd, STATE_NAME)
        return publish_in_parents(configfd, CONFIG_PARENT, varfd, STATE_PARENT,
                                  config_bytes, receipt,
                                  root_uid=0, group_gid=service_gid,
                                  service_uid=service_uid, service_gid=service_gid)
    finally:
        if configfd != -1:
            os.close(configfd)
        os.close(etcfd)
        os.close(varfd)
        # A newly created empty /etc/onyxcore may remain on failure; non-secret,
        # never interpreted as acceptance. Do not delete pre-existing paths.


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--prepare-system', action='store_true')
    parser.add_argument('--approve-inactive', action='store_true')
    parser.add_argument('--approve-filesystem', action='store_true')
    args = parser.parse_args(argv)
    try:
        config_data, receipt, cfg, files = proposed(args.bundle, args.config)
        approvals = (args.prepare_system, args.approve_inactive, args.approve_filesystem)
        if any(approvals) and not all(approvals):
            raise ProvisionRefused('all three approval flags required; refusing partial request')
        if not all(approvals):
            print(canonical_json(preview(args.bundle, args.config)).decode('ascii').strip())
            return 0
        result = native_prepare(config_data, receipt, files)
        print(canonical_json(result).decode('ascii').strip())
        return 0
    except (ProvisionRefused, PublishRefused, OSError, ValueError, TypeError, KeyError) as exc:
        print('STOP: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
