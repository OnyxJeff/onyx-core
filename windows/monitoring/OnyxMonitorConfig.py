#!/usr/bin/env python3
"""ONYX CORE v0.7.0: side-effect-free development configuration validator.

No network access, state creation, task installation, or repair operations.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re


class ConfigError(ValueError):
    """Invalid or unsafe monitor configuration."""


DEV_STATE = r"%LOCALAPPDATA%\OnyxCore-v070-Development\Monitoring"
MONITOR_KEY = r"%USERPROFILE%\.ssh\onyxcore_monitor_ed25519"


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError("Duplicate JSON property: " + key)
        result[key] = value
    return result


def _object(value, required, location):
    if not isinstance(value, dict):
        raise ConfigError(location + " must be an object")
    expected = set(required)
    received = set(value)
    missing = sorted(expected - received)
    extra = sorted(received - expected)
    if missing or extra:
        raise ConfigError("{}: missing={} unexpected={}".format(location, missing, extra))
    return value


def _string(value, field, pattern=None):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ConfigError(field + " must be a non-empty, trimmed string")
    if pattern is not None and not re.fullmatch(pattern, value):
        raise ConfigError(field + " has an invalid format")
    return value


def _number(value, field, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConfigError("{} must be an integer in [{}..{}]".format(field, minimum, maximum))
    return value


def _ipv4(value, field):
    value = _string(value, field)
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError as error:
        raise ConfigError(field + " is not a valid IPv4 address") from error
    if not isinstance(parsed, ipaddress.IPv4Address) or str(parsed) != value:
        raise ConfigError(field + " must be canonical IPv4")
    return value


def validate_config(config):
    """Return validated input as-is. Never expands paths or performs IO."""
    root = _object(config, (
        "schema_version", "profile", "read_only", "repair_action", "windows",
        "pi", "runtime", "timeouts", "monitoring_interval_seconds",
        "startup_grace_seconds", "state_dir"
    ), "root")
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ConfigError("Unsupported schema_version")
    if root["profile"] != "development":
        raise ConfigError("Only isolated development profile is supported in Milestone 1")
    if root["read_only"] is not True or root["repair_action"] != "None":
        raise ConfigError("Read-only mode and repair_action=None are mandatory")
    if root["state_dir"] != DEV_STATE:
        raise ConfigError("Development state_dir must be the approved isolated location")

    win = _object(root["windows"], (
        "adapter_name", "gateway_ip", "receiver_ip", "receiver_port", "upstream_interface"
    ), "windows")
    _string(win["adapter_name"], "windows.adapter_name", r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
    _string(win["upstream_interface"], "windows.upstream_interface", r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
    _ipv4(win["gateway_ip"], "windows.gateway_ip")
    _ipv4(win["receiver_ip"], "windows.receiver_ip")
    if win["gateway_ip"] == win["receiver_ip"]:
        raise ConfigError("Receiver and gateway must differ")
    _number(win["receiver_port"], "windows.receiver_port", 1, 65535)

    pi = _object(root["pi"], ("hostname", "user", "monitor_key_path"), "pi")
    _string(pi["hostname"], "pi.hostname", r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}")
    _string(pi["user"], "pi.user", r"[A-Za-z_][A-Za-z0-9_-]{0,31}")
    if pi["monitor_key_path"] != MONITOR_KEY:
        raise ConfigError("The restricted monitoring identity cannot be changed in Milestone 1")

    runtime = _object(root["runtime"], ("python_executable", "ssh_executable"), "runtime")
    python_path = _string(runtime["python_executable"], "runtime.python_executable")
    ssh_path = _string(runtime["ssh_executable"], "runtime.ssh_executable")
    # Absolute drive paths only; no CLI flags, quotes, paths with control chars, or aliases.
    for label, path in (("python_executable", python_path), ("ssh_executable", ssh_path)):
        if (not re.fullmatch(r"[A-Za-z]:\\[^\r\n\"<>|?*]+\.exe", path)
                or "WindowsApps" in path.split("\\")):
            raise ConfigError("runtime." + label + " must be a direct executable path")

    timeouts = _object(root["timeouts"], (
        "ssh_seconds", "upstream_tcp_ms", "receiver_tcp_ms"
    ), "timeouts")
    _number(timeouts["ssh_seconds"], "timeouts.ssh_seconds", 10, 90)
    _number(timeouts["upstream_tcp_ms"], "timeouts.upstream_tcp_ms", 500, 10000)
    _number(timeouts["receiver_tcp_ms"], "timeouts.receiver_tcp_ms", 100, 10000)
    _number(root["monitoring_interval_seconds"], "monitoring_interval_seconds", 30, 600)
    _number(root["startup_grace_seconds"], "startup_grace_seconds", 0, 3600)
    return root


def load_config(path):
    file_path = Path(path)
    if file_path.stat().st_size > 16384:
        raise ConfigError("Configuration exceeds 16 KiB limit")
    with file_path.open("r", encoding="utf-8-sig") as source:
        data = json.load(source, object_pairs_hook=_reject_duplicates)
    return validate_config(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", required=True, type=Path, metavar="FILE")
    args = parser.parse_args()
    try:
        config = load_config(args.check)
    except (ConfigError, OSError, ValueError, UnicodeError) as error:
        parser.exit(1, "INVALID CONFIG: {}\n".format(error))
    print("PASS: isolated {} config validated (schema_version={}; repair_action=None)".format(
        config["profile"], config["schema_version"]))


if __name__ == "__main__":
    main()
