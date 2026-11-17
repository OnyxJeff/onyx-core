# ONYX CORE v0.8.0 — Deployment and Rollback Plan (M6 DRAFT)

**Status:** PLAN ONLY — do not execute production cutover yet.

## Immutable baseline as audited

- Production working tree: `D:\github_repos\onyx-core`, branch `main`.
- Production HEAD and `v0.7.0` tag: `06ec81582791fc797f74ad294195d68b2023cb66`.
- Development worktree: `D:\github_repos\onyx-core-v080`, branch `feature/v0.8.0-continuous-monitoring`, M1–M5 commit `595f9320491ae6efe2f505d0866e6740b22c8052`.
- Production tasks: `ONYX CORE - Local Gateway` (`C:\Python313\pythonw.exe`, entrypoint `OnyxGateway.py`) and `ONYX CORE - Telemetry Collector` (`C:\WINDOWS\System32\wscript.exe`, entrypoint `Launch-OnyxTelemetry.vbs`) both observed Running. Task actions were checked for expected production repository paths and no development-worktree references. Full arguments were intentionally not printed; nested launcher behavior remains to be documented locally.
- `ONYX CORE - ICS Startup Recovery` Scheduled Task **not installed** at audit.
- Production contains untracked `windows/collector/Send-OnyxTelemetry.pre-v050.bak`; preserve it byte-for-byte. Observed SHA256: `59E1EE7205EFBEDB79BA3D0DCB4C9FD0D8EBD3DFA4D5D9313BBD8325976830EB`.
- Production gateway URL: `http://127.0.0.1:18766/dashboard`; development M4 test URL: `http://127.0.0.1:18767/dashboard`.

## Mandatory predeployment gates

1. Confirm `v0.7.0` resolves to the expected SHA, production branch is `main`, and the intended v0.8 candidate SHA is reviewed. Verify commit ancestry/divergence and candidate diff, not just a short SHA.
2. Preserve the untracked collector backup and record its SHA256; never `git clean -fd`, `git reset --hard`, or overwrite in place without a separately approved preservation plan.
3. Inventory actual Scheduled Task action arguments and nested launcher paths **locally**; store task exports securely (they may include sensitive command-line material). Record a reversible target for each launcher.
4. Decide whether the release simply lands opt-in code without enabling M2/M5, or whether a separate production activation design will be reviewed. Existing M3/M5 paths explicitly use a **development** user store, and M4 refuses to share `18766` when opted in.
5. Preserve current DPAPI token, production receiver/overlay configuration, task principal, triggers, and working fallback; do not copy secrets into release notes or PRs.
6. Re-run M1–M5 offline tests (82 passed previously), the eight localhost M5 integration assertions, and regression checks on the final release candidate.
7. Document how optional workers are stopped. Make *no* automatic Scheduled Tasks, webhook deliveries, network repairs, ICS changes, Pi downtime or token migrations.
8. Obtain operator approval and schedule a monitored window **before any production changes**.

## Suggested non-disruptive deployment sequence (requires approval)

1. Review/merge the approved v0.8 PR; record the exact merge SHA and changes relative to `v0.7.0`.
2. Keep the production gateway/collector tasks pointing to their existing tested executables and launchers unless a reviewed reason to change them is documented.
3. Verify production dashboard, overlay endpoints, and collector-to-Pi telemetry while the v0.8 code remains dormant. Do not assume the M2 monitor or M5 watcher is active.
4. Run isolated smoke tests under the intended account with no secret leakage, and confirm the selected development/production data-store boundary.
5. If a separate gateway instance is intentionally launched, use a distinct loopback port, verify binding and HTTP behavior, then stop it explicitly. Do not silently alter `18766`.
6. Record results and preserve a go/no-go decision for each optional activation. A new task/service or provider integration belongs in a separately reviewed change.

## Completed non-destructive source and startup rehearsal (M6 Phases 10–11)

- The `v0.7.0` tag was verified against production HEAD, with production tracked files unchanged and the untracked collector backup preserved.
- A `git archive` of four critical gateway/collector files was compared with their raw Git objects. The archive had CRLF line endings while Git blobs used LF; replacing CRLF with LF matched all four raw blobs exactly. Do not treat a raw ZIP-file-versus-blob mismatch alone as corruption when line endings differ.
- The full `v0.7.0` archive was extracted into a disposable directory; after supplying a **disposable non-secret stdin token** to satisfy the gateway's legacy credential-loading path, a separate v0.7 gateway returned HTTP 200 on `127.0.0.1:18768`.
- The temporary process was stopped and the staging directory removed. Production dashboard `127.0.0.1:18766` remained HTTP 200, and the original production commit and collector backup hash remained unchanged.
- This smoke test **did not** load DPAPI credentials, authenticate the Pi telemetry proxy, test overlays, change any Scheduled Task, cut over production or demonstrate a complete reverse cutover. Those remain release gates.

## Rollback trigger conditions

Unrecoverable production dashboard or collector regression, inaccessible existing telemetry, incorrect DPAPI token use, unauthorized external alert delivery, unexpected network bind, data-store contamination, or unplanned changes to task/ICS behavior.

## Operational rollback plan (not rehearsed)

1. Stop only *newly introduced* v0.8 test processes or optional watcher instances using their recorded PIDs/foreground windows. **Do not** indiscriminately terminate Python or existing production tasks.
2. Restore original launch targets/settings from the secure predeployment task inventory/export **only if they had changed**, observing the originally documented account and trigger. Avoid changing the v0.7.0 task definitions unnecessarily.
3. Re-establish the proven v0.7.0 application files using the retained `v0.7.0` tag and a **non-destructive, approved Git procedure** (e.g., separately prepared tagged worktree or reviewed revert) that preserves untracked files. Do not hard reset or clean the production repository.
4. Validate `http://127.0.0.1:18766/dashboard`, required overlays, telemetry collector task and fresh data. Confirm the production version target again.
5. Preserve incident-history/cursor files for forensic inspection; do not delete or rewind a cursor as an automatic rollback step. Reconcile event ID identity before re-enabling any alert watcher.
6. Record observed results, operator decision, the actual repository SHA and task states.

**Important:** The concrete production file/Task cutover and rollback commands cannot be finalized until the actual action arguments, launcher indirection and final merge strategy are reviewed. This plan intentionally contains no destructive Git or task-control commands.

## Stop/go matrix

| Observation | Decision |
|---|---|
| Production HTTP 200 and telemetry fresh; no unexpected changes | Continue checks |
| M4 says `Stale` but telemetry is live | Record freshness of M3 separately; do not call it a USB failure |
| Production gateway/collector stops responding following cutover | STOP, invoke reviewed rollback |
| M5 claims journal behind cursor | STOP notification watcher; preserve cursor and journal |
| M2/M3 unexpectedly writing into real/development store | STOP activation, investigate identity/paths |
| Unreviewed task/ICS changes or unapproved external requests | STOP immediately |

## Rehearsal evidence still required

- Review and securely preserve exact production Task Scheduler actions and nested launcher dependencies, task principal/triggers, overlays, and DPAPI behavior. Expected entrypoints and production repository references were confirmed, but complete launcher restoration has not been exercised.
- Plan and approve the exact merge/deployment changes and the reversing procedure without destructive Git cleaning/resetting, with the collector backup explicitly preserved.
- Independently establish loopback-only binding for the approved production topology; HTTP response success alone does not prove listener confinement.
- Run a **separately approved** reversible operational cutover/rollback exercise that includes authenticated telemetry and overlays, then document operator go/no-go. The isolated `18768` startup test is not a substitute.
