# ONYX CORE v0.8.0 — R6.2B2B Contained Worker Implementation

**Status: development-only implementation; security/release HOLD until SQUALL-native acceptance.**

## Implemented

- The protected release binding no longer calls the M1 diagnostic in the journal writer's Python interpreter. It passes a single-call contained probe into the existing guarded runtime bridge.
- The parent holds the pinned source trust, active-console SID/consent, foreground/global mutexes, monotonic session deadline and journal writer. The diagnostic child takes no journal path or storage-writing API parameter.
- The diagnostic subprocess is launched from the fixed protected install root with `C:\Python313\python.exe -I -B`. A Windows restricted token has privileges dropped and its mandatory integrity is set to **LOW** before `CreateProcessAsUserW` starts the suspended process. No unrestricted fallback exists if Windows declines the call.
- The child checks its actual process token's low integrity. It runs one read-only M1 diagnostic, including restricted SSH access to the Pi. It returns only sanitized JSON to stdout; the trusted parent applies an exact schema, classification, timestamp, duplicate-key, size and no-side-effects check.
- The low-integrity worker uses one-shot bounded PowerShell/OpenSSH pipes under the **outer** Job Object; it does not create nested Python temporary capture files in a medium-integrity `%TEMP%` directory. The existing M1 high-level `run_once` remains unchanged for development and non-contained release callers.
- A native Job Object is configured with `KILL_ON_JOB_CLOSE`; the process is suspended before assignment, then resumed. The launcher polls consent at most every 250 ms while running, terminates the entire job for timeout/revocation, and queries the Job Object's active process count after termination before accepting any report or declaring a safely stopped error. Only stdin/stdout/stderr handles are inherited. Existing individual PowerShell/SSH Job Objects continue to be nested underneath the Python worker's Job Object.
- The protected runtime source inventory includes `OnyxV080ContainedProbe.py` as a required attested file. Existing production v0.7.0 and its task/histories are not altered by this patch.

## Boundaries still requiring acceptance

1. **Native Win32 ABI and privilege compatibility.** An ordinary logged-on SQUALL user may lack `SeIncreaseQuotaPrivilege`; if `CreateProcessAsUserW` refuses with error 1314, this is a hard HOLD, not an invitation to use an unrestricted fallback. A separate Windows implementation review is mandatory.
2. **Actual journal integrity.** Low mandatory integrity normally denies write-up to medium/higher integrity objects, but the exact v0.8 journal directory, database file, WAL/SHM files, and inheritance/mandatory label must be audited natively. The low worker must fail to open the actual release journal for write under host acceptance. The synthetic temp-file test proves only the synthetic default-ACL scenario.
3. **Actual diagnostic access.** Windows PowerShell and OpenSSH must work under the restricted low-integrity token with the forced-command SSH key, without writable known-hosts fallback or credential changes. Do not run live Pi/ICS diagnostics until separately authorized.
4. **Commit ambiguity.** Pre-commit authorization checks (R6.2B1/B2A) cannot cancel a SQLite commit already underway. Release needs a tested high-watermark/idempotent recovery protocol; never automatically retry an uncertain commit.
5. **Pinned installation and release.** The revised source manifest must be independently reviewed, frozen, installed under protected `Program Files` ACLs and validated by source attestation before any real foreground opt-in. The current R6 source pin is invalidated by code changes. Scheduler, notifications and repairs are outside this implementation.
6. **User approval.** No commit, push, merge, tag, deploy, grant, enrollment, live probe, service or task change is authorized by this package.

## Acceptance order

1. Apply in development only after read-only preview and hash checks.
2. Run full 1,384-test offline SQUALL monitoring regression suite; expected skips = 9.
3. Explicitly run the separate synthetic host test (does not contact Pi, run monitoring, or write production storage). Require five out of five checks: low-integrity write denied, timeout, revocation, descendant exit, scratch-file integrity.
4. Audit protected release file/directory mandatory integrity and ACLs, first-run journal init and low worker attempted writes. Prove no late/duplicate persistence and restart reconciliation against controlled synthetic v0.8 DB.
5. Review/freeze release source inventory and approve a separate installer; only then consider a version tag or release.

**Not a GO:** A green offline suite or synthetic native test alone does not establish a full-feature v0.8 release approval.
