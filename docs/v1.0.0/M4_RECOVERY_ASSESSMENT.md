# M4 — Manual recovery assessment

The reviewed legacy Repair-ICS.ps1 (SHA256
`cf00f0ea5afe4a3326ed87141bc43fa953512a89dd2f65502986c822c5aa6db7`)
waits for an adapter and preferred gateway address, then unconditionally
restarts SharedAccess if running or starts it otherwise. It checks service
status, not end-to-end forwarding. Preserve the legacy file unchanged.

The v100 manual assessment composes the existing read-only Windows reader,
restricted Pi diagnostic and native Windows Job Object worker containment.
Explicit `--observe-once` is mandatory. It produces a sanitized, existing
journal-compatible observation plus an operator recommendation. It does not
invoke the old development CLI, alter its guards, or create a task or journal.
Healthy evidence returns NoRepairNeeded. USB/route failures, unavailable
observations, receiver failures, and upstream failures are investigated rather
than treated as proof that ICS needs restarting. A confirmed stopped service
with a ready adapter, preferred gateway and expected route may warrant an
operator considering starting ICS. No repair is performed by this command.

Manual source acceptance only: run from the reviewed v100 development tree
with source integrity checked by the invoking operator. The inherited worker
containment requires native Windows acceptance. It does not establish
low-integrity isolation, unattended consent, protected source/ACL admission,
exclusive cross-session journal ownership, or automatic repair authority.
These remain prerequisites for any persistent monitor/writer or privileged
repair integration. This is not a deployable runtime bundle update.

Native acceptance correction: Windows component servicing may create multiple
hardlinks for the two exact OS executable paths (System32 OpenSSH ssh.exe and
WindowsPowerShell v1.0 powershell.exe). Only these paths admit multiple links;
regular-file and non-reparse checks remain mandatory for all paths and ancestors.
The manual run procedure verifies valid Authenticode signatures at both paths
before invoking the assessment. This is not an in-process signature or ACL
attestation and does not authorize unattended execution. Keys and scripts still
require a single link. Refusals now identify the validation stage and exception
type without including diagnostic payloads or credentials.
