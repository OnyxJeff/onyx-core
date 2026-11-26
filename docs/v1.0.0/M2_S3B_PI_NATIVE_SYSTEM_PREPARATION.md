# ONYX CORE v1.0.0 — M2-S3B Native Pi System Preparation

**Status:** Development-only, read-only template and native-metadata preflight. **Not an installation or approval to change the Pi.**

## Purpose

M2-S3A verified an inactive Pi install under OS Temp. M2-S3B establishes the
requirements for a *future* durable ARMv6 installation without writing to
`/opt`, `/etc`, `/var/lib`, or systemd. No SSH, network probes, permissions
changes, enrollment, service registration or activation occur during SQUALL
acceptance.

The `onyx_v100_pi_system_plan.py` module produces deterministic candidate unit
text and a JSON preview. Unit text is never written by the module.

## Future versioned paths (not created)

| Purpose | Proposed path |
|---|---|
| Code release root | `/opt/onyxcore/v1.0.0` |
| Pi config | `/etc/onyxcore/v1.0.0/pi-armv6.config.json` |
| Receiver credential | `/etc/onyxcore/v1.0.0/receiver.env` |
| Dedicated data | `/var/lib/onyxcore-v100` (example; must be reviewed) |
| Inactive unit candidate | `/etc/systemd/system/onyxcore-v100-receiver.service` |
| Activation marker | `/etc/onyxcore/v1.0.0/activation-approved` |

The old receiver and its `/var/lib/onyxcore` history remain untouched. The
system plan **rejects** a state directory of `/var/lib/onyxcore` or any
subdirectory. The actual Windows and Pi configs must agree on telemetry
source and receiver port before installation. The `MyWindowsPC` example is
not SQUALL's production source identity.

## Candidate unit safety properties

- Runs under `onyxcore:onyxcore`; needs pre-provisioned state directory.
- Uses `ProtectSystem=strict`, `NoNewPrivileges=true`, `UMask=0077`,
  `ReadWritePaths=<dedicated versioned state>`, and a versioned credential path.
- Includes `ConditionPathExists` for a *nonexistent until separately approved*
  activation marker and `RefuseManualStart=yes`.
- Contains the runtime CLI arguments but cannot by itself register, enable,
  or start a service; template-only. A future activation milestone must
  explicitly review/replace the manual-start safeguard, and verify the marker.
- Does not embed token values or alter systemd unit directories.

## SQUALL preview (no Pi connection)

```powershell
& 'C:\Python313\python.exe' -I -B `
  'D:\github_repos\onyx-core-v100\tools\installation\pi\onyx_v100_pi_system_plan.py' `
  --config 'D:\github_repos\onyx-core-v100\docs\v1.0.0\examples\pi-armv6.system.config.example.json'
```

This returns `native_readiness=NOT_NATIVELY_INSPECTED`, not an installation
certificate. On actual ARMv6 hardware, `--native-readonly` inspects only OS,
interpreter, command availability, service-account identity and filesystem
**metadata** (never credential contents). Execution on the Pi requires a
separate transfer and operator authorization. Unreadable credential paths are
reported as unknown, not missing.

## Explicitly deferred

Package prerequisites, privilege boundaries, race-safe no-replace publication,
real unit configuration and registration, secure credential enrollment, USB
routing verification, state migrations, and service start remain separately
reviewed tasks. The M2-S3B preview does not establish these are complete.
