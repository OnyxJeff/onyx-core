# ONYX CORE v0.8.0 — Phase 18H1: signed-enrollment fixture integration

**DEVELOPMENT ONLY. NOT a production trust anchor. v0.8.0 release HOLD.**

Parent checkpoint: `34752eb3c9155ff5e145c5c703d4088a309154c0`.

This milestone adds a **pure, synthetic enrollment contract**, not a real grant verifier or issuer. It integrates Phase 18C's bounded supervisor admission checks with strict canonical JSON, *injected* detached-signature fixture validation, revocation floors/IDs, source/config hashes, Windows SID claims, interactive-session claims, and expiry. Every synthetic cycle re-evaluates the evidence. The offline verifier is deliberately injected; the module has **no signing key and no way to gain runtime monitoring permissions**.

## Mandatory invariants

- Canonical UTF-8 ASCII JSON (sorted keys, no whitespace, no duplicates) is the signed message. Limit 8 KiB.
- Explicit required fields only; schema 1; `simulation_only=true` is mandatory.
- Scope exactly `periodic_read_only_usb_ics`; `read_only=true`; `repair_action=None`; `notifications_enabled=false`; `storage_profile=release`; `session_policy=LoggedOnUserOnly`.
- SID, source commit, config SHA-256, grant generation and ID must match independently observed **synthetic** claims. Reject expired, future-dated, over-seven-day validity, revoked and stale-generation grants.
- The signature callback is *not a trust anchor*. Synthetic unit tests employ an intentionally forgeable fixture-only digest. NEVER reuse that verifier for production or accept self-attested signed JSON as live authorization.
- All condition checks are fail-closed. Simulated work is bounded to 1–20 cycles and cannot call M1/M2/M3 live interfaces. No persisted state.

## Still required before any live enrollment

1. Define an independent issuer, cryptographic signature format, pinned public key(s), signing-key custody, rotation and revocation authority. Verified signer provenance must not be supplied by user-writable JSON, task arguments or environment variables.
2. Implement Windows handle-backed source/config/ACL integrity, reparse-point exclusions, process identity/session checks and durable revocation. Bind signed source commit to an audited release tree, executable digest and launch image.
3. Integrate OS-backed attestation with Windows-native primitives; preserve global exclusion across sessions. Test distinct-session exclusion when a genuine second session is available.
4. Provide controlled task registration, stop/rollback, restart limits, retention, status and operational recovery. Never bypass M1's development-only live restrictions until separately approved.
5. Revalidate on real Windows before each cycle; record safe local evidence; no automatic repair or notification delivery.

**A passing offline test demonstrates the contract, not production authorization.** No changes to production v0.7.0, protected histories, or Scheduled Tasks are allowed under this patch.
