# ONYX CORE v1.0.0 — M2-S5E: One-Shot Inactive Windows Installation Contract

**Status:** DEVELOPMENT / TEST ONLY. This checkpoint is **not permission** to create a LocalAppData installation. The public S5E CLI is **preview-only**, and the package does **not** include a persistent installation runner.

## Locked inputs

- M2 source checkpoint: `00c6ba630a18b054308bb7119b610602790e44be`.
- SHA-256-pinned M2-S5D read-only preflight and inherited S5C publisher, S4C 17-file payload builder, R3 safe DACL, S5B Win32 no-overwrite logic, M1 configuration validator.
- Core runtime candidate SHA-256: `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- Reviewed v1 dashboard SHA-256: `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`.
- Native SQUALL preflight plan SHA-256: `77426cdc3207fe96404f04dd410d7c8d00b0d7f36dd46c855fbfe719102a5bd4`.

## Exact prospective operation

The *only* future target is the **new** direct child `%LOCALAPPDATA%\OnyxCore-v100-Inactive-Stable100` as resolved by the Windows Known Folder API; no caller-controlled path. The installation would contain 16 reviewed payload files plus one SHA-256 installation receipt. The settings are pinned to source `SQUALL`, receiver `svr-onyxcore.local:8765`, gateway port `18976`, normal adapter `Ethernet`, USB adapter `Ethernet 3`, interval 30 seconds.

The private one-shot function (not exposed in CLI) revalidates the entire S5D plan, fixed target, SHA-256 file inventory, source code and native user identity immediately before publication. It uses S5C's safe DACL-only hardening and Windows native same-volume no-replace publication. It must reject an already-existing directory, link/junction, changed package, unreviewed helper, mismatched plan or wrong platform. A failed write must report `INCOMPLETE` and retain evidence; **no automatic cleanup, retry, overwrite, or fallback**.

The private function takes an explicit **authorization declaration** whose fields must match the target and reviewed plan. Such a declaration is only a programmatic safeguard, **not proof of human permission**. A future separately reviewed one-shot caller must be prepared only after the user explicitly authorizes the precise LocalAppData filesystem write. No such caller is included in M2-S5E.

## Current acceptance

The M2-S5E acceptance script may: inspect approved source/Git, export committed files to Windows Temp, run synthetic offline tests, execute the read-only user preflight and reverify it, and reuse S5C's already-accepted *Temp-only* native integration fixture. The new 3-file development patch may be copied into the development worktree only after these checks pass.

It may **not** create `%LOCALAPPDATA%\OnyxCore-v100-Inactive-Stable100`, enroll/read DPAPI credentials, connect to the Pi, change Scheduled Tasks, start collectors/gateways, modify production, stage Git, commit, push, merge or tag. Keep existing successful/failed Temp fixtures intact.

## Next separately authorized gate

After native SQUALL acceptance, review the exact one-shot caller (including hash, approved target and plan, audit/receipt results, and failure behavior) and obtain explicit authorization for **one inactive, persistent Windows installation only**. Credential enrollment, startup registration, live telemetry and Pi operations are distinct later approvals.
