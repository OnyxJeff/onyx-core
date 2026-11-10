#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M1: OFFLINE-ONLY unattended-monitoring policy.

No scheduler, live probes, enrollment writes, SSH, network, or repairs.
A matching enrollment is only a DATA-CONTRACT result; it never grants the
ability to execute diagnostics. Future runtime checks are deliberately absent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys

SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 16384
MAX_ENROLLMENT_BYTES = 8192
SCOPE = "periodic_read_only_usb_ics"
PROFILE = "unattended-v080"
STATE_DIR = r"%LOCALAPPDATA%\OnyxCore-v080\Monitoring"
ENROLLMENT_PATH = r"%LOCALAPPDATA%\OnyxCore-v080\Authorization\enrollment.json"
TASK_NAME = "ONYX CORE - USB Monitor"
MONITOR_KEY = r"%USERPROFILE%\.ssh\onyxcore_monitor_ed25519"
PYTHON_PATH = r"C:\Python313\python.exe"
SSH_PATH = r"C:\Windows\System32\OpenSSH\ssh.exe"
RELEASE_STATE_DIR = r"%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring"
DEVELOPMENT_STATE_DIR = r"%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT = re.compile(r"^[A-Za-z0-9_.-]{1,63}\\[A-Za-z0-9_.-]{1,63}$")


class PolicyError(ValueError):
    """Unsupported, malformed, or unapproved monitoring policy data."""


def _fields(value: object, expected: tuple[str, ...], label: str) -> dict:
    if type(value) is not dict or set(value) != set(expected):
        raise PolicyError(label + ": missing or unexpected fields")
    return value


def _true(value: object, label: str) -> None:
    if value is not True:
        raise PolicyError(label + " must be the boolean true")


def _false(value: object, label: str) -> None:
    if value is not False:
        raise PolicyError(label + " must be the boolean false")


def _integer(value: object, lo: int, hi: int, label: str) -> None:
    if type(value) is not int or not lo <= value <= hi:
        raise PolicyError(f"{label} must be an integer from {lo} to {hi}")


def _literal(value: object, expected: str, label: str) -> None:
    if type(value) is not str or value != expected:
        raise PolicyError(label + " does not match the reviewed literal")


def _ipv4(value: object, label: str) -> None:
    if type(value) is not str:
        raise PolicyError(label + " is not a canonical IPv4 address")
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise PolicyError(label + " is not an IPv4 address") from exc
    if not isinstance(ip, ipaddress.IPv4Address) or str(ip) != value:
        raise PolicyError(label + " is not a canonical IPv4 address")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise PolicyError("duplicate JSON property")
        obj[key] = value
    return obj


def _reject_nonfinite(value: str):
    raise PolicyError("nonfinite JSON value is forbidden: " + value)


def _parse_json(raw: bytes, *, limit: int) -> dict:
    if type(raw) is not bytes or not raw or len(raw) > limit:
        raise PolicyError("missing or oversized policy document")
    try:
        obj = json.loads(raw.decode("utf-8-sig", "strict"),
                         object_pairs_hook=_reject_duplicates,
                         parse_constant=_reject_nonfinite)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PolicyError("invalid policy JSON") from exc
    if type(obj) is not dict:
        raise PolicyError("policy document must be a JSON object")
    return obj


def _utc(value: object) -> datetime:
    if type(value) is not str or not (20 <= len(value) <= 40):
        raise PolicyError("approved_at_utc must be an offset-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PolicyError("approved_at_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyError("approved_at_utc must have a timezone")
    return parsed.astimezone(timezone.utc)


def validate_config(data: dict) -> dict:
    """Pure strict validation for a SQUALL-specific FUTURE unattended profile."""
    conf = _fields(data, (
        "schema_version", "profile", "enabled", "read_only", "repair_action",
        "windows", "pi", "runtime", "schedule", "alerts", "authorization",
        "state_dir",
    ), "config")
    if type(conf["schema_version"]) is not int or conf["schema_version"] != SCHEMA_VERSION:
        raise PolicyError("unsupported configuration schema")
    _literal(conf["profile"], PROFILE, "profile")
    if type(conf["enabled"]) is not bool:
        raise PolicyError("enabled must be boolean")
    _true(conf["read_only"], "read_only")
    _literal(conf["repair_action"], "None", "repair_action")
    _literal(conf["state_dir"], STATE_DIR, "state_dir")
    if conf["state_dir"] in (RELEASE_STATE_DIR, DEVELOPMENT_STATE_DIR):
        raise PolicyError("existing incident state must remain isolated")

    win = _fields(conf["windows"], (
        "adapter_name", "gateway_ip", "receiver_ip", "receiver_port",
        "upstream_interface",
    ), "windows")
    _literal(win["adapter_name"], "Ethernet 3", "windows.adapter_name")
    _literal(win["gateway_ip"], "192.168.137.1", "windows.gateway_ip")
    _literal(win["receiver_ip"], "192.168.137.167", "windows.receiver_ip")
    _ipv4(win["gateway_ip"], "windows.gateway_ip")
    _ipv4(win["receiver_ip"], "windows.receiver_ip")
    _integer(win["receiver_port"], 8765, 8765, "windows.receiver_port")
    _literal(win["upstream_interface"], "Ethernet", "windows.upstream_interface")

    pi = _fields(conf["pi"], ("hostname", "user", "monitor_key_path"), "pi")
    _literal(pi["hostname"], "svr-onyxcore.local", "pi.hostname")
    _literal(pi["user"], "onyxpi", "pi.user")
    _literal(pi["monitor_key_path"], MONITOR_KEY, "pi.monitor_key_path")

    runt = _fields(conf["runtime"], ("python_executable", "ssh_executable"), "runtime")
    _literal(runt["python_executable"], PYTHON_PATH, "runtime.python_executable")
    _literal(runt["ssh_executable"], SSH_PATH, "runtime.ssh_executable")

    sched = _fields(conf["schedule"], (
        "interval_seconds", "startup_grace_seconds", "max_cycle_seconds",
        "overlap_policy", "missed_cycle_policy", "session_policy",
    ), "schedule")
    _integer(sched["interval_seconds"], 60, 120, "schedule.interval_seconds")
    _integer(sched["startup_grace_seconds"], 0, 3600, "schedule.startup_grace_seconds")
    _integer(sched["max_cycle_seconds"], 45, 120, "schedule.max_cycle_seconds")
    _literal(sched["overlap_policy"], "Skip", "schedule.overlap_policy")
    _literal(sched["missed_cycle_policy"], "Skip", "schedule.missed_cycle_policy")
    _literal(sched["session_policy"], "LoggedOnUserOnly", "schedule.session_policy")

    alerts = _fields(conf["alerts"], (
        "incomplete_cycles_before_warning", "notify_on_confirmed_incident",
        "notify_on_recovery", "repeat_identical_alerts", "channel",
    ), "alerts")
    _integer(alerts["incomplete_cycles_before_warning"], 2, 5,
             "alerts.incomplete_cycles_before_warning")
    _true(alerts["notify_on_confirmed_incident"], "alerts.notify_on_confirmed_incident")
    _true(alerts["notify_on_recovery"], "alerts.notify_on_recovery")
    _false(alerts["repeat_identical_alerts"], "alerts.repeat_identical_alerts")
    _literal(alerts["channel"], "LocalOnly", "alerts.channel")

    auth = _fields(conf["authorization"], (
        "scope", "enrollment_path", "task_name", "require_account_match",
        "require_source_commit_match", "require_config_digest_match",
    ), "authorization")
    _literal(auth["scope"], SCOPE, "authorization.scope")
    _literal(auth["enrollment_path"], ENROLLMENT_PATH, "authorization.enrollment_path")
    _literal(auth["task_name"], TASK_NAME, "authorization.task_name")
    for key in ("require_account_match", "require_source_commit_match", "require_config_digest_match"):
        _true(auth[key], "authorization." + key)
    return conf


def parse_config(raw: bytes) -> dict:
    return validate_config(_parse_json(raw, limit=MAX_CONFIG_BYTES))


def parse_enrollment(raw: bytes) -> dict:
    grant = _fields(_parse_json(raw, limit=MAX_ENROLLMENT_BYTES), (
        "schema_version", "approval_scope", "approved_account", "source_commit_sha",
        "config_sha256", "approved_at_utc", "operator_approved", "read_only",
        "repair_action",
    ), "enrollment")
    if type(grant["schema_version"]) is not int or grant["schema_version"] != SCHEMA_VERSION:
        raise PolicyError("unsupported enrollment schema")
    _literal(grant["approval_scope"], SCOPE, "enrollment.approval_scope")
    if type(grant["approved_account"]) is not str or not ACCOUNT.fullmatch(grant["approved_account"]):
        raise PolicyError("enrollment.approved_account is invalid")
    if type(grant["source_commit_sha"]) is not str or not SHA40.fullmatch(grant["source_commit_sha"]):
        raise PolicyError("enrollment.source_commit_sha is invalid")
    if type(grant["config_sha256"]) is not str or not SHA64.fullmatch(grant["config_sha256"]):
        raise PolicyError("enrollment.config_sha256 is invalid")
    _utc(grant["approved_at_utc"])
    _true(grant["operator_approved"], "enrollment.operator_approved")
    _true(grant["read_only"], "enrollment.read_only")
    _literal(grant["repair_action"], "None", "enrollment.repair_action")
    return grant


def assess_offline_enrollment(config_bytes: bytes, enrollment_bytes: bytes | None,
                              *, verified_account: str, verified_source_commit: str) -> dict:
    """Pure DATA-only eligibility check; cannot authorize execution in M1.

    'verified_*' are supplied by the caller for offline tests. A future runtime
    MUST independently derive them from a trusted Windows/Git preflight.
    """
    conf = parse_config(config_bytes)
    if not conf["enabled"]:
        raise PolicyError("unattended monitoring is disabled")
    if enrollment_bytes is None:
        raise PolicyError("separate operator enrollment is missing")
    grant = parse_enrollment(enrollment_bytes)
    if type(verified_account) is not str or not ACCOUNT.fullmatch(verified_account):
        raise PolicyError("operator account is not verified")
    if type(verified_source_commit) is not str or not SHA40.fullmatch(verified_source_commit):
        raise PolicyError("source commit is not verified")
    if grant["approved_account"].casefold() != verified_account.casefold():
        raise PolicyError("approved Windows account does not match")
    if grant["source_commit_sha"] != verified_source_commit:
        raise PolicyError("approved source commit does not match")
    if grant["config_sha256"] != hashlib.sha256(config_bytes).hexdigest():
        raise PolicyError("approved config digest does not match")
    return {
        "source": "OnyxV080M1OfflineContract",
        "enrollment_data_matches": True,
        "runtime_enabled": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "repair_action": "None",
        "assessment": "DATA ONLY: runtime preflight and deployment authorization are not implemented",
    }


def check_example_file(path: Path) -> dict:
    """Read-only CLI for a checked-in example. No enrollment access allowed."""
    raw = path.read_bytes()
    conf = parse_config(raw)
    if conf["enabled"]:
        raise PolicyError("M1 checked-in example MUST be disabled")
    return {"source": "OnyxV080M1ExampleCheck", "config_valid": True,
            "enabled": False, "runtime_enabled": False, "live_probe_authorized": False,
            "task_creation_authorized": False, "repair_action": "None"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-example", type=Path, required=True, metavar="PATH",
                        help="read-only validation of a disabled example configuration")
    args = parser.parse_args(argv)
    try:
        result = check_example_file(args.check_example)
    except (PolicyError, OSError) as exc:
        print("M1 OFFLINE POLICY REFUSED: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
