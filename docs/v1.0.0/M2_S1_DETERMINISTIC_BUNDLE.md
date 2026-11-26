# ONYX CORE v1.0.0 — M2-S1 Deterministic Core Runtime Bundle

**Scope:** Development-only packaging proof. No installation, configuration
writes, credential enrollment, service/task registration, USB/network changes,
external download, activation, commit, push, merge, or deployment.

**Pinned input:** Local development branch
`feature/v1.0.0-stable-installation`, exact reviewed M1 commit
`8df66f772d5b15464290b7040621e9b03635d49e`.

## Deliverable and contract

`tools/installation/common/onyx_v100_bundle.py` builds a **core runtime candidate**
ZIP using exactly 20 explicit, reviewed Git blobs from the pinned commit.
It reads objects with `git show COMMIT:path`, not working-tree content; Windows
CRLF checkout settings do not change bundle bytes. It refuses modified tracked
sources, staged changes, wrong branch/commit, missing blobs, symlink Git entries,
or unexpected file inventory. New untracked development tools are never bundled.

The package includes: the two validated configuration examples, the common
validator, the Pi v1 receiver, versioned SQLite store, the existing history and
health helpers, Pi dashboard, Pi launcher and readiness/USB selectors; and the
Windows v1 collector/gateway, gateway HTML dashboard and both overlays,
DPAPI **read** helper, Windows runtime launcher and readiness helpers.

The package intentionally excludes source generators, tests, legacy systemd
units, legacy Scheduled Task installers, existing state/history, token enrollment,
DPAPI token data, existing production configurations, v0.8 alert-monitoring
components and all machine-specific secrets. It is **not a complete v1.0.0
release artifact** and must not be installed into production as-is.

## Deterministic encoding

- Sorted paths, canonical ASCII JSON (sorted keys, compact separators, final LF).
- ZIP_STORED (no platform-dependent compression), fixed DOS timestamp
  `1980-01-01 00:00:00`, fixed Unix regular-file mode `0644`.
- No ZIP member comments or extra data, no duplicate/unsolicited paths.
- `bundle-manifest.json` records Git commit, version, roles, exact paths,
  SHA-256, sizes, permissions and explicit non-install/activation flags.
- Internal SHA-256 entries establish self-consistency, **not authenticity**.
  Later installation needs an independently verified archive SHA-256 or
  release signature and a separately reviewed provenance policy.
- Pre-publication verification checks the entire staged archive; exclusive
  hardlink creation refuses overwrite, including pre-existing files.

## Operator commands (Windows PowerShell 5.1)

**Preview (no writes):**

```powershell
$Repo = 'D:\github_repos\onyx-core-v100'
$Python = 'C:\Python313\python.exe'
$Tool = Join-Path $Repo 'tools\installation\common\onyx_v100_bundle.py'
& $Python -I -B $Tool plan --repo $Repo
```

**Create a candidate archive outside the repository:**

```powershell
$Out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ONYX_CORE_v1.0.0_M2S1_CoreRuntime_CANDIDATE.zip'
& $Python -I -B $Tool build --repo $Repo --output $Out --approve-build
```

**Read-only verification against the pinned local Git commit:**

```powershell
& $Python -I -B $Tool verify --archive $Out --repo $Repo
Get-FileHash -LiteralPath $Out -Algorithm SHA256
```

The build refuses an existing output; do **not** delete or overwrite it to
force a retry before inspecting the situation. Keep the SHA-256 for later review.

## M2-S1 acceptance

1. Run `test_onyx_v100_bundle.py` offline (synthetic local Git fixture).
2. Run preview on the actual M1 commit; expect 20 source files.
3. Build two candidates in distinct, unused OS-temp destinations and confirm
   their SHA-256 values and bytes match. Verify each against the local Git commit.
4. Keep just one candidate for review, with its independent SHA-256.
5. Confirm production `main`, legacy service tasks, Pi and persistent state are unchanged.

All commands are offline. No runtime process is launched. M2-S2/M2-S3 must
introduce actual Windows/Pi install and dependency verification. Credential
provisioning, safe activation, upgrades/rollback and native ARMv6 acceptance
remain independent milestones and approval gates.
