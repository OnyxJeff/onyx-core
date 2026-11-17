# ONYX CORE v0.8.0 — Phase C SEC-01–SEC-10 Closure Register (Draft)

**Document class:** Security release-gate register; **status:** DRAFT FOR REVIEW / offline only.  
**Evidence cutoff:** 2026-11-11 post-R6 audit, exact development commit `6e4ddef5a30e36742387432448f67e8dcf8bd469`.  
**Disposition:** **9 BLOCKED**, **1 OPEN TEST GAP**, **0 CLOSED**. **Live unattended monitoring / release: NO-GO**.

## 1. Status definitions and evidence bar

- **BLOCKED:** An operational trust, safety or functionality control has not been independently established by the R1–R6 synthetic work. A mock token, test fixture, unkeyed digest chain or inert CLI is not closure evidence.
- **OPEN TEST GAP:** A specific adversarial Windows test could not run in the available ordinary-user environment; there is no basis to call that case passed.
- **CLOSED:** Reserved for *future*, separately approved implementation plus reproducible host evidence, explicit review and a recorded disposition change. Nothing here is closed.

All owner, testing, implementation, rollout and evidence-capture assignments remain **TBD**. The evidence column below specifies *what* to demonstrate, not permission to execute the tests or deploy the control. Live/security testing requires a separate risk review, operator authorization and protections for production and existing tasks/histories.

## 2. Release gate register

| Gate | Domain / source boundary | Current status | Closure evidence needed (not yet supplied) |
|---|---|---|---|
| **SEC-01** | Operator consent, R1 synthetic grants and revocation | **BLOCKED** | Authenticated, specific, per-cycle Windows operator approval binding user/session, source/config, expiry and exact capability; authoritative revoke/disable and fail-closed behavior independently tested |
| **SEC-02** | Windows identity, source and filesystem integrity, R1 mock SID/ACL/path checks | **BLOCKED** | Real Windows token, interactive session and effective NTFS owner/DACL/inherited-ACE checks; verified ancestors, final handles, reparse points and change/race handling with independently reviewed evidence |
| **SEC-03** | Worker and descendant confinement, R2 synthetic job/deadline model | **BLOCKED** | Demonstrate atomic suspended-start/Windows Job Object containment or independently reviewed equivalent, non-breakaway descendants, finite timeout, kill-tree and output/memory budget behavior under failure |
| **SEC-04** | Read-only collection, R2/M2C synthetic observations and legacy v0.7 writing collector | **BLOCKED** | Independently reviewed v0.8-only read-only evidence adapter with measurable no-write/no-migration guarantees for production and both protected v0.7 stores; credible behavior on errors |
| **SEC-05** | Authenticity and time, R2 synthetic observations, R5 modeled clocks | **BLOCKED** | Actual trusted live observation provenance, defensible clock/monotonic relation, timezone/skew/rollback/drift behavior and explicit UNKNOWN when attestation is absent |
| **SEC-06** | Durable, authenticated incident/event/intent state, R3/R4 temporary SQLite and unkeyed hashes | **BLOCKED** | v0.8-specific ACL-hardened write boundaries and authenticated actor/event provenance; crash-atomic transactions, replay safety, recovery, bounded retention/backup and tamper-response evidence |
| **SEC-07** | Authenticated operator controls, R4 synthetic actions and M4 static UI | **BLOCKED** | Authenticated and authorized operator action/acknowledgment protocol, source/incident binding, replay controls, safe UI and independent real-user/session attestation |
| **SEC-08** | Explicitly opted-in transport and delivery, R4 simulated would-send | **BLOCKED** | Approved provider and channels, affirmative opt-in, authenticated send/receipt/uncertainty ledger, persistent deduplication, privacy controls and proven no implicit retry on ambiguity |
| **SEC-09** | Native Windows symlink adversarial test, M2A fixture creation refused by OS policy | **OPEN TEST GAP** | Separately authorized, isolated native Windows symlink/reparse-point test executed under suitable conditions; retain complete failure/success evidence and verify rejection. Do not elevate an installer or relax system security merely to force a pass |
| **SEC-10** | Actual unattended scheduler/worker timing, R5 pure transitions | **BLOCKED** | Bounded observed cadence with missed-cycle, jitter, overlap, timeout, shutdown/restart, quarantine, clock anomaly and process-tree termination evidence under explicitly approved host tests |

## 3. Minimum review standard for a future closure proposal

Each gate requires (a) a scoped implementation/reference design identifying production and private-store boundaries, (b) approved native-host test conditions and protected-asset snapshots, (c) fail-closed negative/adversarial cases as well as positive cases, (d) attributable reproducible evidence, (e) independent review of the evidence versus the exact gate, and (f) a separately recorded operator decision. Completion of a test **does not itself change gate status**. Never merge or infer a capability by combining synthetic modules with `simulation_only=true`.

**Cross-cutting stop rules:** Preserve production v0.7.0, its original collector backup, both protected five-file histories, and the three audited task definitions. Do not use protected history files as fixtures. No real probes, Task Scheduler registration, enrollment, transport, auto-repair or privileged test runs are authorized by this document. Unknown evidence must result in **NO-GO / UNKNOWN**, not green health.

## 4. Current count and release implication

**0/10 gates closed.** SEC-01 through SEC-08 and SEC-10 are BLOCKED, and SEC-09 is OPEN TEST GAP. Even if the known symlink test is eventually demonstrated, the other nine controls still require independent closure. Conversely, 923 passing offline tests, 41 matching hashes, and a clean Git history are useful development assurance but cannot authenticate the live Windows environment. **Live unattended v0.8.0 release remains NO-GO.**
