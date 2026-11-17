# ONYX CORE v0.8.0 — R6 Independent Security & Release Verification (Offline)

**Authorization:** R6 development **only**, from local R5 commit `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4`, branch `feature/v0.8.0-continuous-monitoring`.  
**Current disposition:** **R6 OFFLINE SQUALL HOST ACCEPTANCE PASSED; R6 REVIEW/STAGING CANDIDATE; LIVE UNATTENDED MONITORING NO-GO**.  
**SQUALL R6 host acceptance:** **PASSED** on November 11, 2026 using the separately hashed post-install acceptance-resume checkpoint after a no-source-change installer invocation correction; 924 tests, 923 passed, one permitted symlink skip, zero failures/errors.  
**Production:** v0.7.0 remains unchanged. This documentation review and staging checkpoint is the sole separately authorized Git index change; no v0.8.0 commit, push, merge, tag, release, enrollment, notification, live diagnostic or deployment is authorized.

## 1. Purpose and independent review method

R6 is a separate, *negative-capability* audit of the R1–R5 security and lifecycle contracts. It evaluates whether the offline evidence can reasonably support release claims, explicitly separates synthetic acceptance from trusted operational evidence, and carries forward **SEC-01–SEC-10** as release gates. This is not a real-time scanner, an operational security authority, or a path to enabling unattended polling.

The R6 additions are exactly:

- `windows/monitoring/v080/OnyxOfflineIndependentSecurityReview.py` — deterministic, pure synthetic-evidence classifier and conservative release decision;
- `tests/monitoring/v080/test_offline_independent_security_review.py` — independent adversarial cross-component tests using the **actual checked-in** R1–R5 module interfaces and synthetic fixtures;
- `docs/v0.8.0/R6_OFFLINE_INDEPENDENT_SECURITY_REVIEW.md` — this evidence matrix and non-release contract.

R6 neither edits nor imports production state. It does not authorize any Windows identity, authenticated revocation, real filesystem protection, worker containment, scheduling, delivery, Pi access, SSH, USB probing, or task execution. Its sole CLI option is `--check-inert`; no other CLI action is supported. It uses no OS, filesystem, network, subprocess, scheduler or clock APIs in its runtime audit functions. The CLI prints an inert, NO-GO declaration.

## 2. Review inputs and trust separation

**Source-derived facts reviewed:** R1 Windows trust, R2 execution/evidence, R3 incident journal, R4 operator/delivery, R5 lifecycle/timing; original M5 integration-security audit; original production/runtime separation and test limitations; SQUALL-hosted R5 acceptance and commit output. R6 checks real module `check_inert()`/`inert_status()` signatures against independent, exact expected *negative capability* contracts. Test fixtures never become genuine authorization.

**Host verification required (independent of the R6 JSON fixture):** the guarded original installer, recovery acceptance and staging review must pin all **38** prior M1–M5/R1–R5 source/document/config SHA-256 values, verify the exact parent and unchanged production HEAD, confirm the original collector backup hash, both distinct protected five-file v0.7 histories, and pre/post XML exports of all **three** audited Scheduled Task definitions. It must independently run the entire discovered Python suite and validate the exact new three-member source ZIP before a **CreateNew**-only initial installation. The separate review/staging checkpoint may amend **only this Markdown document** to the reviewed byte-exact preview and stage exactly three R6 files; no Python source or task modification is permitted.

**Crucial distinction:** `component_hash_claims`, synthetic CLI fields, test-count JSON, and SHA-256 event chains supplied as *data* are neither cryptographic attestation nor proof of trusted Windows state. The R6 classifier explicitly reports `offline_771_host_attested=false` and `live_security_evidence_verified=false`; the **PowerShell checkpoint**, not user-supplied JSON, verifies offline source hashes, tests and preserved assets. Even a successful host checkpoint cannot establish live security.

## 3. Traceability and unresolved release blockers

| Finding | R1–R5 evidence / reviewed boundary | Release disposition | Evidence still required for closure |
|---|---|---|---|
| **SEC-01** Operator consent | R1 synthetic grant/revocation; no independently authenticated identity | **BLOCKED** | Per-cycle authenticated Windows operator consent, authoritative revocation and fail-closed behavior |
| **SEC-02** Filesystem and account trust | R1 verifies *mock* SID/ACL/path snapshots, not actual NTFS handles | **BLOCKED** | Real token/session, inherited ACL/ancestor and race-safe final-path/source validation |
| **SEC-03** Process containment | R2 evaluates synthetic job/deadline phases, not a real Windows worker | **BLOCKED** | Atomic Windows job-object/start-suspended containment with descendant and timeout evidence |
| **SEC-04** Read-only evidence | R2 model is synthetic; legacy v0.7 collector writes to v0.7 release history | **BLOCKED** | Independently reviewed v0.8-only non-mutating evidence adapter; no protected-store access |
| **SEC-05** Evidence and trusted time | R2 synthetic observations; R5 supplied wall/monotonic times | **BLOCKED** | Authentic live observation, trusted clock and drift/rollback semantics |
| **SEC-06** Incident durability/authenticity | R3 synthetic SQLite; R4 synthetic action log; unkeyed hashes do not authenticate malicious writers | **BLOCKED** | Race-safe v0.8-only state, ACL/authenticity, crash-safe recovery, backup/retention evidence |
| **SEC-07** Operator actions | R4 fake grant actor; M4 view static | **BLOCKED** | Authenticated action protocol and safe live view/operator authorization |
| **SEC-08** Notification delivery | R4 `SimulatedWouldSend` is not delivery; R5 starts no service | **BLOCKED** | Opt-in provider, authenticated delivery journal, dedup and explicit consent |
| **SEC-09** Windows symlink test | One known M2A symlink creation test skipped on ordinary SQUALL account | **OPEN TEST GAP** | Separately authorized adversarial Windows symlink fixture exercise |
| **SEC-10** Runtime timing | R5 deterministic intervals, quarantine, no worker/task/clock attestation | **BLOCKED** | Independently measured bounded live cadence, overlaps, restart/jitter and containment |

**Independent conclusion:** R1–R5 provide useful specification and offline regression coverage but do not form an authenticated or fail-safe production trust chain. R6 cannot close any of these gates by observing the other modules' own boolean declarations. The presence of a known test gap is not consent to elevate or modify Windows settings.

## 4. Audited cross-component invariants

1. **Synthetic trust cannot promote synthetic evidence.** R1 mock account/SID/ACL claims combined with R2 synthetic evidence must never yield live operator authorization or verified health.
2. **Synthetic persistence is not operator identity.** R3 and R4 temporary SQLite can maintain internally consistent fixture state, but they do not authenticate an actor, make a real store safe, send a notification, or modify protected v0.7 state.
3. **A synthetic scheduled transition is not execution.** R5 `Due`, `Running`, `FailedClosed`, restart quarantine, and clock boundaries are state-machine projections, not actual Windows process/task/clock events. R5 `task_creation_authorized=false` exists; `task_created` is **not** an R5 field (it is an R4 field). R6 rejects attempts to misstate this contract.
4. **No aggregated privilege.** Combining five components with `simulation_only=true` cannot grant capabilities absent from each component. No positive `GO`, live evidence, enrollment, or operator authorization claims are accepted as R6 inputs.
5. **Fail closed against altered evidence.** Exact source/status schemas, component SHA-256 *claims*, precise test outcome counts, unique JSON fields, and allowed skip identifiers must match or the classifier rejects the fixture. Malformed JSON, unknown findings, altered capabilities and forged successful outcomes are not silently normalized.
6. **A passed test is not live attestation.** The R6 output retains `NO-GO` even for exactly 771 previously accepted offline tests (770 passes and the documented skip, or 771 passes with no skips).

## 5. R6 audit interface and tests

- `SOURCE = OnyxV080R6OfflineIndependentSecurityReview`; `SCHEMA = onyx-r6-offline-review-v1`; `PROVENANCE = SyntheticEvidenceOnly`.
- `example_evidence()` returns a labeled, deterministic **test fixture**, not observed host facts.
- `parse_evidence(raw_bytes)` rejects oversized/malformed JSON, duplicate keys, invalid UTF-8, and nonfinite JSON values.
- `assess_offline_evidence(fixture)` validates exact test and component claim schemas; returns 10 traceable findings, `offline_claim_consistency=PASS`, and **always** `live_release_decision=NO-GO`, `live_security_evidence_verified=false`, `runtime_enabled=false`, `notification_enabled=false`, `delivery_permitted=false`.
- `inert_status()` and `--check-inert` explicitly refuse task creation, runtime, live probing, real-state authorization, delivery and repair.
- The new R6 test module includes **153 discoverable tests** in an isolated rehearsal: independent R1–R5 inert API comparisons; real R3/R4 temporary fixture initialization and R5 synthetic transition; adversarial field mutations for every R1–R5 inert key; forged operator/GO/delivery/clock/authentication claims; malformed JSON; test-count/skip tampering; provenance and closure checks; and CLI denial.

**Host test gate (PASSED on SQUALL):** **771 preexisting + 153 R6 = exactly 924 cases**. The same two actual v0.7 reducer compatibility tests must be present and pass. The only permitted skip remains `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory` if Windows refuses symlink creation. Expect **923 passes / 1 skip / 0 failures**, or **924 passes / 0 skips / 0 failures**. Any additional skip or test error is a stop condition. The accepted 924-case offline pass permits the separately authorized Markdown review and exact-three-file staging checkpoint, **not** runtime enablement or a GO decision.

## 6. Guarded SQUALL installation and preservation

- Require Windows PowerShell 5.1, ordinary **non-elevated** session, expected Python 3.13, and exact clean `D:\github_repos\onyx-core-v080` branch/parent `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4`.
- Refuse staged, modified or untracked development files before installation. Refuse reparse-point directories, preexisting target files, unknown ZIP members or mismatched ZIP/member hashes. Create exactly three R6 files via no-overwrite `FileMode.CreateNew`; if creation is partial or later checks fail, **do not rerun** or clean up without review.
- Recheck all 38 pinned old artifacts, original collector backup, untouched production repository (`main` at `06ec81582791fc797f74ad294195d68b2023cb66`), both five-file protected history inventories and three exported Scheduled Task definitions before and after tests.
- Assert inert R1–R6 and M1–M4 interfaces, specifically R5 `task_creation_authorized` (not nonexistent `task_created`), plus R6 negative GO/notification/authorization claims. Validate that only the three new R6 files remain untracked with their original SHA-256 values; no staging, no commit.

## 7. Release decision and separate authorization boundaries

**R6 development verdict:** **offline host acceptance PASSED** and documentation review/staging separately authorized; successful staging does not authorize a commit. **v0.8.0 live unattended release verdict: NO-GO.** Remaining SEC-01–SEC-10 closure evidence requires separate, explicit consent and appropriately scoped Windows/security testing before any production-readiness claim. R6 does not quietly re-label blockers as mitigated or “done.”

The user has **separately authorized documentation review and exactly three R6 additions staged**, contingent on the guarded hash/blob, 924-test and preservation gates; the user has **not** authorized a commit, push, merge, tag, release, deployment, live diagnostic, elevation, enrollment, notification, Scheduled Task modification, or repair. The current reviewed staging checkpoint is conditional on the same signed-off source inventory and 924-test acceptance; any subsequent single local commit requires **new, separate authorization**. Existing v0.7.0 production behavior stays untouched.

## 8. SQUALL host acceptance, installer defect and review boundary (2026-11-11)

**Host evidence:** the initial R6 installer successfully validated the exact R5 parent, 38 prior artifacts, the two protected five-file monitoring histories and three audited Scheduled Task definitions, and created the **exact three** SHA-256-matched R6 files. It then stopped at an installer-generated malformed Python import-path argument containing a vertical tab in place of the intended `windows/monitoring/v080` module directory. That installer run **did not complete host acceptance**; the defect was in the invocation path, not a demonstrated error in either R6 Python file.

**Recovery evidence:** the independent post-install resume script used an explicit corrected module path, verified the original R6 ZIP and all three installed file SHA-256 values again, tested the inert R1–R6 surfaces and the R6 classifier, and executed **924 discovered offline tests** on SQUALL: **923 passed, one documented Windows symlink-creation permission skip, zero failures, zero errors**. The two genuine v0.7 reducer compatibility cases passed. It finished with exactly three original byte-identical R6 files **untracked and unstaged**, a clean tracked tree, preserved production and collector backup, unchanged release/development protected histories (five files each), and unchanged exported definitions of all three audited Scheduled Tasks. The recovery did not reinstall or modify R6 source.

**Classifier disposition:** `live_release_decision=NO-GO`, `live_security_evidence_verified=false`, and ten distinct SEC-01 through SEC-10 findings remain. SEC-01–SEC-08 and SEC-10 are blocked for live operational trust; SEC-09 is an **open Windows adversarial-test gap**, not a passed platform assertion. These findings are not cleared by test count, provenance strings, unkeyed hashes or a static audit. No operational GO decision is established.

**Review/staging authorization (separate checkpoint):** only this Markdown file may be amended to its exact approved review bytes; the 153-test Python module and pure R6 review implementation must stay byte-identical to the original source ZIP. Before staging, the guard must reconfirm exact R5 HEAD `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4`, clean index and exactly three R6 untracked files, all 38 older hashes, original collector backup, production, both protected five-file histories, all three Scheduled Task definitions, explicit inert NO-GO output and the full **924-test** suite. Stage **only** the three reviewed R6 additions, require exact Git blob IDs and diff line counts, then recheck preservation. A Git commit and any subsequent action require independent authorization.

**Final live release assessment:** **NO-GO — operational security remains unverified.** Passing offline acceptance and exact review/staging checks cannot establish real Windows identity, authoritative revocation, job containment, trusted clock, live Pi/USB evidence, state authenticity, authenticated operator actions, notification delivery or a safe unattended scheduler. Production remains v0.7.0.
