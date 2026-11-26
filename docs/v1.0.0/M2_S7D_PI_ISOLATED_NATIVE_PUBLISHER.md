# M2-S7D - Inactive Pi publisher

## Scope

This replaces the S3C/S3D publication path for the revised S7C contract. The
old tools remain available for historical offline regression coverage; do not
invoke their native modes for this installation. The runtime ZIP remains pinned.
The S7D publisher accepts a validated Pi configuration, including non-SQUALL
source/subnet values. It does not require historical S7A evidence. This is a
candidate, not the final public installer or an activation tool.

The ordinary preview is portable and read-only. `--native-preflight` requires
root on native Linux ARMv6 Trixie Python 3.13, checks absence and permissions,
and returns `ACCOUNT_PROVISIONING_REQUIRED` if the new user AND group are absent.
It does not provision an account. A partial identity is refused. The account
must be a separately provisioned non-root dedicated user/group, primary group
only, nologin shell and `/nonexistent` home. Lock its password at provisioning;
this checker does not inspect password hashes or shadow. A root-owned safe
`/opt/onyxcore` parent must already exist; clean-host setup is future packaging work.

## Publication

The inactive install interface requires `--install-inactive` and the exact
`--approve-plan-sha256` from a freshly generated preview. Do not run that mode
until explicitly authorized. Use root-owned, hash-verified installer sources
and input bundle/config from a trusted staging location; do not execute
untrusted user-writable Python as root. No arbitrary system target switch.

The engine stages each directory privately and publishes using `renameat2`
`RENAME_NOREPLACE`, with no fallback. Target and ancestor checks use no-follow
file descriptors; parents are root-owned, non-writable by group/other, and
traversable by the dedicated identity. Extended POSIX ACLs are refused. Each
published tree is re-opened and audited for exact files, bytes, modes,
owners, groups, regular-file link counts and absence of additional paths.

* `/opt/onyxcore/v1.0.0`: 15 files, directories 0750, files 0640, root:onyxcore-v100.
* `/etc/onyxcore-v100`: 2 files (nonsecret config and inventory receipt), same modes.
* `/var/lib/onyxcore-v100`: empty 0700, owned by onyxcore-v100.

The S7C unit bytes remain unchanged and are only a release-file candidate.
New S7D inventory receipts describe intended bytes and require a separate native
post-publication verification result; they do not assert installation occurred.
No unit registration, systemctl enable/start, credential enrollment, history
migration, legacy permission changes or network/USB reconfiguration. A read-only
systemctl show checks the v1 unit is not loaded and inactive. The legacy port
8765 handover is separate activation work.

Each directory rename is atomic; the three-target transaction is NOT atomic.
On failure, stop and preserve stage/target evidence. Never overwrite, automatically
retry or delete. A future operator recovery tool must validate inventory and
ownership before removing anything. This is failure containment, not a tested
uninstaller or full rollback mechanism.

## Acceptance

Run the existing Pi regressions and the focused S7D tests once from verified
staged sources. Real Linux tests use only disposable private temporary parents,
not system paths. Windows skips Linux-only tests. Actual ARMv6, root account
validation and native system publication are not proved by x86 Linux fixtures.
Before installing on the Pi, perform native read-only preflight and a separately
authorized private Temp fixture, then authorize account preparation/publication.

Post-v1.0.0 priority: GitHub Actions for Windows/Linux test matrix, deterministic
artifact builds and SHA-256 validation, release checks and explicit approval for
publication. ARMv6 hardware acceptance remains a separate native gate.
