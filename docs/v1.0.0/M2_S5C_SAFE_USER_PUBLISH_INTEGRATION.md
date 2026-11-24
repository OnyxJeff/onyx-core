# ONYX CORE v1.0.0 — M2-S5C Safe User Publication Integration

## Scope

Integrates the frozen M2-S4C 17-file runtime payload with M2-S5A-R3's DACL-only hardening and M2-S5B's native no-replace publication contract. The new `onyx_v100_windows_safe_user_publish.py` is an **additive** installer candidate. It does **not** replace or execute the committed unsafe `onyx_v100_windows_user_install.py` or `Set-OnyxV100UserInstallAcl.ps1`.

## Approved inputs

- Local M2 development commit: `00c6ba630a18b054308bb7119b610602790e44be`
- Reviewed original deterministic runtime ZIP (SHA-256 `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`)
- Versioned dashboard source (SHA-256 `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`)
- Hash-pinned M2-S4C, M2-S5A-R3 and M2-S5B Python dependencies
- The new DACL-only helper is separately hash-pinned by the new Python entry point.

## User-scope safety contract

The CLI accepts only `--mode preview` and `--mode native-temp`, never a caller-supplied root or target. Its default mode previews a fixed, versioned LocalAppData target without writing. It offers **no persistent installation CLI mode**.

The internal `install_core` mechanism supports a future user-scope integration, but requires three explicit approvals, native non-elevated Windows Python 3.13, the trusted Windows LocalAppData Known Folder and strict new-target validation. Any real user-scoped call is **not authorized at this milestone**.

Native SQUALL acceptance uses two explicit Temp-only approvals. It creates a fresh marked fixture under the OS Temp directory, assembles the full 17-file installation (16 runtime files plus receipt), applies fresh DACL-only security descriptors, publishes with Win32 `MoveFileExW(flags=0)`, verifies the receipt and DACL, and then checks a separate existing-target collision fixture. The legacy ACL helper is never called.

On failure, incomplete staging is retained. No automatic deletion, retry, replacement, or rollback can modify evidence. This is not a substitute for dedicated persistent-install rollback testing.

## Future release gate

Before an actual `%LOCALAPPDATA%` write: inspect and approve the new User-scope helper branch, complete native acceptance of the new helper's user-path guards, audit all protected production state, request separate explicit authorization, perform a one-shot inactive installation, and validate receipt and ACL without activation.

No credentials, telemetry runtime, Scheduled Tasks, services, registry, firewall, network probes, Pi changes, Git commits, pushes, tags or production changes are permitted by this phase.
