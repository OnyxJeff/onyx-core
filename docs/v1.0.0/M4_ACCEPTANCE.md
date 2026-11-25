# M4 - Monitoring and recovery assessment acceptance

## Status

Technical acceptance: PASS

Acceptance date: 2026-11-25

Development branch: feature/v1.0.0-stable-installation

Development parent:
abf28c8a61c6ae89796cc20b0856857888d9e240

## Delivered capabilities

- Integrated monitoring health assessment.
- Isolated v1.0.0 SQLite monitoring history.
- Authorized journal initialization and recording.
- Incident lifecycle management and duplicate prevention.
- Read-only operator monitoring projection.
- Windows USB and Raspberry Pi connectivity assessment.
- Recovery recommendations without automatic repair.
- Native monitoring storage access-control enforcement.

## Focused regression acceptance

| Module | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| Monitoring foundation | 11 | 1 | 0 |
| Journal binding | 10 | 0 | 0 |
| Recovery assessment | 17 | 0 | 0 |
| Supervised recorder | 7 | 0 | 0 |
| Total | 45 | 1 | 0 |

46 tests discovered.
Test process exit code: 0.
Execution duration: 1.211 seconds.

The skipped redirected-parent symlink test requires a
Windows privilege unavailable in the non-elevated session.

Explicit-approval argument parser rejection was expected
and constituted successful negative test coverage.

## Native supervised acceptance

Host: SQUALL
Platform: Windows PowerShell 5.1, non-elevated

Observation timestamp:
2026-11-25T18:05:36.555197+00:00

Observation duration: 12736 ms

Observed status: Healthy
Windows classification: WindowsPathReady
Pi classification: PiInternetVerified
Reason: WindowsUsbAndPiInternetVerified
Journal outcome: NoIncident
Recommendation: NoRepairNeeded

No automatic repair, notification or scheduler activation
was performed.

The observation establishes health at the recorded instant,
not continuous availability after that observation.

## Independent journal verification

Relative user storage:

OnyxCore-v100/Monitoring/incident-history.sqlite3

SQLite user_version: 1
Database size: 32768 bytes
SQLite quick_check: ok

| Table | Rows |
| --- | ---: |
| checks | 1 |
| cycle_receipts | 1 |
| incidents | 0 |
| incident_events | 0 |

Database SHA-256:

FA087F860E399CD24D0625A5530EE7501A048F6388ED634E2DB93B8A599AE64C

The database hash remained unchanged during read-only
inspection and subsequent acceptance audits.

No SQLite sidecars were present during those audits.

Monitoring storage permissions were observed to be
restricted to the native user, SYSTEM and Administrators.

## Recorder evidence reconciliation

The original recorder contained a malformed 63-character
installation receipt SHA-256 pin.

Historical receipt evidence and the installed receipt
established the correct 64-character identity.

A separate corrected recorder was created using an exact,
reversible one-byte insertion. The original was preserved.

The corrected recorder subsequently completed one
supervised native observation successfully.

The external acceptance wrapper initially reported a
development status mismatch because it incorrectly expected
the worktree to remain unchanged after intentional patch
application.

The applied four-file recorder patch was subsequently
reconciled and independently checked.

Two source-manifest inspection attempts initially expected
SHA-256 identities. The original recorder actually used
40-character Git SHA-1 blob object identities.

Final canonical Git identity verification: 19 of 19.

Raw Git blob identities differed from the original manifest,
consistent with Git working-tree content normalization.
Independent raw SHA-256 snapshots verified source-byte
preservation during regression and reconciliation audits.

## Installation and production preservation

Production branch: main

Production HEAD:
06ec81582791fc797f74ad294195d68b2023cb66

Original collector backup SHA-256:

59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB

Windows installation receipt SHA-256:

C4C4FC7035D5010770511D254E49007B8AC583556B9CCCA919C271092EB810FE

Protected evidence remained unchanged during the final
acceptance operations.

## Checkpoint scope

The technical acceptance scope contains 19 development
files: six modifications and thirteen additions.

This acceptance document is an additional documentation
file, bringing the proposed checkpoint to twenty files.

## Remaining release boundaries

M4 acceptance is not a v1.0.0 release authorization.

The following remain outside this checkpoint:

- Continuous scheduled monitoring enrollment.
- Automatic repair activation.
- Notification enrollment.
- Deployment of newly developed M4 application code.
- Final reproducible release packaging.
- Full release-level installation and rollback acceptance.
- Push, merge, tag and publication.

The native observation must be preserved. Do not repeat
journal initialization merely to reproduce this evidence.

A local development commit requires separate authorization.
