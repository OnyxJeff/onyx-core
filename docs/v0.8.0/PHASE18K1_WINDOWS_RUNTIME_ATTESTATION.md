# ONYX CORE v0.8.0 — Phase 18K1: Windows console/source + consent binding

**Development only. NOT deployable as a production monitoring supervisor. Release HOLD.**

Baseline: `e1d4a5ec0469fe332bb04a803e06f7472a51f858` on `feature/v0.8.0-continuous-monitoring`.

## Delivered

`OnyxWindowsRuntimeAttestation.py` makes the first *real* composition of the previously committed J1 user-consent adapter and G1 Windows token SID with per-call content/session attestation. It is an importable component, not an executable live launcher:

- `ReleaseManifest` enforces an exact file inventory of M1, M2, M3, the guarded runtime bridge, native admission, consent module, and the attestor itself, together with a full commit ID and exact SHA256 values. **The manifest must be pinned by independently reviewed release metadata, not supplied by an environment variable or user-writable consent grant.**
- `verified_consent_context` obtains the real process token SID using G1, validates it against the approved SID, and checks active console session via `ProcessIdToSessionId` and `WTSGetActiveConsoleSessionId`. It fails closed for RDP/detached sessions and mismatches. Validating active console session does not independently prove a particular user's informed consent.
- `attest_source` screens source/config paths for symbolic links and Windows junctions, rejects missing/oversized files, and compares bytes to manifest SHA256. Rechecked every time `build_rechecking_authorizer` is invoked, then J1 evaluates the current user-scoped grant and expiration.
- Unit tests cover real J1 grant interpretation with synthetic input and source bytes, revocation, source/config mutations, session refusal, mismatch, symlinks, and the inert CLI. Tests **do not call any Windows Credential Manager or native session operations**.

## Important security limitations

1. `ReleaseManifest` by itself is **not an authenticated trust anchor**. A Python caller supplying its own manifest/callback can forge an approval. A reviewed startup path must pin the allowed manifest and secure the launch context.
2. This initial source checker uses read-only path screening plus hash comparison. It does **not** provide open-handle identity anchoring, prove ancestor NTFS DACL/owner restrictions or eliminate path replacement TOCTOU races. SEC-02/09 remain open. Do not use it as the sole source attestor in an unattended worker.
3. Same-user Windows malware can change generic credentials and potentially modify user-writable source. The locally scoped trust model must be consciously accepted and documented; this is not an independent signer.
4. Release config must be separately validated. M1's development-only config/verify-context guard remains unchanged; no release-mode M1 CLI is enabled by this patch.
5. SEC-03 process-tree confinement and SEC-10 unattended timing are not yet operationally proven. No job object, scheduled task, live SSH/ICS probe, notification, credential enrollment, release SQLite DB, or collector changes are included.

**NO-GO:** Do not create a production launcher, change Scheduled Tasks, deploy, or claim security-gate closure based on this module alone. Next tasks are handle-backed ACL/source attestation, release-config validation, a reviewed opt-in startup/stop path, and controlled Windows end-to-end acceptance.
