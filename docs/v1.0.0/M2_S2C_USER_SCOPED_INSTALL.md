# ONYX CORE v1.0.0 — M2-S2C protected user-scoped install

Status: **Development-only source and offline tests**. Not production authorized. Parent: local M1 `8df66f772d5b15464290b7040621e9b03635d49e`. M2-S1 verified bundle SHA-256 `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d` and M2-S2A dashboard SHA-256 `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`.

## Purpose

Extend the accepted M2-S2B inert OS Temp installation with a *separate* durable, non-elevated, user-scoped Windows installation. Preserve every existing ONYX CORE service, task, credential, monitoring history, and installation. No existing target may be replaced or adopted.

Proposed inactive target naming: `%LOCALAPPDATA%\OnyxCore-v100-Inactive-<unique-ID>` as a **direct child** of native Windows LocalAppData, never `%LOCALAPPDATA%\OnyxCore` or a v0.7.0 history. `SHGetFolderPathW(CSIDL_LOCAL_APPDATA)` must agree with `LOCALAPPDATA` before using the location. No caller-selected root override is exposed in the CLI.

## Source artifacts

- `tools/installation/windows/onyx_v100_windows_user_install.py`: read-only preview by default. Uses the SHA256-pinned M2-S2B `onyx_v100_windows_install.py` for full 20-file bundle and corrected dashboard verification, with strict configuration. Only Windows/common files are installed.
- `tools/installation/windows/Set-OnyxV100UserInstallAcl.ps1`: restricted *staging-only* DACL helper, pinned by the Python source SHA256. A future explicitly approved local-profile install hardens the complete staging tree to the current user, SYSTEM and built-in Administrators and audits principals before atomic publication.
- `tests/installation/test_onyx_v100_windows_user_install.py`: synthetic user-root tests in temporary directories, negative authorization paths, provenance, receipt and tampering.

An installed tree includes 15 approved files plus `installation-receipt.json`. Its receipt identifies the source commit and SHA256-pinned bundle/dashboard, records per-file digests, and explicitly says no credential enrollment or activation occurred. Configuration is **not a secret**, and the receipt does not contain tokens.

## Authorization boundary

The public command defaults to preview. An actual user-profile install requires **all three** `--install --approve-inactive --approve-user-scope` flags, non-elevated native Windows Python 3.13, a new correctly named target, hardened ACLs, and explicit operator approval separate from this development patch. On failure, it leaves the target unpublished; a staged directory may be removed. Once published, the installer will never overwrite an existing target.

M2-S2C acceptance on SQUALL only installs **the four new source files in the development worktree** and runs offline synthetic tests and a *read-only* native LocalAppData preview. The guarded acceptance script will not pass any of the three installation flags to the Windows user installer. The existing M2-S2B Temp sandbox remains untouched.

## Intentionally pending

- Native ACL hardening *on a real user-scoped installation* requires a separately approved inactive install and evidence review. Synthetic ACL tests are not native DACL attestation.
- Preflight network route/host resolution, gateway port availability, secure token enrollment and task/service registration are not proven by this milestone. They remain future gates.
- No uninstall, upgrade or rollback, and no Pi receiver activation are authorized here.
