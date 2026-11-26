# M4 — Supervised native journal acceptance

This is an explicitly requested, one-cycle same-user recording run, not a
release unattended authorization issuer. The development worktree is still
user-writable. The operator checks the exact source identities and system
binary signatures before starting. The process checks its token SID and a
short monotonic authorization window before each journal transaction gate.

The existing cross-session protected v080 global mutex is reused deliberately
so a legacy protected writer and this supervised recorder cannot overlap.
The mutex does not change either legacy storage profile. The lock covers
provisioning, observation, transaction, and projection. There is no scheduler.

The native storage helper checks the existing protected v100 credential
parent without opening the credential. With explicit initialization, it
creates a fresh sibling staging directory under that parent with a protected
user/SYSTEM/Administrators DACL and publishes it without replacing any existing
Monitoring directory. It audits directory and SQLite-file ownership and access
rules. The Python path guard rejects redirection and hardlinked SQLite files.
Existing files and ACLs are not rewritten. A failure may leave a stage, an
empty directory or an already committed journal transaction for inspection.

This same-user threat model cannot protect against the supervising user,
administrators, or malicious code already running under that account. Path
and ACL checks are not atomic with SQLite open/commit. The authorization
window is not a hard disk-flush deadline. No durable consent, notification,
automatic repair, task registration, runtime replacement or legacy writes are
performed. Native acceptance of DACL behavior and the mutex is still required.
