# ONYX CORE v0.9.0 — M5 CI and candidate readiness

**Status:** development-only checkpoint. M5 source is uncommitted until a separately authorized commit. No system installation, release, tagging or publishing approval is implied.

## Implemented

- A two-build reproducibility checker consumes the *specified full Git commit SHA*, calls the immutable-source package builder twice, validates ZIP member manifests and `.sha256` sidecars, and checks byte-for-byte reproducibility. No checkout modifications or installation.
- An offline-only GitHub Actions workflow runs the existing targeted package/inactive-install/sandbox-backup suites and M5 focused tests on Windows and Linux; Windows uses **PowerShell 5.1 parse-only checks**. Neither job uses production hardware, credentials, real network diagnostics or deployment.
- A read-only Downloads cleanup classifier, with no safe-to-delete category or deletion command.
- A cleanup decision register grounded in the SQUALL audit, plus explicit outstanding release gates.

## Observed development tests on SQUALL (from operator transcripts)

- M1: 8 package-engineering tests passed.
- M2: 5 sandbox tests passed.
- M3: 11 tests executed, 10 passed, 1 expected Windows symlink privilege skip.
- M4: 13 tests passed, including two sandbox end-to-end package→inactive-install→launch-plan checks.

**Do not add these historical counts to claim a complete end-to-end production installation.** CI has not run on GitHub because the workflow is not yet committed/pushed. Native Raspberry Pi Zero ARMv6 acceptance has not run.

## Candidate freeze and GO/NO-GO gates

| Gate | Current state |
| --- | --- |
| Commit with all v0.9.0 installation/release source and no secrets | OPEN — 23+ source files untracked; commit separately requires authorization |
| Rebuild exactly twice from committed Git SHA and match package SHA256 | TOOL IMPLEMENTED; OPEN on final candidate |
| GitHub Actions Windows/Linux tests and package build | WORKFLOW AUTHORED; OPEN until CI executes |
| PowerShell 5.1 installer and Pi POSIX install preparation | INACTIVE CODE PREPARATION IMPLEMENTED; operational install not implemented |
| Native ARMv6 systemd/NetworkManager/USB and SQLite acceptance | OPEN; do not treat Linux CI as native Pi evidence |
| Windows new-user startup with preserved user DPAPI material | OPEN; no actual v0.9.0 tasks installed |
| Real configuration/prerequisite validation without host-specific assumptions | PARTIAL; Windows collector CPU sensor and v0.8 monitor paths remain host-specific |
| Live data-consistent backup, stop/cutover, health check, rollback | OPEN; M4 only exercises synthetic SQLite sandbox backup/restore |
| Protected v0.8 operator trust rebinding to v0.9 | OUT OF SCOPE without independent security review; monitoring disabled |
| One complete offline regression after frozen candidate | OPEN; perform once, after freeze |
| User documentation for first-time operational install and recovery | OPEN until real activation/cutover supported and validated |

**Decision:** M5 is a *preparation and CI checkpoint*, not an installable v0.9.0 RC. It is unsafe to label or publish the current inactive-code package as an operational full installer. Production v0.7.0 and protected v0.8.0 remain untouched.

## Requested minimal path forward

1. Stage these M5 files in isolated worktree, run only the new focused tests.
2. Review the full v0.9.0 source diff and freeze/install contracts. Request separate authorization for a **local commit**, then build official packages from that exact commit.
3. Implement and test opt-in native startup/upgrade/rollback on isolated disposable Windows/Pi hardware (cannot be replaced by synthetic tests).
4. Run a single full regression against final frozen source; accept or reject a real release candidate.
5. Only then offer the precise Downloads/Temp cleanup allowlist and independently approved maintenance cleanup.
