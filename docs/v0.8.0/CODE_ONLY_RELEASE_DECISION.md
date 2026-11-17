# ONYX CORE v0.8.0 — Code-only GitHub Release Decision

**Decision date:** November 17, 2026. **Scope:** GitHub source release only; no protected deployment.

**Operator approval:** User expressly authorized final tests, GitHub merge, v0.8.0 tag, publication, and root README update. This approval does **not** imply live diagnostic execution, protected installation, task changes, notification delivery or network repair.

## Release test evidence

- Final SQUALL v0.8.0 offline suite: **1574 tests**, **11 skips**, **zero failures/errors**; includes the receipt-consistency hardening tests.
- Nine PowerShell synthetic route-evidence cases passed.
- Before release, twelve reviewed source files were pinned to the historical hash inventory, and the two patched files matched the proposed hashes after application.
- Development Git and original collector backup were checked; production `main` remained `06ec81582791fc797f74ad294195d68b2023cb66` and the two existing ONYX CORE tasks remained registered.
- No GitHub Actions CI is asserted. No live Windows/Pi diagnostic session, native LOW-integrity host acceptance, notification delivery, or protected-install reconciliation is asserted.

## Code-only GO / operational NO-GO

**GO:** merge reviewed v0.8.0 code through PR #18; tag the resulting merge commit; publish GitHub release notes; document actual capabilities in README.

**NO-GO:** protected Windows deployment, unattended monitoring startup, repair automation, treating the synthetic LOW-integrity oracle as real Windows attestation, and automatic notification delivery. Those require separate review and acceptance. The protected `C:\Program Files\OnyxCore\v0.8.0` tree is **not** promoted by this release.

The November 16 pre-merge readiness/checklist documents record an earlier, stricter *operational* gate and remain useful historical evidence. This decision scopes them to protected deployment, **not** publication of an inert/opt-in code snapshot. Do not interpret this as operational acceptance.

**Known host discrepancy:** `ONYX CORE - ICS Startup Recovery` was not registered in the latest read-only audit. No task was created or repaired as part of v0.8.0 source publication.
