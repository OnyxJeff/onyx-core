# ONYX CORE v0.9.0 — M4 Runtime Plan and Isolated SQLite Recovery

**State:** development code only; no source commit, system installation, runtime activation, scheduled task changes, NetworkManager changes, Pi access, or release authorization.

**Source baseline:** `76fd861f83960897c85271a62d50bb544be2d858` (published v0.8.0). **Development:** `D:\github_repos\onyx-core-v090`, branch `feature/v0.9.0-install-release-engineering`.

## Newly implemented

1. `tools/installation/common/onyx_runtime_plan.py` verifies *every file* in an M3 inactive versioned release against its checked-in manifest, checks its unactivated receipt and independently supplied Git SHA, and emits a **read-only** Windows/Pi startup proposal. This is not independent package authentication: archive SHA must be pinned separately and the manifest must originate from a trusted release workflow. The planner never creates Scheduled Tasks or services.
2. `tools/installation/pi/launch-onyx-v090-receiver.sh` uses the fixed versioned `/opt/onyxcore/v0.9.0` path, dynamically discovers the original Pi Zero's expected USB ICS lease, and **includes both** `--history-file /var/lib/onyxcore/telemetry.db` and `--state-file /var/lib/onyxcore/latest-snapshot.json` to use SQLite-backed history. Do not use that default as an automatic migration destination: production can use a different database filename. Reconcile actual state and migration strategy first.
3. `tools/installation/pi/onyxcore-v090-receiver.service` is an uninstalled, unstarted, separate candidate unit. The accompanying `90-onyx-v090-receiver` dispatcher is also uninstalled; if independently approved later, it restarts only the active candidate service when the USB DHCP address changes. M3 installs the dispatcher in a release tree with mode 0644; any *future* real NetworkManager registration must give its copy executable permission 0755 and correct owner/ACL. No change to the existing `onyxcore-receiver.service` or gadget/ICS setup is authorized.
4. `tools/installation/common/onyx_backup.py` supports disposable-temp **SQLite-only** snapshots and restores using Python SQLite's transactional backup API. The source DB is opened read-only, including WAL-backed sources. The snapshot is normalized to a single DB file, integrity-checked, hashed and accompanied by a strict manifest. Restore refuses overwrites and writes only a new disposable directory. This does **not** read, migrate or restore production data. The backup routine is sandbox-only by design.

## Important non-implemented work and release blockers

- **No real upgrade/cutover:** An active `onyxcore-receiver.service` and a new candidate service cannot both bind TCP 8765. A controlled stop/activate/health-check/rollback transaction, preserving credentials, Task Scheduler definitions, monitoring grants, and OBS endpoints, requires separate implementation and approval.
- **No actual Windows installation or startup:** The plan names candidate Windows tasks and port 18769, but changes nothing. Production port 18766 and protected release port 18768 remain untouched. The v0.8.0 protected monitoring operator is pinned to `C:\Program Files\OnyxCore\v0.8.0` and cannot safely be renamed/repointed to v0.9.0 without a new trust/approval design; M4 leaves monitoring disabled.
- **No production backup or restore:** The SQLite tool protects only synthetic sandboxes, not `%LOCALAPPDATA%`, `/var/lib/onyxcore`, v0.7.0 monitoring histories, or the protected v0.8.0 tree. An approved deployment must add durable, native snapshots and verify actual restore before any cutover; tokens and DPAPI blobs are explicitly excluded from copying.
- **No guaranteed compatibility with existing Pi database:** The documented reference paths have evolved. Inventory current `/var/lib/onyxcore` and service command line read-only before choosing a real path. An initial v0.9.0 clean install may use `telemetry.db` but must not overwrite or silently replace an older `companion.db`.
- **No cross-architecture native acceptance:** Linux test execution confirms only standard-library backup/plan logic; Pi Zero ARMv6 shell, systemd, NetworkManager dispatcher and reboot behavior still need native isolated acceptance.
- **No arbitrary self-service installer yet:** Source-attestation/ACL, explicit consent, clean Windows startup, dependency/config portability and final end-to-end acceptance are still outstanding.

## Narrow tests

From Windows PowerShell 5.1 in the isolated worktree:

```powershell
& 'C:\Python313\python.exe' -I -B 'D:\github_repos\onyx-core-v090\tests\installation\test_onyx_backup.py'
& 'C:\Python313\python.exe' -I -B 'D:\github_repos\onyx-core-v090\tests\installation\test_onyx_runtime_plan.py'
& 'C:\Python313\python.exe' -I -B 'D:\github_repos\onyx-core-v090\tests\installation\test_onyx_m4_integration.py'
```

Both are self-contained and create/release only their own `OnyxV090-*` disposable folders. **Expected: 6 SQLite checks + 5 startup-plan checks + 2 end-to-end archive/install/plan checks, no skips.** No live diagnostics, HTTP calls or task scheduling. Pi shell syntax also validated offline where POSIX `sh` is available.

## M5 short path

1. Commit candidate **only after explicit approval** and build from the new exact Git commit. M1's builder selects the new `tools/installation/common`, `tools/installation/pi` and `docs/v0.9.0` contents automatically.
2. Add CI for packaging, tests, PowerShell 5.1 parsing and SHA validation. No CI secrets or live tests.
3. Freeze packages and run one full offline regression, then a clean Windows install and native ARMv6 install with disposable storage and task/service state. Verify rollback of an actual stopped candidate without touching production.
4. Write an independently executable install and recovery guide (new operator, no prior-chat dependencies). Final release promotion/production activation are separate approvals.

**GO for isolated M4 development staging and targeted offline tests; NO-GO for system installation, task/service changes, active backup, notifications, CI pushes, commits, merges, tags or deployment.**
