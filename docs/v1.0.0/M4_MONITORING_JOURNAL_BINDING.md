# M4 — v1.0.0 scoped incident journal binding

Status: source-only continuation of M4 foundation. No live CLI, installation,
credential, repair, notification or task registration is provided here.

The v100 journal adapter resolves the same fixed path as the read-only view,
requires the directory to have been provisioned, and reuses the existing v080
validated-observation, transactional incident lifecycle and durable receipt
implementation without modifying legacy modules. It requires an explicit
independent authorization callback, a native storage attestor and an exclusive
lock supplied by a trusted parent. Authorization and storage checks run again
at the existing schema and cycle pre-commit gates. Three consecutive unhealthy
checks within five minutes open an incident; two consecutive healthy checks
resolve it. An identical observation reuses its durable operation receipt.

Fixture callbacks are not real authority. Native cross-session locking,
protected path/ACL attestation, bounded worker execution and independently
verified consent are still required. Path checks do not eliminate concurrent
path replacement races. Revocation before commit can roll back an uncommitted
transaction; an in-flight disk commit cannot be instantaneously undone. The
existing v080 live context checks and storage profiles remain unchanged.

The isolated journal must never fall back to a legacy profile, even when the
v080 release selector is set. No directory is created by the adapter. The
monitoring directory must be independently provisioned and attested before
native acceptance. Repair and notification enrollment remain separate.
