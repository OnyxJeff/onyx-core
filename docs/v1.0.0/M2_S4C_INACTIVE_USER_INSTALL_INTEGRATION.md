# ONYX CORE v1.0.0 — M2-S4C: Integrated User-Scoped Installation Acceptance

Status: **offline development only; native SQUALL acceptance pending**. This does not authorize a persistent Windows installation.

## Scope

Combine the 17-file M2-S4B integrated Windows runtime with the existing M2-S2C user-scoped receipt and ACL callback workflow. The three S4A-derived assets (collector, gateway DPAPI helper, and runtime launcher) must appear in the user installation inventory together with the versioned dashboard and isolation manifest. All inputs and intermediary implementations are pinned by SHA-256.

## Explicit boundaries

- Public CLI implements **only `preview-user`**, using native Windows Known Folder / LocalAppData validation. It does not have a native installation or credential-enrollment command.
- Unit tests exercise `user.install_inactive()` in new OS Temp `OnyxV100-S4C-TestRoot-*` fixtures with an injected synthetic ACL callback. **This is not a native ACL test**. A synthetic receipt contains `acl_hardened: true` because it reuses the original installer API, but the S4C test report explicitly identifies `synthetic_acl_only: true` and `native_acl_verified: false`.
- All 16 runtime/configuration/manifest files are bound into the existing installation receipt (17 files total). Tampering with receipt or runtime is refused.
- The future v1 token location is `%LOCALAPPDATA%\OnyxCore-v100\collector-token.dpapi`; this step does not open or create it. No fallback to `%LOCALAPPDATA%\OnyxCore\collector-token.dpapi` or the original collector mutex.
- Reserved gateway ports 18766–18769 are refused. Native read-only SQUALL preview uses loopback port 18976.
- No production changes, monitoring histories, Scheduled Tasks, collector/gateway processes, network probes, token reads or writes, Pi access, Git commits, pushes, deployments, or persistence.

## Native acceptance

1. Require M1 development HEAD `8df66f7`, production `main` `06ec8158`, and all 33 approved M2 development files with exact SHA-256.
2. Verify the original M2-S1 runtime ZIP and M2-S2A dashboard, and exact 3-file S4C ZIP.
3. Stage SHA-256-pinned S4B, S2B, S2C, S4A, and ACL sources; run 22 tests, including native Windows Known Folder read-only preview and Temp-only synthetic installation.
4. Add precisely three untracked development files; repeat tests using the installed source.
5. Execute one additional read-only `preview-user` against a new absent LocalAppData target, verify 17-file plan and no directory creation.
6. Confirm 36 expected untracked development files, unchanged tracked files, commits, runtime ZIP, dashboard, and original backup.

## Separate future authorization gates

- Native ACL validation on actual Windows user-profile installation, then explicit approval for a **persistent inactive** install.
- Credential enrollment into the new v1 DPAPI store without exposing the token in logs, process arguments, or checkout.
- Pi native ARMv6 installation, isolation, and activation acceptance.
- Live collector/gateway execution, task registration, restarts, production cutover, rollback, and release commit/deployment.
