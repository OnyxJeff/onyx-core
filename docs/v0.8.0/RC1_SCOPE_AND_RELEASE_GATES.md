# ONYX CORE v0.8.0-rc.1 — Candidate scope and release gates

**Status (2026-11-15): PREPARATION / NO-GO for installed or live release.**

Target version: `v0.8.0-rc.1`. The release candidate has **not** been tagged, pushed, published, deployed, or independently accepted. The current pinned development HEAD is `047a753b5506729ac782b4a0d09a6074644580ed`; production remains v0.7.0 at `06ec81582791fc797f74ad294195d68b2023cb66`.

## Intended v0.8.0 features

- Continuous-monitoring and operational-alert policy foundations (synthetic/offline validation completed in prior milestones).
- Incident state, acknowledgement and recovery lifecycle; read-only operator visibility and an isolated development dashboard.
- Native Windows authorization and foreground-session release operator prototypes, using protected source attestation and a separate v0.8 storage profile.
- No automatic repairs, scheduled monitor deployment or notification delivery are authorized in this candidate checkpoint.

**Important:** Developed or tested components are not equivalent to an authorized live release. The main production gateway remains loopback `127.0.0.1:18766`, while development validation has used independent ports. Never overwrite production tasks, collector backups or protected v0.7 monitoring histories.

## R6.1 review findings (blocking)

The R6.1 two-file proposal was independently rejected: 46/47 existing R4–R6 tests passed with one expiration regression, despite 7/7 narrow synthetic checks passing. A long-running worker can cross the session deadline; an earlier bridge authorizer lacks the deadline; R5 persistence counters can disagree with R4 completion, and M3 SQLite commits already underway cannot be undone merely by returning `EXPIRED`. The original R6 source passed 47/47 focused offline tests, which do not close these gaps.

**Do not install the R6.1 review-only patch. Do not enable `--run-session-count` or claim a hard deadline.** The existing `--run-count` path is not a substitute for an independently verified session runtime. No live operator action is approved at this checkpoint.

## Minimal RC acceptance gates

1. **Source integrity:** correct development HEAD/branch, scoped reviewed changes only, trusted artifact manifest with all executed files, no protected approval-anchor reuse.
2. **Deadline containment:** prove process-tree containment for a full runtime cycle (not only external diagnostic subprocesses), including forced termination and verified exit when authorization expires.
3. **Persistence control:** children cannot write protected journals; parent validates result and source/identity/consent before initiating a bounded transaction; define and test in-flight commit semantics rather than claiming impossible instantaneous atomic cancellation.
4. **Accounting:** after 59/60/61-second boundary, blocked recorder, revocation and errors, persisted counts represent actual writes; no `PASS` after expired work; R4's documented retry policy remains unchanged unless explicitly scoped to the release operator.
5. **Offline regressions:** rerun all existing R4–R6 tests and the wider v0.8.0 suite with adversarial additions; zero unexplained failures or skips.
6. **SQUALL host acceptance (separately authorized):** native Windows Job Objects, process descendants, locks, ACL/source checks, clocks, cleanup and rollback, without modifying protected v0.7 assets.
7. **Release authorization:** separate review/approval before commit, merge, tag, push, protected installation, credentials, live probes, recurring tasks, notification or repair.

## README and versioning policy

The root `README.md` should distinguish **production v0.7.0** from **v0.8.0-rc.1 in preparation**. The RC is not the latest published release and must not replace the live release badge or production-deployment statement. After all gates pass and publication is separately authorized, change the README to the verified released version and link the actual release/tag.

## Verification notes

- Original R4–R6 source archive (`047a753`): 47/47 focused offline tests passed on a disposable Python 3.13.5 checkout during candidate preparation.
- This document and a README version update are **documentation-only changes**; they do not resolve the R6.2 deadline blocker.
- No claims are made about full-suite or Windows host acceptance from these archive-only checks.
