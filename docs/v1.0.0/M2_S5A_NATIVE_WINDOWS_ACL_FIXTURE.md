# ONYX CORE v1.0.0 — M2-S5A-R2: Native Windows ACL Fixture Acceptance

Status: **development-only, native SQUALL R2 acceptance pending; ACL proof passed in a separate fixture**. Base: local M2 commit `00c6ba630a18b054308bb7119b610602790e44be`.

## Goal

Demonstrate that the **committed M2-S4C full 17-file integrated Windows runtime** (16 payload files plus the receipt) can be assembled, DACL-hardened with the tested Windows `Set-Acl` method, published and audited inside a **new OS Temp test fixture**, without installing ONYX CORE in the user profile or affecting the existing production runtime.

## Inputs and preserved contracts

- Original M2-S1 runtime ZIP SHA-256: `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- Versioned dashboard SHA-256: `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`.
- Reviewed M2-S4C integrated user installer SHA-256: `a3d96181da4e0907d8ca50eb1e9a6d7e4e70a6f7b0adcbe381d7e674d063b83f`.
- Reviewed M2-S2C ACL helper SHA-256: `7e8b1f0b70a99684cfeaab3ad59d369dc1df6b50e6c4e7446eae1789bee5d5d5`.
- Existing reviewed source files are **never edited**. M2-S5A introduces two new verification tools, tests and this document.

## Scope

The Python CLI defaults to `preview-user`, which uses the actual Windows Known Folder path and **creates no files**. `native-temp-acl` additionally requires `--approve-temp-acl-test` and `--approve-inactive-fixture`. It requires non-elevated Windows Python 3.13, creates a *new* `OnyxV100-S5A-ACL-<32 hex>` direct child of the OS Temp directory, and installs the 17 files only beneath that fixture. The fixture has an exact marker file and is retained for human review.

The native-only PowerShell ACL helper rejects arbitrary paths, symlink/reparse-point paths, elevated users, nonexistent/altered markers, unexpected fixture children, and all paths outside the exact OS Temp fixture. The legacy S2C `icacls /inheritance:r`-then-`/grant:r` sequence is **known unsafe** and must never be invoked for this fixture. The replacement builds each complete DACL in memory, writes it using one `Set-Acl` call per node (deepest first), and verifies exactly three explicit Full Control ACEs for current user, SYSTEM, and Administrators. The original committed helper is preserved *only* as pinned evidence of the defect; it still must be replaced before permanent installation. It audits every file and directory to require protected DACLs, no unexpected principals or deny ACEs, and current-user full control. After installation, it audits the published tree a second time without modifying the DACL.

The Python wrapper reuses S4C's SHA-pinned runtime derivation and S2C's existing inactive install/receipt verifier. It never reads the versioned DPAPI token, uses legacy credentials, probes the Pi, starts telemetry processes, touches Scheduled Tasks, or modifies production.

## SQUALL acceptance sequence

1. Verify clean M2 HEAD `00c6ba6`, production `main` `06ec8158`, unchanged original collector backup, pinned M2-S1 bundle, exact 36-file committed review inventory, and four absent new development targets.
2. Stage four pinned S5A files and the six pinned existing M2 dependencies, parse staged Python sources and native PowerShell 5.1 ACL helper.
3. Run all offline tests on SQUALL; there must be no fixture mutation from tests. Run a native read-only user-profile preview.
4. **Before adding development files**, run exactly one `native-temp-acl` fixture with both Temp-only approval flags. Verify the 17-file receipt, real DACL, and no production or user-profile installation.
5. Add exactly four untracked development files; repeat the offline tests and verify unchanged Git heads and clean tracked index.

## Limits / remaining issues

- This proves the ACL algorithm in **OS Temp**, not actual permanent LocalAppData publication. The S2C helper's LocalAppData-specific path guard is **not** exercised by this fixture. Real profile install and permissions remain a separate authorization gate.
- The S2C user's `Path.rename(target)` publication includes a pre-check for an absent target, but a check/rename race is still possible on Windows. **A fail-closed native no-overwrite publication operation must be developed and validated before any permanent profile install.** No production install is approved by M2-S5A.
- On fixture failure, do **not** delete or retry automatically; inspect the retained temporary directory and logs. No installation receipts should be interpreted as live runtime readiness.
- Never commit, push, merge, tag, enroll credentials, register startup tasks, modify production monitoring histories, or perform live telemetry activation without separate authorization.

## SQUALL ACL defect and R2 evidence

The initial S5A fixture retained `OnyxV100-S5A-ACL-42af9e7f62c54086b6447ea6ceea4279` after the legacy ACL helper removed inherited user access. A subsequent read-only inspection identified a protected staging DACL with no Full Control for the current user and an inaccessible `config` directory. **Do not delete or repair that fixture automatically.**

The independent single-`Set-Acl` proof successfully created a second, unrelated Temp fixture and verified explicit access for user/SYSTEM/Administrators, no OWNER RIGHTS or inherited ACEs, and continued read access. The S5A-R2 integrated fixture repeats that approved algorithm on the 17-file runtime before publishing. Full ARMv6 testing, persistent LocalAppData installation, and modification of the known-unsafe tracked M2-S2C helper remain separate work and authorization.


## R3: DACL-only native operation (2026-11-22)

The first R2 native 17-file fixture on SQUALL stopped with `SeSecurityPrivilege`
while writing a staging-directory ACL. R2 round-tripped an existing `Get-Acl`
security descriptor through `Set-Acl`. That path can attempt to update security
audit information on a complex tree. It is not appropriate for a non-elevated
DACL-only installer.

R3 creates a **new** `DirectorySecurity` or `FileSecurity` object for each
fixture node, adds only the three approved full-control ACEs, protects the DACL,
and uses the matching `System.IO.Directory.SetAccessControl` or
`System.IO.File.SetAccessControl` method. Existing SACL/owner/group metadata is
not loaded into or written through the replacement object. Each node remains
subject to the same post-write ACE count, identity, inheritance, and readback
audit; failures stop with native diagnostics and retain the fixture.

R3 is **not** approved for real LocalAppData installation and does not change
the frozen M2-S2C helper. Do not rerun or repair prior failed Temp fixtures.
Native SQUALL acceptance is required before trusting this update.
