# ONYX CORE v0.8.0 M2 — Foreground continuous connectivity monitor

**Status:** Development candidate; not scheduled or deployed. Uses the M1 one-shot Windows/Pi diagnostic, demonstrated healthy on SQUALL at `2026-11-12T01:23:26Z` (one observation, not ongoing availability).

## Behavior

- Each cycle calls M1 `OnyxLiveConnectivity.run_once` to gather a real, bounded Windows USB/ICS result and a Pi result through the existing restricted SSH command.
- One cycle runs at a time. Cycles are paced from the **start** of the previous cycle with an operator-selected interval of **90–3600 seconds** (default **120**). A slow cycle never triggers catch-up or parallel probes.
- `--count N` runs 1–20 cycles, then exits; `--continuous` runs only in the foreground until **Ctrl+C**. Both require explicit `--live-read-only`. No background task, Windows service, startup registration or autostart is created.
- A Windows **Local session** named mutex refuses a second M2 runner in the same logon session. It does not coordinate across multiple interactive Windows sessions or prevent someone manually starting M1 at the same time. A production-grade cross-session singleton is a separate future requirement.
- Each result is printed immediately in a human-readable format, or as one sanitized JSON object per line with `--jsonl`. `Healthy`, `Degraded`, and `Unknown` are retained separately; absent evidence is **not** proof of a healthy link or ICS fault.
- **No incident history writes, dashboard change, notification, repair, Scheduled Task modification, production deployment or Pi installation.** These belong to later independently tested milestones.
- Existing v0.7 release source and protected incident stores remain untouched. The only side effects in live mode are the real diagnostic's read-only Windows/SSH/network probes and terminal output.

## Offline first (safe to run without authorizing network probes)

```powershell
& 'C:\Python313\python.exe' -B `
  'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxContinuousMonitor.py' `
  --check-config
```

## Future explicit live acceptance (not included in the patch-application step)

Run from a non-elevated Windows PowerShell console on SQUALL, **only after opting in to the real repeated probes**:

```powershell
& 'C:\Python313\python.exe' -B `
  'D:\github_repos\onyx-core-v080\windows\monitoring\v080\OnyxContinuousMonitor.py' `
  --live-read-only --count 2 --interval-seconds 120
```

Expected: two real report lines, separated according to the 120-second start-to-start cadence, with separate Windows and Pi classifications. A `Degraded` or `Unknown` status represents data, not necessarily a failed program. For an explicit indefinite foreground session use `--live-read-only --continuous --interval-seconds 120` and stop with Ctrl+C. Never configure this CLI as an automatic task until a future installer and lifecycle are tested.

## Developer validation

```powershell
& 'C:\Python313\python.exe' -B -m unittest discover `
  -s 'D:\github_repos\onyx-core-v080\tests\monitoring\v080' `
  -p 'test_continuous_monitor.py' -v
```

Offline tests simulate time and subprocess results; they perform no live checks. M1's 14 tests should also continue to pass. This is an **additive, unstaged** development patch only.
