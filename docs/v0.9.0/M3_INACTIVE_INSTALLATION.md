# ONYX CORE v0.9.0 — M3: Versioned, inactive installation preparation

**Status:** development only; no system installation or deployment authorized. Starts from published v0.8.0 source SHA `76fd861f83960897c85271a62d50bb544be2d858` in isolated worktree `D:\github_repos\onyx-core-v090`.

## What is implemented

- Cross-platform Python standard-library offline release installer. It verifies the **independently supplied** package SHA-256, source commit, platform, version, ZIP manifest, every file digest, and input path safety before writing.
- Preview by default. Explicit `--apply` atomically installs a *new*, **inactive** release directory only. Existing directories are never replaced, even if they contain matching files. Preexisting v0.7/v0.8 data, services and tasks are not read or changed.
- Windows PowerShell 5.1 wrapper: a disposable OS-temp sandbox is the default; protected system-path preparation would require `-System -Apply -ApproveInactiveSystemPreparation` *and* an elevated administrator context. This stage does **not** authorize those flags.
- Pi shell wrapper: default disposable sandbox; versioned system path would be `/opt/onyxcore/v0.9.0` on an original ARMv6 Pi with root and explicit authorization. It does not install/update systemd or NetworkManager and cannot activate the receiver.
- A provenance receipt records release version, Git commit and independent archive SHA-256 with `activated: false`.
- M1 packager is minimally updated so both Windows and Pi archives include `tools/installation/common/`. Previously the shared validator and installer were absent from built archives.

## Deliberately not implemented yet

- **No production/source checkout synchronization, Scheduled Tasks, service registration, `systemctl` calls, USB/ICS changes, Pi receiver activation, secret enrollment, or network requests.**
- No in-place upgrade or operational rollback. New-version code can be prepared without touching active components, but switching a service/task to use it is a separate, still-unimplemented transaction.
- No SQLite data backup/restore yet. Live stores and credentials must be left alone until a consistent backup and verified restoration procedure is developed and accepted.
- Existing v0.8.0 guarded monitoring code is hard-coded to its v0.8 installation path/approval source. **Do not run it from v0.9.0 or weaken its checks.** This remains a required compatibility gate for future monitored activation.
- Pi legacy receiver launcher doesn't pass `--history-file`; a clean v0.9 Pi service definition must explicitly configure SQLite-backed history and use a versioned path. That reconciliation is the next engineering task.
- Windows system-path source attestation is not yet covered by the v0.8.0 operator. The inactive installer requires administrator elevation for system preparation but does not replace native ACL trust acceptance.

## Safe development acceptance

`C:\Python313\python.exe -I -B tests\installation\test_onyx_install.py`

Expected: **11 tests**, with one possible Windows symlink-permission skip. No actual system installations, task changes or Pi changes. Only the named isolated development files are staged, with no commit.

## Next

M4: Pi receiver/service reconciliation, Windows activation policy and configuration, consistent SQLite backup + recoverable cutover design, installation smoke tests on isolated devices. M5: GitHub CI, documentation, frozen candidate and one final full regression. **Any system installation or Git write requires separate explicit user authorization.**
