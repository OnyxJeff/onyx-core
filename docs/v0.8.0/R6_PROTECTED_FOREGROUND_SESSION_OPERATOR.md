# ONYX CORE v0.8.0 R6: Protected Foreground Session Operator

Status: **DEVELOPMENT / OFFLINE ONLY**. This patch does **not** change the installed RC3 runtime or grant authorization to run R6 on SQUALL. No push, tag, merge, installation, enrollment, notification delivery, repair or Scheduled Task creation.

## Approved change boundary

- `OnyxV080ReleaseOperator.py` gains an **opt-in**, manually invoked `--run-session-count N --approve-session-read-only --session-duration-minutes M` foreground command. No action is added to the default CLI. Existing `--run-count`, audit, enrollment and revocation behavior is preserved.
- Bounded values: 1–20 cycles; 1–60 minutes; one cycle per reviewed M1/M2/M3 release-binding call; configuration-matched 120-second interval; no persistent service or scheduled startup.
- R4 `SessionPolicy` and R5 `run_reviewed_session()` are called only **after** the operator's existing fixed-path, protected owner/DACL, independent approved-source digest, Windows user/SID and active local-console admission.
- Fresh Windows grant verification uses `OnyxWindowsRuntimeAttestation.build_rechecking_authorizer()`. The R4 wait loop rechecks authorization, native console session and protected source every two seconds or less. The worker's release binding independently rechecks authorization before each probe/record and enforces the existing Job containment and single-instance lock.
- Session expiry returns `EXPIRED`, not an unqualified `PASS`. Worker/source/consent failures propagate to the operator's fail-closed exit. No automatic credential renewal.
- R6 expands `REQUIRED_FILES` from 16 to 18 to cover the two **newly executed** R4/R5 modules. The operator and attestation modules were already in the inventory.

## Alert boundary is not closed by R6

R4 alert authorization and R5 cursor integration remain inert and separate. **No actual notification provider, grant issuer, secret endpoint reader, or delivery entrypoint is enabled.** An independent alert authorization and provider integration milestone is required before operational alerts can be claimed.

## Release packaging blocker

The RC1–RC3 `build_rc_source.py` toolkit has a hard-coded 16-file approval inventory. **Do not reuse it for R6.** A new independently reviewed frozen-candidate builder must match all 18 `OnyxWindowsRuntimeAttestation.REQUIRED_FILES`, and a separately pinned administrator-protected install/approval anchor must be generated before any Windows R6 native acceptance. Rebuilding an approval document in a user-writable directory is not an independent trust anchor.

## Acceptance

Offline tests should prove explicit session approval, ordinary one-cycle CLI compatibility, two one-cycle bridge calls, persistent-cycle counts, prompt revocation, console/source denial, absolute duration expiry and release-profile preservation. Full development regression must pass on SQUALL with protected RC3 and all four monitoring histories unchanged. **No real live R6 session is authorized at this stage.**
