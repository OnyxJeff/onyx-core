# M2-S7C — isolated Pi configuration contract (offline)

Parent: `cf682b0729c8d03a0ba7c882dbdb811e752bd6a2`. S7B-R2 remains unchanged and reports its original protected-parent refusal. The user approved an independent `/etc/onyxcore-v100` configuration directory. This checkpoint adds a separate **preview-only** contract, not a native publisher. No host changes, credentials, activation or commits are authorized.

## Proposed targets and permissions

| Component | Target | Owner/group and mode |
| --- | --- | --- |
| Release directories / files | `/opt/onyxcore/v1.0.0` | root:onyxcore-v100, 0750 / 0640 |
| Configuration directory / nonsecret files | `/etc/onyxcore-v100` | root:onyxcore-v100, 0750 / 0640 |
| Future credential | `/etc/onyxcore-v100/receiver.env` | root:root 0600 |
| Future activation marker | `/etc/onyxcore-v100/activation-approved` | root:root 0600 |
| State | `/var/lib/onyxcore-v100` | onyxcore-v100:onyxcore-v100 0700 |
| Future unit | `/etc/systemd/system/onyxcore-v100-receiver.service` | root:root 0644 |

Use a dedicated non-root system user and group named `onyxcore-v100`, with no login shell or legacy group memberships. Numeric IDs are not assigned or assumed. The legacy service user and group remain untouched. Systemd's system manager reads the future root-only EnvironmentFile; the receiver consumes the token from its environment, not by reading the credential file. The proposed unit also denies access to legacy config/state via InaccessiblePaths. Keep legacy `/etc/onyxcore` root:root 0700, legacy state and service unchanged. The proposed unit has no [Install] section, refuses manual start, and requires a separate marker; do not register or activate it. A separate activation design must account for the marker, RefuseManualStart, and port 8765 handover. These guards are not a substitute for keeping the unit unregistered.

## Source and receipts

The M2-S1 bundle is unchanged. Its JSON configuration schema already accepts the same isolated state directory; the launch CLI accepts an external config path. The original 14-file release payload changes only its unit candidate; the new prospective receipt records 14 entries, producing 15 release files in total. The external config has two prospective files (canonical JSON and receipt). No credential or marker bytes are generated. Candidate receipts explicitly do not attest native publication. The three accepted S7B hashes are verified before generating revised hashes. The old S3C and S3D native writers still target the old contract and MUST NOT be used to publish these candidates. No live write entry point is added here.

## Remaining gates

1. Read-only metadata verification of the new config root and identity name/UID/GID availability; previous absence evidence applies only to the old path. Verify ancestors, supplemental groups and existing service identity; no credential contents.
2. Adapt the native no-replace publishers to the revised contract, including ownership, verified inventory, and new receipt semantics. Test native ARMv6 renameat2, safe staging, incomplete publication and rollback; authorize Temp writes separately.
3. Obtain separate authorization for account provisioning and inactive publication. No credential enrollment or unit registration until explicitly authorized; activation and port handover remain separate.

No claim of native readiness or security enforcement is made by the offline candidate. The previously observed legacy port 8765 remains occupied. The installed Windows runtime and production Git tree are not modified.
