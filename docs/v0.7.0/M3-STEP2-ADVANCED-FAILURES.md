# ONYX CORE v0.7.0 — Milestone 3 / Step 2
## Advanced offline fault sequences and crash-boundary tests

**Status:** Development-only, offline tests. No implementation changes. Do not commit from installation script.
**Baseline:** Checkpoint H `1da5f17b9e1b77bcb81b8aa630b664b41f38332b`.

### Purpose

Test the complete existing **live bridge → incident adapter → lifecycle reducer → atomic store**
under longer, less tidy input sequences and deliberately injected exceptions. These tests
complement the 33 Step 1 cross-component tests; they do not replace them. All writable
files live under new `tempfile.TemporaryDirectory` instances per test.

### New test module

`tests/monitoring/test_m3_advanced.py`: **31 offline `unittest` cases**, covering:

| Group | Examples | Expected behavior |
| --- | --- | --- |
| Intermittent connectivity | Active→Healthy→Investigate→Healthy→Healthy; correlated failures repeated | Do not recover too early; do not duplicate incident transitions |
| Multiple fault domains | ICS-service observation with Pi DNS failure; Windows adapter down and unreachable Pi | Keep ambiguous diagnosis suspected rather than claiming proven ICS root cause |
| Evidence gaps | Healthy→Unknown→Healthy; Active→Unknown→Investigate; repeated unknown | Display Unknown during incomplete evidence, preserve incident identity and deduplicate events |
| Recovery boundary conditions | 29 vs 30 seconds between healthy samples; 301-second gap | Apply inclusive 30-second minimum and 300-second maximum spacing correctly |
| Lifecycle identity and replay | New outage after recovered and unknown; exact cycle replay while recovery pending | New outage gets new ID, replay cannot count as a second healthy cycle |
| Longer sequence | 60 synthetic cycles with alternating complete and incomplete evidence | Retain generation count, bounded journal, no repair action or raw private decision reasons |
| Initialization crash boundary | Failure before sentinel, then failure after sentinel but before first state | Never silently reinitialize an interrupted store |
| Transaction crash boundary | Write fails before replace; exception reported after successful replace | Old state survives precommit error; postcommit retry is idempotent |
| Locks | Nested writer lock; lock release after failed collector; existing unheld lock file | No concurrent mutation or permanent obstruction after normal release |
| Store corruption | Invalid JSON; extra event fields even with recomputed checksum | Refuse before collection, do not modify suspect record |
| Runner input rejection | Duplicate JSON fields, nonfinite number, oversized response, invalid UTF-8 | Reject malformed evidence without touching persisted history |
| Ineligible input | Backdated cycle, same timestamp with modified content, repair command | Reject without modifying store or starting unauthorized action |
| Data hygiene | Distinct private diagnostic details across many cycles | Never write private reason text into incident state or event journal |

### Safety and scope

- **No tests execute** the PowerShell runner, SSH diagnostic, Windows ICS changes, services, tasks, repair code, or a network probe.
- `execute_one_cycle` is exercised only with a **mocked collector callback**, never its real collector default.
- Faults are introduced by synthetic JSON, monkeypatches, or temporary file mutation—not by unplugging USB or stopping Windows services.
- The actual `%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring` data stays untouched at generation 2, including the initialization marker, lock file, and recovery-observations file.
- The test module is additive; existing source modules must remain unchanged.
- The baseline production repository and backup remain protected; do not push, deploy, schedule, or commit while installing this test package.

### Test gates on SQUALL

1. Verify production main, protected backup SHA-256, dev branch at Checkpoint H, and clean dev status.
2. Hash all four protected live monitoring artifacts before testing; ensure no directory redirects.
3. Validate ZIP SHA-256 and exactly two archive entries, then extract only the additive test and documentation.
4. Run **31 / 31** new advanced tests.
5. Run the full monitoring Python suite: **181 / 181 expected** (150 Checkpoint H + 31 new).
6. Run the two existing offline PowerShell collector/cycle suites.
7. Verify all live incident artifact hashes and exact two-file untracked scope; production unchanged.

### Limitations

The simulated failure combinations and crash boundaries improve confidence in software
behavior but are not field evidence of actual Pi hardware, USB cable, Windows ICS failure,
Windows file-lock scheduling, or adverse power-loss filesystem behavior. Supervised live
fault injection requires a later, separately authorized plan; it is **not** done here.

### Next gate

After SQUALL's offline validation succeeds, commit these **two files only** as
Checkpoint I and continue with Milestone 3 scope/readiness audit.
