# RC2-M5: Interrupted-state recovery contract

RC2 adds **explicit** recovery phases; ordinary activation and rollback phases remain
fail-closed. These operations are not automatic, not scheduled, and not enabled by reboot.
Run only from an independently validated state with a fresh operator authorization.
Do **not** run development controllers against the RC1 installation or production.

## Pi ARMv6

- `resume-activate`: only `candidate-unit-registered`, verifies frozen receipt and unit,
  original inactive/disabled, unchanged runtime guard/dispatcher inventory, no
  unexpected persistent startup, and exclusive USB receiver binding. Starts the
  exact candidate service only if inactive, then journals `candidate-running-rehearsal`.
- `reconcile-rollback`: for interrupted rollback phases, requires original unit match
  the escrow copy, original active/enabled, candidate inactive/disabled, exact USB
  socket owned by legacy systemd MainPID, and absent v0.9.0 legacy-exclusion guards.
  The only change is the existing atomic journal write to `rolled-back`.
- `rollback` remains responsible for **stopping** candidate and **restoring** original.
  `reconcile-rollback` deliberately refuses partially restored services.

## Windows 11 PowerShell 5.1

- `ResumeCandidate`: only `candidate-registration-created`, requires explicit Pi
  candidate confirmation, original Scheduled Tasks disabled and legacy processes
  absent, correct candidate task principal/action/no triggers, no unexpected port
  owner. Starts **only missing** candidate tasks and journals after unique collector,
  launcher and gateway runtime plus loopback ownership are verified.
- `ResumeLegacy`: only `candidate-quiesced`, requires explicit Pi legacy
  confirmation, prevents any candidate activation, enables original tasks only
  if disabled, starts missing original tasks only if their runtime is absent,
  and journals after unique original processes plus loopback ownership verify.
- `ReconcileLegacy`: only `candidate-quiesced` or `quiescing`, requires separate Pi
  legacy confirmation, original tasks and all three original processes running,
  loopback port owned by original gateway, candidate processes absent, any retained
  candidate task definitions validated and disabled. Only writes `rolled-back`.
- `StopCandidate` and `RestoreLegacy` remain the real rollback actions. Reconcile
  never starts or stops production. If preconditions fail, inspect; do not edit JSON.

## Release gate

These synthetic tests do **not** replace an explicit RC2 native two-host replay and
reboot/logon validation. No source commits, merges, deployment, release, or reboot
are authorized by this development patch. RC1 recovery evidence remains immutable.
