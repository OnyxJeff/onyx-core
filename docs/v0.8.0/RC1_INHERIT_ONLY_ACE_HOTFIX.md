# ONYX CORE v0.8.0 RC1: Inherit-only ACE classifier correction

**Scope:** native protected-source ACL admission only. No monitoring changes,
additional permissions, enrollment, task modifications, or production deployment.

## Evidence

On SQUALL, the first native rejection came from `C:\Program Files`:

- Owner SID: `S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464`.
- ACE SID: `S-1-3-0` (`CREATOR OWNER`).
- ACE type: allow (`0`); access mask `0x10000000` (`GENERIC_ALL`).
- Flags `0x0B`: object inherit, container inherit, **inherit only**.

Microsoft documents that an inherit-only ACE does **not** apply to the object
on which it is stored. The existing scanner omitted `AceFlags` from its native
ACL representation and therefore incorrectly treated the inherited-only ACE
as current-object write access.

## Correction

- Native `_handle_acl` now returns `(type, SID, mask, flags)`.
- Effective-write classifier ignores access masks on a well-formed ACE marked
  `INHERIT_ONLY`, only for the current object.
- Effective inherited allow ACEs **remain** checked and nonprivileged writes
  remain blocked; child paths are separately opened and checked.
- Unrecognized ACE kinds, invalid flags, unsupported structures, reparse
  points, nonprivileged owners and malformed ACL records still fail closed.
- Legacy three-field injected rules remain interpreted as effective, avoiding
  accidental bypass in older synthetic test fixtures.

## Acceptance

1. Audit source/working tree; install this three-file development patch only.
2. Run the targeted offline tests and the existing trust/operator tests.
3. Run `Probe-OnyxV080RC1-InheritOnly-ReadOnly.py` on SQUALL **without**
   installing code. It verifies the old installed candidate/approval/checker
   digests before checking the full approved source inventory using the patched
   reader and classifier.
4. If native probe passes, run the full offline regression and get a separate
   local-commit approval.
5. Produce new pinned release-candidate artifacts and a separate protected
   replacement/rollback plan. Do not edit the existing installed files or the
   Windows `Program Files` ACLs in place.

**Release status: HOLD.** The user-scoped credential and launch path, incident
recovery, optional alerts, and rollback require separately authorized live
acceptance.
