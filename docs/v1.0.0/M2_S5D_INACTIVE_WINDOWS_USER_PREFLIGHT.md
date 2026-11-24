# ONYX CORE v1.0.0 - M2-S5D: Persistent Windows Installation Preflight

**Status:** Development only; read-only on the real user profile. Not an installation authorization.

## Objective

Bind the accepted S5C safe publisher to a single future user-profile installation target without exposing a public write entry point. Verify the exact 17-file integrated runtime, source provenance, configuration, target collision protections, and the previously tested DACL-only helper.

## Accepted inputs

- M2 development commit `00c6ba630a18b054308bb7119b610602790e44be` (source identity).
- S5C safe publisher and its pinned S4C, R3, S5B and DACL-only helper dependencies.
- M2-S1 runtime bundle SHA-256 `b4e3c350e47d087bd06c4249aa163d96abe07b792109fc4e9b1032705e2c263d`.
- Reviewed versioned dashboard SHA-256 `16cec6731032a444bf944e165b22fdc179cca6ae6d48252520b77a51be6d8a57`.

## Proposed target

`%LOCALAPPDATA%\OnyxCore-v100-Inactive-Stable100`, resolved from the native Windows Known Folder API. The target must not exist. A redirected LocalAppData path, altered root, reparse point, or existing target fails closed. No alternate target CLI argument is accepted.

## Preflight result

The JSON plan includes the target, machine-specific receiver/source/port settings, exact installed-file SHA-256 inventory (16 payload files and one future receipt), source hashes, and a deterministic `plan_sha256` calculated from the plan without its own digest. The digest is **review evidence**, not an installation approval token or authorization credential.

The public CLI implements only `--mode preview`; there are no `install-user`, `--target`, or approval switches. It creates no profile directory, changes no DACL, reads no DPAPI credential, and starts no runtime process, service, or Scheduled Task. The S5C native Temp-only acceptance remains the authoritative test for DACL/no-overwrite publication until separately approved native user-scope validation.

## Required next gate (not in M2-S5D)

After preflight acceptance, review the exact plan and authorize a separate one-shot, inactive user-scope writer. That writer must revalidate the plan, trusted known-folder target, complete DACLs, same-volume no-replace publication, receipt, and no runtime activation immediately before execution. Only the exact planned directory may be written. Partial failure must retain evidence; no unsafe automatic cleanup, retry, or overwrite. Credential enrollment, service registration, collector/gateway startup, commits, pushes, and Pi changes require their own authorization.
