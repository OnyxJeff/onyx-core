# ONYX CORE v0.9.0 — M2 package sandbox acceptance

Status: **development-only stage**, not a production installer or v0.9.0 release candidate. Starting source is the published v0.8.0 commit `76fd861f83960897c85271a62d50bb544be2d858` and the M0/M1 untracked release tools.

## Implemented in this checkpoint

- Standalone cross-platform Python staging tool using M1's complete ZIP/manifest verifier.
- Archive SHA-256, full source commit, release version, and platform must all match the operator's independent expectations.
- Preview is default. Explicit `--stage` extracts only to a **new** direct child of the operating system's temporary directory named `OnyxV090-*`.
- Existing target directories are never intentionally overwritten. Verification and staging fail closed on unexpected files or mismatches.
- Windows PowerShell 5.1 wrapper (preview by default) and read-only Pi system readiness inventory.
- Targeted tests cover preview/no-write, content/provenance, no-overwrite, wrong identity, and out-of-sandbox/corruption refusal.

## Known baseline packages from SQUALL bootstrap

These are **v0.8 source audit packages**, not v0.9 installables:

| Platform | Package | SHA-256 |
| --- | --- | --- |
| Windows | `ONYX_CORE-v0.8.0-audit-windows.zip` | `085840fc32dd8d6b87d52ab6279545c5d2e18ebfbff33f957496a53050e05621` |
| Pi | `ONYX_CORE-v0.8.0-audit-pi-armv6.zip` | `ce16cf8f5723308ca3d6fb547c52ed6db99df062599782dda31c3c8cf90dab67` |

The packages were reported at `%TEMP%\OnyxV090-BaselineBuild` after staging on SQUALL. Never install those audit packages into system paths.

## Next acceptance gates (not performed)

1. Reconcile Pi receiver `launch-receiver.sh` with the actual `receiver.py` SQLite history options before creating a system service installer.
2. Write a Windows v0.9.0 install-root, task, and DPAPI preservation contract distinct from existing protected v0.8.0 and running v0.7.0 production.
3. Implement **separately authorized** native install, task/service registration, data-consistent backup, upgrade and rollback. Test in disposable Windows/Pi environments first.
4. Only after candidate freeze, run the complete regression once. No commits, pushes, tags, releases, or production installation are authorized by this checkpoint.

## Commands

From the isolated v0.9.0 worktree:

```powershell
& 'C:\Python313\python.exe' -B .\tests\installation\test_onyx_stage.py
```

For package *preview* without extracting, use:

```powershell
& 'C:\Python313\python.exe' -I -B .\tools\installation\common\onyx_stage.py `
  --archive "$env:TEMP\OnyxV090-BaselineBuild\ONYX_CORE-v0.8.0-audit-windows.zip" `
  --platform windows `
  --expected-commit 76fd861f83960897c85271a62d50bb544be2d858 `
  --expected-version 0.8.0-audit `
  --expected-sha256 085840fc32dd8d6b87d52ab6279545c5d2e18ebfbff33f957496a53050e05621 `
  --target "$env:TEMP\OnyxV090-WindowsSandbox"
```

Add `--stage` only when you approve extraction into a disposable temporary directory. This cannot register tasks, contact the Pi, or activate monitoring.
