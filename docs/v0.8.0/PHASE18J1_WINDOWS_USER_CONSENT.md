# ONYX CORE v0.8.0 — Phase 18J1 Windows user-scoped consent adapter

**Development-only, default deny.** This is a real Windows Credential Manager generic-credential adapter, not a production approval or independent signature system. Scope: logged-on SQUALL user, periodic read-only USB/ICS checks, release-only incident history, no repair or notification transport. Release status remains **HOLD**.

## Delivered

- `OnyxWindowsUserConsent.py`: read/validate Windows generic credential `OnyxJeff/ONYX_CORE/v0.8.0/ReadOnlyMonitoring`; explicit, non-CLI `write_windows_grant()` and `delete_windows_grant()` primitives for a **future separately authorized operator workflow**. Their existence is not permission to invoke them.
- Only exact canonical JSON grants can pass: current SID, full source commit, 64-character config SHA256, bounded UTC issue/expiration (max seven days), exact read-only scope, `LoggedOnUserOnly`, release storage profile, `repair_action=None`, notifications disabled.
- `make_reader_authorizer` produces a **per-invocation** verification callback. The Phase 18I1 bridge does not call this automatically; no runnable live CLI, scheduler, operator enrollment, or task setup is included.
- Twenty offline tests use injected credential bytes and fake attestation. They **never call** `CredReadW`, `CredWriteW`, `CredDeleteW`, actual Windows mutexes, the Pi, or real history storage.

## Security model and limits (do not waive silently)

Microsoft documents that generic Windows credentials are available to processes under the same Windows user and are **not an independent signing authority**. A same-user attacker can rewrite this credential. Credential Manager protects it from other user contexts and from casual plaintext exposure, not from malware running as the enrolled user. Revocation-by-deletion is not rollback resistant under same-user compromise. Explicit grant expiry prevents indefinite unattended authorization but needs an operator renewal process.

The `VerifiedContext` inputs are **not trusted by this module** unless supplied by a separately reviewed Windows-native attestor that validates actual token/session, source bytes, configuration, executable path/identity, ancestors, NTFS owner/DACL and reparse/TOCTOU conditions. `make_reader_authorizer` is a safe test/integration seam, **not a production-proof attestor**. Reading a user credential does not close SEC-01, SEC-02 or SEC-09 by itself. SEC-03 process containment and other release gates remain pending. Do not mistake a clean Git status for source-chain integrity.

## Operational separation

Installation changes exactly three new development files in `D:\github_repos\onyx-core-v080` and runs offline tests; it does NOT read, write, create, enroll or delete any Windows credentials. It cannot start monitoring, change Windows Scheduled Tasks, use live connectivity checks, access the Pi or the protected v0.7/v0.8 monitoring histories, send notifications, modify a production file, stage Git, commit, push, merge, tag or deploy. The CLI only accepts `--check-inert`.

Before promoting this component, explicitly review and approve the intended **local-user trust boundary** versus a separate signing authority. Production integration requires a source/identity attestor, operator enrol/revoke UX, authoritative revocation controls, Windows native tests, and release acceptance against the SEC-01–10 register. This installation is **not** that authorization.
