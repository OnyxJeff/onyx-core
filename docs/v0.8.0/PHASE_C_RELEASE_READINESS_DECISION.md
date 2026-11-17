# ONYX CORE v0.8.0 — Phase C Release-Readiness Decision Record (Draft)

**Decision ID:** `ONYX-v080-PHASEC-2026-11-11-DRAFT`  
**As-of:** November 11, 2026. **Document status:** DRAFT, for operator review; **not an approved release decision signed by the operator**.  
**Development commit examined:** `6e4ddef5a30e36742387432448f67e8dcf8bd469` (`feature/v0.8.0-continuous-monitoring`).  
**Production baseline:** `06ec81582791fc797f74ad294195d68b2023cb66` (`main`, v0.7.0).  
**Recommended operational decision:** **NO-GO for v0.8.0 live unattended monitoring, production merge/deployment, tag and release publication.**

## 1. Distinct decisions: development versus live release

| Decision target | Evidence-based position | Meaning |
|---|---|---|
| R1–R6 **local offline development checkpoint** | **PASS (historically verified)** | Six reviewed local commits, direct-parent chain, R6 three approved files/664 insertions, 41 pinned hashes and clean repository state at Phase A audit |
| R6 **offline regression acceptance** | **PASS (historical SQUALL transcript)** | 924 tests discovered; 923 passed; one known symlink-creation skip; no failures/errors; genuine v0.7 reducer compatibility tests passed. **No fresh 924-test execution in Phase A or Phase C planning** |
| Windows identity, consent, path safety, process containment, live evidence, incident authenticity, operator actions, notification and timing | **NOT VERIFIED** | R1–R6 are synthetic/inert; 9 operational SEC gates remain blocked and 1 adversarial native-host test gap is open |
| v0.8.0 **live unattended release/deployment** | **NO-GO** | No approved live trust chain, enrolled service, authorized scheduler, validated provider or qualified deployment/rollback path |
| Phase C documentation preparation | **DRAFT REVIEW ONLY** | These external files do not themselves authorize a Git change or release |

## 2. Basis for the NO-GO recommendation

R6 independently refuses to aggregate synthetic modules into a runtime capability. Its inert interface explicitly returns `live_release_decision=NO-GO`, `live_security_evidence_verified=false`, `runtime_enabled=false`, `task_creation_authorized=false`, `enrollment_authorized=false`, `live_probe_authorized=false`, `notification_enabled=false` and `delivery_permitted=false`. The audited R6 contract lists SEC-01–SEC-08 and SEC-10 as **BLOCKED**, SEC-09 as **OPEN TEST GAP**.

The Phase A audit confirmed the local tree's integrity, provenance and protected-state preservation. This is a source/inventory finding, not a guarantee of live user consent, trusted Windows handles/ACLs, worker confinement, safe store writes, authenticated incident state, actual delivered alerts or measured scheduler behavior. Even complete offline regressions would not change those missing real-world facts.

## 3. Evidence accepted and limitations recorded

- **Local Git and files:** R1–R6 ancestry and commit inventory verified, with R6 directly descending from R5 `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4`; exactly 664 R6 insertions; 41 source/doc/config SHA-256 values matched.
- **Historical host suite:** the separately authorized R6 commit transcript recorded `Ran 924 tests`, `OK (skipped=1)`. The skip was `test_offline_supervisor.SyntheticSupervisorTests.test_rejects_symlinked_fixture_directory`, not a passed native Windows adversarial test.
- **Production segregation:** production main and its original collector backup, both separate protected five-file v0.7 monitoring histories and the three audited Scheduled Task XML definitions remained unchanged in the audit.
- **Documentation chronology:** historical M5/R6 language (DOC-01/DOC-02) reflects earlier approval boundaries; this Phase C record is an additive explanation, not a retroactive rewrite.
- **Execution defects:** the R6 installer import-path and first staging script quoting errors were corrected through separately reviewed checkpoint scripts without altering R6 Python source. These fixes do not establish live readiness.
- **Evidence limitations:** operator-submitted command transcripts and SHA-256 consistency checks are not signed independent runtime/Windows security attestations. Phase A read-only audit **did not rerun** tests.

## 4. Conditions before reopening a live release decision

1. Each SEC-01–SEC-10 closure condition is implemented, separately reviewed, and supported by reproducible actual Windows evidence; SEC-09's native symlink case must no longer be an untested gap.
2. A distinct, specifically approved host validation plan protects production, both v0.7 stores, collector, task definitions, identities, network/USB/ICS and any future v0.8-only state.
3. A future release-candidate gate reruns the fully enumerated offline regression suite against its exact candidate sources, then independently checks live consent, containment, read-only evidence, durability, operator actions, delivery and timing. A future pass count is not assumed to remain 924 if sources change.
4. A separately reviewed deployment/rollback and release plan establishes operator approval for every potentially side-effecting activity; no implicit task creation, live probe, notification or repair.
5. A final operator-signed release decision records the commit, evidence references, remaining risks, provenance and exact authorized promotion scope.

## 5. Prohibited promotion and next authorized checkpoint

**This document does not approve a v0.8.0 release candidate, production merge, tag, GitHub release, site update, deployment, new Scheduled Task, enrollment, live probe, notification transport, elevation, repair, or Git staging/commit.** The next permissible step under the current authorization is **read-only review of these four Phase C Markdown drafts**, supported by the unchanged post-R6 read-only audit and pinned package hashes. Any installation into `docs/v0.8.0/`, staging or local commit requires separate explicit authorization.

**Decision in this draft: offline milestone documentation eligible for review; operational release remains NO-GO.** Production stays v0.7.0.
