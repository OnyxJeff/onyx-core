# ONYX CORE v0.6.0 — Recovery Policy

## Purpose

Define safe recovery decisions for the Windows-to-Raspberry Pi
USB networking connection.

Development is isolated from production v0.5.1.

## Diagnostic Sources

- Windows: Test-OnyxUsbIcsReadiness.ps1
- Raspberry Pi: Test-OnyxUsbForwarding.py
- Future: independent Windows upstream connectivity check

## Decision Classes

### Healthy

Both diagnostics confirm expected connectivity.

Action: None.

### WaitAndRetry

The USB interface is missing, initializing, or temporarily
unavailable.

Action: Wait for the next diagnostic cycle.

### Investigate

A failure exists but available evidence does not establish
that Windows ICS is responsible.

Examples:
- Receiver unavailable
- Incorrect USB route
- DNS failure
- Windows upstream internet unavailable
- Missing or conflicting diagnostic evidence

Action: Log the failure. Do not restart ICS.

### PossibleIcsFailure

Windows upstream connectivity is verified.
The USB interface and gateway are operational.
The Pi can reach Windows but cannot reach external TCP services.

Action: Continue diagnostics. Do not automatically restart ICS.

## Proposed Stability Safeguards

- Never restart a verified healthy connection.
- Require at least three consistent failed observations.
- Separate observations by at least 30 seconds.
- Ignore stale or incomplete evidence.
- Allow a startup grace period before evaluating failures.
- Use a cooldown and bounded retry count for future repairs.
- Do not infer ICS failure from a single external endpoint.
- Do not treat an unreachable Pi as proof of ICS failure.
- Keep all recovery actions disabled during initial development.

## Testing Requirements

- Healthy Windows and Pi
- Missing USB adapter
- Incorrect USB route
- Receiver unavailable
- Windows upstream outage
- Pi DNS-only failure
- Suspected ICS forwarding failure
- Missing or stale diagnostic reports
- Intermittent failure followed by recovery
- Repeated failures and retry limits

## Release Requirement

No automatic repair is permitted until detection, decision
logic, and recovery safeguards have independent test coverage.

Production configuration remains unchanged during development.
