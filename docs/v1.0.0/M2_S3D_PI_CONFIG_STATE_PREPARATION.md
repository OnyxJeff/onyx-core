# ONYX CORE v1.0.0 — M2-S3D Pi Configuration and State Preparation

Status: **development-only; native ARMv6 installation not approved**.

## Objective

Prepare the two **separate** v1.0.0 Pi destinations after S3C's code-only
publication. Existing receiver services, `/etc/onyxcore/receiver.env`, and
`/var/lib/onyxcore` remain untouched.

- Configuration directory: `/etc/onyxcore/v1.0.0`, `root:onyxcore`, `0750`.
- Configuration: `/etc/onyxcore/v1.0.0/pi-armv6.config.json`, `root:onyxcore`, `0640`.
- Configuration receipt: `/etc/onyxcore/v1.0.0/config-receipt.json`, `root:onyxcore`, `0640`.
- Empty state directory: `/var/lib/onyxcore-v100`, `onyxcore:onyxcore`, `0700`.
- **Not created:** `/etc/onyxcore/v1.0.0/receiver.env`, activation-approved marker,
  systemd unit, history database, snapshots, or network changes.

The config schema and the S3C release bytes are validated against the pinned
M2-S1 candidate. The S3C release must exist on the Pi before future native
filesystem preparation. The provisioner never copies or migrates legacy data.

## Procedure — development acceptance (SQUALL)

Run `tests/installation/test_onyx_v100_pi_config_state.py` with the pinned
candidate ZIP in the `ONYX_V100_BUNDLE` environment variable. Then run the
config-state tool with `--bundle` and `--config` and **without** any approval
switches. The command emits one JSON `PI_V100_CONFIG_STATE_PREVIEW` record
and performs no system writes. The guarded M2-S3D SQUALL installer repeats
these steps before and after placing three new files in the isolated development
worktree.

## Native system boundary (not approved in M2-S3D)

Native filesystem preparation requires a **separately authorized** Pi operation
and all three explicit CLI switches `--prepare-system --approve-inactive
--approve-filesystem`, plus Linux ARMv6, Python 3.13, root privileges, and
verification of an existing, matching S3C code release. The CLI cannot select
alternative system targets. The tool validates fixed parent directories,
service identity, symlink safety, and no-overwrite publication.

The two destination directories cannot be published as a single atomic
filesystem transaction. The tool stages each directory and performs separate
`renameat2(RENAME_NOREPLACE)` operations. If state publication succeeds but
configuration publication fails, the state directory remains intact and the
operation reports `INCOMPLETE`. **Do not rerun or delete automatically.** An
operator must reconcile that partial state before any further attempt.

No credential material is read or produced, no service is registered or
started, and no activation marker is written. Native ARMv6 acceptance and
systemd operations remain future gated milestones.

## Known constraints

- A Windows-run preview is **not** native Pi acceptance.
- The source example uses `MyWindowsPC` as a portable sample identity; an
  installer must use matching source identities on both hosts.
- The existing Pi may have restrictive `/etc/onyxcore` permissions; failure
  must stop for review rather than loosening legacy directories.
- Do not infer durable state migration or reboot persistence from this step.
