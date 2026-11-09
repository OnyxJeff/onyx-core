#!/usr/bin/env python3
"""ONYX CORE v0.7.0: offline-only release context contract (NOT a live launcher).

This module defines the candidate SQUALL release policy without authorizing
network probes or enabling a production runtime. Existing development launchers
remain unchanged and reject production contexts until a later audited step.
"""
from __future__ import annotations

import argparse
import copy
import ntpath
from pathlib import Path
import sys

import OnyxMonitorConfig as existing


class ReleasePolicyError(ValueError):
    """A release configuration or requested operation breaks the release policy."""


RELEASE_ROOT = r"D:\github_repos\onyx-core"
RELEASE_BRANCH = "main"
RELEASE_STATE = r"%LOCALAPPDATA%\OnyxCore-v070-Release\Monitoring"
RELEASE_CONFIG_NAME = "monitoring.release.example.json"
OPERATIONS = frozenset(("status", "report", "one-shot-cycle"))


def validate_release_config(config: dict) -> dict:
    """Validate a release profile using the proven v0.7.0 strict field schema.

    Deliberately DOES NOT change/relax OnyxMonitorConfig's development policy.
    No filesystem, process, network or environment access is performed here.
    """
    if type(config) is not dict:
        raise ReleasePolicyError("release configuration must be an object")
    if config.get("profile") != "release":
        raise ReleasePolicyError("release profile is required")
    if config.get("state_dir") != RELEASE_STATE:
        raise ReleasePolicyError("release state path must be the dedicated v0.7.0 location")
    try:
        # The M1 validator is deliberately development-only. Validate every
        # shared field by substituting ONLY the two policy-specific literals.
        # Do not pass this substituted configuration to any live runner.
        checked = copy.deepcopy(config)
        checked["profile"] = "development"
        checked["state_dir"] = existing.DEV_STATE
        existing.validate_config(checked)
    except (existing.ConfigError, TypeError, ValueError) as exc:
        raise ReleasePolicyError("release configuration violates strict shared schema") from exc
    return copy.deepcopy(config)


def load_release_config(path: Path | str) -> dict:
    """Read and validate one bounded JSON file, without triggering probes."""
    file_path = Path(path)
    try:
        if file_path.stat().st_size > 16384:
            raise ReleasePolicyError("release configuration exceeds 16 KiB")
        # Existing loader is strict about duplicate keys and UTF-8 errors, but
        # rejects release profiles. Use its private duplicate-key validator
        # while keeping release-specific validation above.
        import json
        def reject_nonfinite(value: str):
            raise ReleasePolicyError("nonfinite JSON value is prohibited")
        with file_path.open("r", encoding="utf-8-sig") as stream:
            config = json.load(stream, object_pairs_hook=existing._reject_duplicates,
                               parse_constant=reject_nonfinite)
    except (OSError, UnicodeError, ValueError, existing.ConfigError) as exc:
        raise ReleasePolicyError("unreadable or invalid release configuration") from exc
    return validate_release_config(config)


def _canonical_root(root: str) -> bool:
    """Require the exact reviewed Windows path (case-insensitive, no redirects)."""
    if type(root) is not str or not root:
        return False
    if ntpath.normpath(root) != root:
        return False
    return root.casefold() == RELEASE_ROOT.casefold()


def validate_release_intent(
    config: dict,
    *,
    root: str,
    branch: str,
    operation: str,
    explicit_live_read_only: bool = False,
    initialize_new: bool = False,
    schedule_requested: bool = False,
    repair_action: str = "None",
) -> dict:
    """Pure intent check; not a replacement for runtime path/ACL/Git checks.

    Real launchers MUST additionally verify filesystem junctions, Git state,
    current identity, approved executable paths, and existing incident history
    before accepting any live operation. This function never approves a launch.
    """
    validated = validate_release_config(config)
    if not _canonical_root(root) or branch != RELEASE_BRANCH:
        raise ReleasePolicyError("unapproved release repository or branch")
    if type(operation) is not str or operation not in OPERATIONS:
        raise ReleasePolicyError("unapproved release operation")
    if type(explicit_live_read_only) is not bool or type(initialize_new) is not bool:
        raise ReleasePolicyError("authorization flags must be booleans")
    if type(schedule_requested) is not bool or schedule_requested:
        raise ReleasePolicyError("unattended monitoring is not included in v0.7.0")
    if repair_action != "None":
        raise ReleasePolicyError("network and ICS repairs are prohibited")
    if operation == "one-shot-cycle" and not explicit_live_read_only:
        raise ReleasePolicyError("one-shot diagnostic requires explicit live read-only opt-in")
    if operation != "one-shot-cycle" and (explicit_live_read_only or initialize_new):
        raise ReleasePolicyError("stored-data views cannot authorize probes or initialization")
    # A new empty release store will require two explicit approvals, with
    # marker/store and ACL verification enforced by the future live caller.
    return {
        "profile": "release",
        "operation": operation,
        "read_only": validated["read_only"],
        "repair_action": "None",
        "manual_only": True,
        "runtime_enabled": False,
        "requires_runtime_preflight": True,
        "state_dir_literal": RELEASE_STATE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, required=True, metavar="FILE",
                        help="validate one candidate release config; never probe or deploy")
    args = parser.parse_args(argv)
    try:
        load_release_config(args.check)
    except ReleasePolicyError as exc:
        print("RELEASE POLICY REFUSED: " + str(exc), file=sys.stderr)
        return 1
    print("PASS: offline release config contract; runtime NOT enabled; no probes or repairs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
