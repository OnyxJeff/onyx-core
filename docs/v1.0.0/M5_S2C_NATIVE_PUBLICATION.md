# M5-S2C - inactive side-by-side runtime publication

Status: offline publication implementation; native publication and activation
require separate approval. The accepted M5-S2B archive hashes are immutable.
This is not an upgrade or clean-install orchestrator.

## Publication contract

- Windows: direct LocalAppData child `OnyxCore-v100-Inactive-M5-a8ca64b`.
  Verify the pinned old receipt and all 16 rollback payload files; copy only
  the receipt-bound nonsecret Windows configuration bytes. Stage the 24-file
  candidate, its manifest, the retained config and a prospective publication
  inventory (27 files). Reuse the historical DACL-only helper, verified by
  exact SHA256 (canonical LF or reviewed CRLF); audit before and after a
  same-parent MoveFileExW with flags zero. No replacement or copy fallback.
  The historical DACL permits the current user, SYSTEM and Administrators;
  it is not protection against the same logged-in user or an administrator.
- Pi: direct root-owned `/opt/onyxcore/v1.0.0-m5-a8ca64b`. The 11-file
  candidate, manifest and prospective inventory total 13 files. Existing
  config and state are external and never copied or opened by the publisher.
  The native guard requires ARMv6 Trixie, root, Python 3.13, dedicated account
  and expected old runtime/config/state directory metadata. Use no-follow
  descriptor-relative staging, root:onyxcore-v100 0750 dirs/0640 files,
  fsync, renameat2(RENAME_NOREPLACE), and complete post-publication audit.
  No chmod/chown outside the newly created stage; no unit changes.

Both roles authenticate the exact accepted archive bytes before reading ZIP
metadata, check role/commit/tree/inventory, refuse unexpected destination or
abandoned stages, and require explicit publish opt-in plus the plan digest.
A failed publication preserves evidence rather than deleting unknown paths.
The inventory inside the stage describes intended contents, not completed
activation; only a successful native audit result establishes publication.

## Offline plan

On SQUALL, use Python -I -B with the new publisher, `plan --role windows
--archive <accepted absolute Windows ZIP>` or `plan --role pi-armv6 --archive
<accepted absolute Pi ZIP>`. The Windows plan verifies the existing receipt
and rollback payload and destination absence. The Pi plan is portable: it
only verifies the archive and prospective inventory; it does not prove the
native target is absent or its metadata valid. Neither plan writes files.

## Native publication boundary

Native `publish` is not authorized by offline patch acceptance. The Windows
invocation additionally requires the pinned historical ACL helper. The Pi
publisher must be delivered and verified through a root-trusted bootstrap
before execution, not imported or executed as root directly from an
untrusted writable checkout or transfer directory. Plan hash and archive
hash do not attest the publisher itself. No native execution commands are
part of this acceptance step. Do not activate either code tree yet.

## Handover and rollback contract (implementation pending)

Current Windows tasks are interactive, limited, direct gateway/collector
launches. Preserve their original full XML locally with restricted ACLs;
validate complete action tokens, triggers, principal, settings and all
non-path arguments before proposing changes. Use the new gateway path and
`--v100-monitor-view`; retain -I -B and existing DPAPI helper behavior. The
collector retains its existing parameters and versioned mutex. Never run
old and new collectors concurrently. Do not route scheduled tasks through
the candidate standalone launcher, which correctly refuses existing tasks.
Restore original task definitions and old code paths on rollback.

Pi uses a dedicated service account, strict ProtectSystem, NoNewPrivileges,
external receiver.env and config, and versioned state. Preserve the original
unit and effective ExecStart locally before constructing a reviewed drop-in
that changes only the two runtime-root references. No change to privileges,
network, environment file, or working directory. Stop the old service before
starting the candidate; restore original unit and reload on rollback. Do not
read or export the credential file. Exact unit/drop-in and task handover
scripts, interruption recovery, and native rollback rehearsal are pending.

Prior to handover, qualify persistent SQLite schema compatibility on a safe
consistent backup, not an unsafe raw copy of an active database. Preserve
telemetry history and monitoring journal; do not restore old database bytes
over newer accepted telemetry during code rollback. M4 projection is read-only
and may display Stale until a separately authorized observation is recorded.
No automated repair, monitoring schedule or notifications are enabled.
