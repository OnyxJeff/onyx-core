# ONYX CORE v0.7.0 — Milestone 1, Step 3

Scope: development configuration contract **only**. Contains three implementation/test files plus this documentation file (four files total):

- `windows/monitoring/OnyxMonitorConfig.py` — offline-only configuration parsing and fail-closed validation.
- `windows/monitoring/monitoring.development.example.json` — reviewed reference settings for SQUALL.
- `tests/monitoring/test_config.py` — offline configuration regressions.

No script runs live network probes, changes networking, installs a task, accesses private keys, writes runtime monitoring state, or invokes repairs. The original v0.6.0 diagnostic collector and the receiver/gateway/overlays remain unchanged.

Configuration includes the *reference* Pi IP and Windows adapter settings confirmed by the read-only USB diagnostic. `%USERPROFILE%` and `%LOCALAPPDATA%` remain literal tokens at this stage (no automatic expansion or file creation). Executable paths are validated syntactically; runtime availability will be checked separately in subsequent milestones.

## Offline commands, from the development worktree

```powershell
& 'C:\Python313\python.exe' windows\monitoring\OnyxMonitorConfig.py --check windows\monitoring\monitoring.development.example.json
if ($LASTEXITCODE -ne 0) { throw 'Config validation failed.' }
& 'C:\Python313\python.exe' -m unittest discover -s tests\monitoring -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Config tests failed.' }
```

These files are a foundation for the later collector refactor; they are not a functional unattended monitor. No commit, push, scheduling, installation, or production deployment is included.
