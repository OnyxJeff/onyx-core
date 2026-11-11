# ONYX CORE v0.8.0 — Phase C DOC-01 / DOC-02 Chronology Reconciliation (Draft)

**Document class:** Additive chronology note; **status:** DRAFT FOR REVIEW, not installed or committed.  
**As-of:** November 11, 2026. **Authority:** Historical SQUALL acceptance/commit transcripts and the successful post-R6 read-only audit.  
**Principle:** Preserve the original M5 and R6 documents **byte-for-byte**. Their prior statements were time-bound and should not be retroactively rewritten as if they anticipated later approvals.

## 1. Why a new chronology record is needed

The post-R6 audit passed source, commit ancestry, and preservation checks but surfaced two documentation-context findings. These are not source corruption or runtime incidents; they arise because checkpoint Markdown was reviewed at a moment when the next approval had not yet occurred. An *additive* dated record makes the sequence legible without falsifying the historical approval boundary.

| ID | Original claim in its checkpoint context | Later verified event | Reconciliation |
|---|---|---|---|
| **DOC-01** | `docs/v0.8.0/R6_OFFLINE_INDEPENDENT_SECURITY_REVIEW.md` says R6 staging/commit is a separately authorized future step and explicitly disclaims commit authorization | The user later authorized one local commit; SQUALL committed exactly three R6 additions (664 lines) as `6e4ddef5a30e36742387432448f67e8dcf8bd469` after 924-case acceptance | Treat the R6 document as an accurate *pre-commit* contract. This new record supplies the *post-commit* state; original R6 file remains untouched |
| **DOC-02** | `docs/v0.8.0/M5_RELEASE_READINESS.md` and the M5 integration audit describe an M5-time documentation/test status with staging or commit to follow | Subsequent isolated R1–R6 development progressed to a completed, verified R6 commit and a passing read-only integration audit | M5 remains an *M5-time* readiness snapshot; it never established live v0.8 GO, and does not override the R6 ten-gate NO-GO finding |

## 2. Evidence chronology (source- and transcript-grounded)

1. **2026-11-10, M5 offline checkpoint:** 301 discovered tests; 300 passed; one permitted Windows symlink-creation skip; no errors/failures. M5 documentation recorded an offline-only, NO-GO decision. Its own staging and commit were outside the original installer scope.
2. **R1 through R5:** Six-stage post-M5 trust/lifecycle work began. Each R1–R5 change was separately reviewed and committed locally. R5 checkpoint evidence on **2026-11-11** recorded 771 tests: 770 passes, the known single skip, and zero errors/failures. R5's initial installer had a guard-property mismatch (`task_created` versus actual `task_creation_authorized`); recovery left its source intact.
3. **2026-11-11, R6 initial install:** Original source files were created correctly, but the installer hit a malformed Python module directory argument with a hidden vertical-tab character. No host test result was claimed from that failed run.
4. **2026-11-11, R6 acceptance-resume:** A dedicated read-only/revalidation recovery gate operated on the existing three original files; it accepted **924 tests: 923 passed, one permitted skip, zero failures/errors**, including the genuine v0.7 reducer tests. No reinstallation, source rewrite, staged files, or commit resulted.
5. **2026-11-11, R6 review/staging:** The first staging script stopped before writing due to PowerShell-to-Python quoting; a corrected script verified the original bytes, reran 924 tests, amended *only* R6 Markdown to its approved 88-line version, and staged three files (664 insertions). No commit at this step.
6. **2026-11-11, R6 local commit:** A separately authorized guarded commit script reran the 924 cases (923/1/0), created direct-child commit `6e4ddef5a30e36742387432448f67e8dcf8bd469` from R5 `7f22513e82c2a27dcbddad9a8e1d3203ae75e2d4`, and verified clean development Git, 41 source hashes and all protected assets.
7. **2026-11-11, Phase A post-R6 read-only audit:** Verified direct-parent R1–R6 ancestry, three files per commit, R6 Git blobs/664 insertions, 41 pinned hashes, exact production and development HEADs, clean repositories, original collector, both protected five-file monitoring histories and three unchanged Scheduled Task XML definitions. The script explicitly **did not rerun tests** and reported **source/history/preservation PASS; live release NO-GO**.
8. **2026-11-11, Phase C planning:** This draft is being prepared **outside Git** for operator review. There is no newly authorized staging, commit, remote operation, test rerun or live execution.

## 3. Evidence hierarchy and nonclaims

The direct local audit establishes SHA-256 matches, Git history and clean worktrees at audit time, and before/after protected snapshots. The operator-provided SQUALL stdout records the historical 924-test execution; it is not a signed independent live-monitoring trace. R6 `NO-GO` comes from an intentionally conservative synthetic classifier and release assessment; it is not an authenticated live health or Windows security measurement.

**No approval is retroactive.** Each later staging or commit authorization applies only when issued, and does not rewrite what an earlier document was permitted to do. All security findings remain open under their original IDs: SEC-01–SEC-08 and SEC-10 **BLOCKED**; SEC-09 **OPEN TEST GAP**.

## 4. Recommended future documentation mechanics (NOT authorized here)

If the operator later approves repository documentation finalization, add a **new** dated Phase C document set under `docs/v0.8.0/` referencing the existing M5 and R6 records. Do not edit those historical files solely to erase time-bound phrases. Any Git add/commit, PR, push, merge or release must have separate explicit authorization and a new guarded checkpoint.
