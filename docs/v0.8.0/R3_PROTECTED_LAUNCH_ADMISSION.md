# ONYX CORE v0.8.0 — R3 Protected Release Admission

**Status:** DEVELOPMENT ONLY / RELEASE HOLD. **Checkpoint parent:** `e68035d44a7a0355a1ef597f8a755a99d67311ea`.

## Implemented

- `OnyxWindowsRuntimeAttestation.REQUIRED_FILES` now covers fourteen release monitoring execution dependencies, including the R3 release profile/binding, Windows Job Object runner, configuration validator, Windows PowerShell probe wrapper, and the underlying USB/ICS diagnostic script.
- `OnyxV080ProtectedLaunch` parses a canonical, bounded approval document with exactly the intended fields and a SHA256 **pinned outside the document**. It rejects a modified document, ambiguous JSON, unexpected file inventory, unsafe SID, redirected source root, missing or modified source files, and non-release settings.
- Its offline `prepare_reviewed_install` adapter builds the **existing** `OnyxV080ReleaseBinding.ReleaseWiring`; it does not create another monitoring supervisor.
- The release binding's established rechecking authorizer will use the expanded manifest before every probe and persistence operation and during interval waits. An actual grant is not created or used by the adapter.

## Mandatory release blockers (still open)

- `APPROVED_RELEASE_DOCUMENT_SHA256` intentionally remains `None`. The real `audit_pinned_install` cannot succeed before an administrator-approved, separately pinned installation artifact exists.
- No production CLI starts the runtime. There is no grant issuer, start/stop, notification activation, Scheduled Task registration, live probe, or automatic repair.
- Independent, handle-backed NTFS ACL / file identity / time-of-check-to-time-of-use source attestation remains unimplemented. The path checks are preventive, not an adequate substitute.
- Python interpreter and dependencies, OpenSSH and PowerShell executable integrity, privileged installation procedure, console-session and consent workflows, real end-to-end start/stop/revoke, and rollback acceptance remain required.
- This component verifies **live monitoring dependencies**; it does not claim to authenticate the full independent gateway/dashboard delivery surface.
- `Windows Credential Manager` grants are user scoped but not an independent signature; a process running as the same user can potentially replace its own grant. The final threat model must accept or mitigate this.

## Developer verification

The new offline suite `tests/monitoring/v080/test_r3_protected_launch_admission.py` exercises approved and denied source admission (including post-build Job runner and PowerShell script mutation) and inert command-line behavior. Existing R3, release-binding, and 18K attestation suites remain part of the focused regression.

**Do not install into Program Files, create any enrollment, run live monitoring, push, merge, tag or deploy as part of this development-only integration.**
