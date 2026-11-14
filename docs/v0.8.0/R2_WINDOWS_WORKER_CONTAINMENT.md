# ONYX CORE v0.8.0 — R2 Windows worker containment

**Review stage:** development-only; **release status:** HOLD.
**Source basis:** locally verified candidate `220b544aae9d5dd836519a5b02c06b823f361052` (59 file manifest).

## Actual behavioral change

`OnyxLiveConnectivity.run_once()` now selects `OnyxWindowsJobRunner.WindowsJobRunner` when its **reviewed configuration explicitly declares `profile=release`**. In that case the caller may not override the subprocess adapter. The development-mode M1 CLI and mockable development `runner` remain unchanged. The existing release binding already passes `m1.run_once` into the guarded M2/M3 bridge. The bridge and other production CLIs stay inert.

The Windows worker adapter allowlists executable paths and requires bounded timeouts (1–90 seconds). The implementation uses the following Win32 sequence for each diagnostic subprocess:

1. Create an unnamed Job Object and set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
2. Prepare only the three required standard streams in a `STARTUPINFOEX` handle list (stdin is `NUL`; stdout/stderr are temporary files).
3. Call `CreateProcessW` **with CREATE_SUSPENDED** and `CREATE_NO_WINDOW`.
4. Assign the suspended process to the Job Object. Refuse and terminate the suspended process if assignment fails.
5. Resume its primary thread; wait for at most the configured timeout.
6. On timeout, terminate the job; always close the Job Object handle at cleanup, terminating any surviving job descendants.
7. Return bounded stdout bytes to M1's existing sanitizing JSON decoder; never expose raw stderr.

An inability to establish containment throws `JobRunnerRefused` (a `RuntimeError`) instead of being translated into a harmless `Unknown` diagnostic result. This is intentional: monitoring must fail closed, not persist a cycle as if job containment had succeeded.

## Unchanged / intentionally forbidden

- No live-monitor or enrollment CLI created. All application launchers stay disabled or dev-only as before.
- No Scheduled Task registration, Windows service installation, notification, repair, network change, source ACL modification or incident-store write.
- No change to the existing M1 development-only Git/worktree guard.
- No change to v0.7.0 gateway/collector, their Scheduled Tasks or histories.
- No change to the original R2 **source candidate**. That artifact is now a **review baseline only**, not the final post-containment release package.

## Required acceptance before authorization or deployment

1. Complete the offline regression on SQUALL, including the new tests.
2. Test a **harmless local child** (not PowerShell or SSH diagnostics) under the native job runner, including successful output, timeout cleanup and descendant termination. Native Win32 behavior is **not** validated by the Linux offline tests.
3. Verify host process/job nesting, handle inheritance, Windows error handling, and effective NTFS permissions in the final install directory.
4. Finish protected executable installation, pin a **new** manifest containing the modified M1 and new runner, bind the trusted manifest, implement reviewed enrollment/stop/revocation controls and an operator-approved start path.
5. Perform bounded live acceptance, dashboard/incident/notification checks, rollback rehearsal and signed-off release promotion.

Security limitation: Job Objects prevent ordinary child-process survival. They are not a sandbox, not a replacement for a pinned trusted release image, and cannot themselves prove source/ACL attestation or operator intent.
