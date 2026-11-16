# ONYX CORE v0.8.0 — R6.2B2C Process-handle exit barrier

**Status: offline-only change; RELEASE HOLD pending SQUALL-native acceptance.**

## Why this correction is necessary

SQUALL's R6.2B2B native synthetic test v2 observed a positive descendant PID with
`WaitForSingleObject(descendant_process, 0) == WAIT_TIMEOUT` **after** the
supervisor returned successfully. The previous supervisor treated
`QueryInformationJobObject(JobObjectBasicAccountingInformation).ActiveProcesses
== 0` as sufficient cleanup evidence. It is not a guaranteed per-process exit
barrier. `TerminateJobObject` is asynchronous with respect to process teardown.

## Change

- Before terminating a job, `QueryInformationJobObject` requests a complete
  `JobObjectBasicProcessIdList` snapshot with a bounded, expanding buffer.
- Each still-discoverable member PID is opened with `SYNCHRONIZE |
  PROCESS_QUERY_LIMITED_INFORMATION`, then checked with `IsProcessInJob`.
- The parent retains these process **handles**, preventing PID reuse for those
  identified processes, until cleanup finishes.
- `TerminateJobObject` is requested even if enumeration fails. Then the parent
  waits for its primary process handle and each independently retained member
  handle to become signaled, within one three-second cleanup deadline.
- Job accounting must also report no active processes. Any unsupported API,
  missing permission, incomplete member list, failed per-process wait, or
  outstanding member causes a fail-closed refusal. No old success fallback.
- All acquired process handles are closed. Aborted timeout/revocation still
  attempts best-effort kill in `finally` and rejects unverified cleanup.
- The launch security contract, restricted low-IL token, descendant Job, source
  trust, parent-only journal and consent boundaries remain unchanged.

## Limits requiring separate release acceptance

Win32 does **not** guarantee a finite cleanup duration. A Job PID list is a
snapshot, not a complete historical registry of all uncooperative descendants;
a descendant racing process creation with job termination can escape the
snapshot. This change strengthens observable termination for members captured
before `TerminateJobObject`, but does not prove arbitrary-process-tree identity
coverage in every race or the security of out-of-Job process creation.

The protected production journal ACL, restricted SSH diagnostic functionality,
late/ambiguous SQLite commit reconciliation and release-source manifest must
still receive independent Windows validation. None of these is approved by
passing a synthetic test. No deployment, monitoring activation, enrollment,
release tagging, Git staging/commit/push or protected-state write is included.

## Acceptance

1. On SQUALL verify exact source hashes and only this three-file development
   scope, with backup before apply.
2. Run full 1,391-test offline suite, expected 10 skips, zero errors/failures;
   compare protected v0.7.0 histories and Git status before/after.
3. Run the existing **v2** synthetic native acceptance script again, requiring
   all 5/5, including `B2B-NATIVE-04-Descendant-Exit`.
4. If native test fails, keep HOLD and inspect the actual Win32 diagnostic;
   do not lower the acceptance standard or deploy.

References: Microsoft documentation on `TerminateProcess`,
`JOBOBJECT_BASIC_PROCESS_ID_LIST`, `IsProcessInJob`, and Windows Job Objects.
