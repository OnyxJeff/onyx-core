# ONYX CORE v0.8.0 — M5 Deployment Prerequisites and Rollback Plan

**Classification:** PLANNING ONLY. **No executable deployment commands or authorization are included.**  
**Baseline:** v0.8.0 offline branch at `27071dcdbb41616096107bfa3a7fcc8be337b7ce`; production `main` `06ec81582791fc797f74ad294195d68b2023cb66`.  
**Live readiness:** **NO-GO**; required implementation and permission gates remain open.

## 1. Scope separation

M5 may document a future rollout, but must not copy code to an active runtime, start services, enable tasks, enroll an account, run an SSH probe, read/modify credentials, or publish a release. The protected v0.7.0 release/development monitoring histories remain immutable. The original collector, local gateway, ICS recovery mechanism and LibreHardwareMonitor tasks retain their current definitions. There is no supported live v0.8.0 package to install yet.

**Rollback of an uncommitted M5 documentation check:** no service was installed or configured. The safest action is to **stop and inspect the exact Git status**, not to reset repositories, delete protected files, or rerun a partially completed installer. A later separately approved documentation cleanup may remove only individually verified M5 files; nothing in this plan authorizes that cleanup now.

## 2. Future deployment prerequisites (all require separate approval)

| Gate | Minimum evidence before proceeding |
|---|---|
| Identity, source and enrollment | Real approved Windows token/session, verified binary+imports and ACL ancestry, independently captured operator grant, monotonic revocation, disabled-by-default behavior |
| Safe worker | New read-only v0.8.0 evidence adapter; verified destination and signed/hashed worker inputs; job/child-tree kill containment, timeouts, locks; no v0.7.0 release collector invocation |
| Isolated storage | New `%LOCALAPPDATA%\OnyxCore-v080\Monitoring` with explicit authorization and tested atomic init, crash recovery, bounded retention and full denial of v0.7.0 data paths |
| Cadence and evidence | Tested sample freshness, 3 correlated observations, health vs incomplete evidence, 2 healthy recovery samples 30–300 s apart, jitter/sleep/restart/overlap bounds |
| Alert integrity | Durable replay and intent dedup, restart replay behavior, idempotent acknowledgement and delivery journal; real notification delivery requires additional approval |
| Task installation | Reviewed task definition and principal, logon/trigger behavior, no privilege elevation by default, fixed schedule and skip-overlap behavior, independently approved install and disable/rollback |
| Backup and rollback | Captured pre-change task XML, source commit, hashes, baseline health, original collector and exact five-file histories; tested restore from isolated copy without overwriting v0.7.0 history |
| Operator sign-off | Explicit authorization for each promotion step, environment and rollback conditions; separate approval for any genuinely live diagnostic |

## 3. Proposed future rollout stages — NOT AUTHORIZED NOW

1. **Candidate assessment:** review security audit and close all blockers. Re-run offline suite and host trust checks on the precise candidate bytes; sign off on the remaining skip or run its adversarial scenario in an approved controlled test environment.
2. **Deployment dry run in isolation:** use a disposable, non-production Windows environment with synthetic input and only newly created v0.8 state; verify scheduling and crash/kill behavior without credentials or network traffic.
3. **Pre-change backup and observation:** obtain authorized baseline definitions/hashes of relevant tasks; verify both v0.7.0 histories (including `.json.lock`) and collector backup byte-for-byte; choose maintenance window and decision owner.
4. **Distinct, disabled installation:** only after authorization, install into a new trusted path and v0.8-only state; no v0.7.0 script scheduling or policy bypass. Installation must not imply execution.
5. **Bounded explicit acceptance:** any real probe requires its own authorization and preflight. Confirm unknown-state and no-repair behavior first; never infer a live health result from synthetic output.
6. **Enablement decision:** only a fresh, separate approval may authorize recurring execution or notification. Document expected start/stop behavior and on-call response.
7. **Observation and promotion:** monitor under a defined time window and measurable exit criteria; production Git merge/tag/publication is a separate decision from enabling services.

## 4. Future stop / rollback triggers

Immediately halt planned progression for altered protected history hashes, changed task definitions, wrong production/source revision, revoked or unverifiable grant, unknown identity/ACL, directory redirection, an uncontained worker, unexpected network or filesystem writes, duplicate delivery, evidence incomplete yet shown healthy, premature recovery, or any indication of repair behavior. **Unknown is not Healthy.** Failure to meet an acceptance gate is a stop, not a reason to loosen the policy.

## 5. Future rollback design — no operation now

**First:** stop any *new* v0.8 scheduled execution using its separately authorized disable/revocation path; prevent new cycles and coordinate in-flight bounded tasks without truncating atomic writes. Revoke permission independently of Task Scheduler state. Do not disable the preexisting collector, gateway, LibreHardwareMonitor or ICS recovery tasks.

**Second:** restore only the separately inventoried **new** v0.8 runtime configuration, task and sources using tested copies. Preserve original v0.8 incident/alert records for later audit when lawful; do not blindly delete or reset state to silence an alert. If a new task was never installed, no task rollback is necessary.

**Third:** verify the original production commit, collector backup SHA-256 and all five files in both protected v0.7.0 histories; the rollback process must **not rewrite those histories** or replay new incidents into them. Do not use `git reset --hard`, `git clean -fd`, deletion of `%LOCALAPPDATA%` stores, or a v0.7.0 collector invocation as a substitute for rollback.

**Fourth:** confirm current scheduled task definitions still match the authorized baseline and that normal existing ONYX CORE services are not inadvertently interrupted. Record evidence, outstanding state and a distinct operator decision before a retry.

This is a **rollback specification**, not an executed rollback or tested recovery. A future live deployment requires its own implementable runbook, reproducible backups and a successful approved rollback drill.

## 6. M5 documentation-only exit

For M5 as authorized today, the exit criteria are exactly four new untracked Markdown documents, a successful 301-test offline suite, unchanged production/collector/protected histories/tasks, and no commit or deployment. Anything beyond that requires a new operator instruction.
