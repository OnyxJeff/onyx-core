#!/usr/bin/env python3
"""ONYX CORE v0.8.0 M2B: OFFLINE simulated authorization boundary.

A DATA-ONLY policy exercise. All identity, Git, source, ACL, consent and
revocation facts are caller-provided simulated assertions, NEVER authenticated
Windows observations. There is no live execution path or enrollment writer.
The command-line entry point only emits a fixed inert capability statement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

# -I omits script-relative imports on supported Python versions. Limit this
# dependency to the fixed sibling policy module; no user-supplied import path.
_FIXED_MODULE_DIR = str(Path(__file__).resolve().parent)
if _FIXED_MODULE_DIR not in sys.path:
    sys.path.insert(0, _FIXED_MODULE_DIR)
import OnyxUnattendedPolicy as m1

SCHEMA = 1
MAX_FACTS_BYTES = 16384
MAX_REVOCATION_BYTES = 4096
FIXTURE_PREFIX = "onyx-v080-m2b-"
SIM_ROOT = Path(tempfile.gettempdir()).resolve()
SID = re.compile(r"^S-1-5-21-(?:[0-9]{1,10}-){3}[0-9]{1,10}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
TRUSTED_SYSTEM_SIDS = frozenset(("S-1-5-18", "S-1-5-32-544"))
ROLES = frozenset(("worktree", "config", "enrollment", "revocation", "state", "python", "ssh"))
FILES = frozenset(("config.json", "enrollment.json", "revocation.json", "facts.json"))


class OfflineAuthorizationError(ValueError):
    """The simulated approval cannot pass a strictly defined data gate."""


def _must(condition: bool, message: str) -> None:
    if not condition:
        raise OfflineAuthorizationError(message)


def _fields(obj: Any, keys: set[str], label: str) -> dict:
    _must(type(obj) is dict and set(obj) == keys, label + " schema mismatch")
    return obj


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: Any, label: str) -> str:
    _must(type(value) is str and DIGEST.fullmatch(value) is not None,
          label + " must be a canonical SHA-256")
    return value


def _json(raw: bytes, limit: int) -> dict:
    try:
        return m1._parse_json(raw, limit=limit)
    except m1.PolicyError as exc:
        raise OfflineAuthorizationError("invalid or oversized simulated JSON") from exc


def _windows_path(value: Any) -> str:
    _must(type(value) is str and 4 <= len(value) <= 260, "invalid simulated Windows path")
    _must(not value.startswith("\\\\") and "%" not in value and "/" not in value,
          "UNC, substituted or noncanonical paths refused")
    drive, tail = ntpath.splitdrive(value)
    _must(re.fullmatch(r"[A-Za-z]:", drive) is not None and tail.startswith("\\"),
          "simulated path must be drive-absolute")
    _must(ntpath.normpath(value) == value and ".." not in value.split("\\"),
          "noncanonical or parent-traversing path refused")
    _must(all(part and not part.endswith((".", " ")) and ":" not in part
              for part in tail.split("\\")[1:]), "ambiguous simulated path refused")
    _must("onyxcore-v070" not in value.casefold(), "v0.7.0 paths are protected")
    return value.casefold()


def _identity(value: Any) -> tuple[str, str]:
    obj = _fields(value, {"account", "sid", "authenticated", "interactive", "session"},
                  "simulated identity")
    _must(obj["authenticated"] is True and obj["interactive"] is True and
          obj["session"] == "LoggedOnUserOnly", "simulated identity not eligible")
    account = obj["account"]
    sid = obj["sid"]
    _must(type(account) is str and m1.ACCOUNT.fullmatch(account) is not None,
          "simulated account malformed")
    _must(type(sid) is str and SID.fullmatch(sid) is not None,
          "simulated operator SID malformed")
    return account, sid


def _acl_paths(value: Any, current_sid: str) -> None:
    obj = _fields(value, set(ROLES), "simulated ACL role map")
    seen: set[str] = set()
    for role in sorted(ROLES):
        desc = _fields(obj[role], {"path", "owner_sid", "write_sids",
                                   "dacl_checked", "redirected", "inherited_untrusted_write"},
                       "simulated ACL for " + role)
        canonical = _windows_path(desc["path"])
        _must(canonical not in seen, "simulated resource paths must be distinct")
        seen.add(canonical)
        _must(desc["dacl_checked"] is True and desc["redirected"] is False and
              desc["inherited_untrusted_write"] is False,
              "unverified or redirected simulated ACL path: " + role)
        owner = desc["owner_sid"]
        _must(type(owner) is str and owner in (TRUSTED_SYSTEM_SIDS | {current_sid}),
              "simulated owner SID is untrusted: " + role)
        writers = desc["write_sids"]
        _must(type(writers) is list and 1 <= len(writers) <= 3 and
              all(type(item) is str for item in writers) and
              len(set(writers)) == len(writers), "invalid write SID list: " + role)
        _must(set(writers).issubset(TRUSTED_SYSTEM_SIDS | {current_sid}),
              "untrusted writer on simulated ACL: " + role)


def _source(value: Any, grant_commit: str) -> None:
    obj = _fields(value, {"branch", "commit_sha", "clean", "observed_component_sha256",
                          "approved_component_sha256", "source_path_redirected"},
                  "simulated source")
    _must(obj["branch"] == "feature/v0.8.0-continuous-monitoring" and
          obj["clean"] is True and obj["source_path_redirected"] is False,
          "simulated source tree not approved")
    _must(type(obj["commit_sha"]) is str and
          m1.SHA40.fullmatch(obj["commit_sha"]) is not None and
          obj["commit_sha"] == grant_commit, "simulated source commit differs")
    _must(_sha(obj["observed_component_sha256"], "observed component") ==
          _sha(obj["approved_component_sha256"], "approved component"),
          "simulated component digest differs")


def assess_simulated_preflight(config_raw: bytes, enrollment_raw: bytes,
                               revocation_raw: bytes, facts_raw: bytes) -> dict:
    """Pure, fail-closed policy exercise. NEVER grants runtime authority.

    All facts including Windows auth, ACLs, Git, revocation generation and
    consent are SIMULATED and must be independently obtained and authenticated
    by a separate future production attestor. Do not call from a live launcher.
    """
    try:
        config = m1.parse_config(config_raw)
        grant = m1.parse_enrollment(enrollment_raw)
    except m1.PolicyError as exc:
        raise OfflineAuthorizationError("M1 config or enrollment is invalid") from exc
    _must(config["enabled"] is True, "simulated configuration is disabled")

    facts = _fields(_json(facts_raw, MAX_FACTS_BYTES),
                    {"schema_version", "simulation_only", "identity", "source", "acl_paths",
                     "approval", "revocation_floor"}, "simulated facts")
    _must(type(facts["schema_version"]) is int and facts["schema_version"] == SCHEMA,
          "simulated facts version mismatch")
    _must(facts["simulation_only"] is True, "only simulation assertions accepted")
    account, sid = _identity(facts["identity"])
    _source(facts["source"], grant["source_commit_sha"])
    _acl_paths(facts["acl_paths"], sid)
    approval = _fields(facts["approval"],
                       {"operator_consent_observed", "enrollment_sha256", "config_sha256"},
                       "simulated independent approval")
    _must(approval["operator_consent_observed"] is True,
          "independent simulated consent assertion absent")
    _must(_sha(approval["enrollment_sha256"], "grant digest") ==
          _digest(enrollment_raw), "simulated enrollment changed after consent")
    _must(_sha(approval["config_sha256"], "config digest") ==
          _digest(config_raw), "simulated configuration changed after consent")
    _must(account.casefold() == grant["approved_account"].casefold(),
          "simulated identity and enrollment account differ")
    _must(grant["config_sha256"] == _digest(config_raw),
          "enrollment is bound to a different configuration")
    floor = facts["revocation_floor"]
    _must(type(floor) is int and 1 <= floor <= 2**31 - 1,
          "invalid simulated revocation revision floor")

    record = _fields(_json(revocation_raw, MAX_REVOCATION_BYTES),
                     {"schema_version", "grant_sha256", "generation", "revoked", "reason"},
                     "simulated revocation record")
    _must(type(record["schema_version"]) is int and record["schema_version"] == SCHEMA,
          "simulated revocation version mismatch")
    _must(_sha(record["grant_sha256"], "revocation grant digest") ==
          _digest(enrollment_raw), "revocation record binds a different grant")
    generation = record["generation"]
    _must(type(generation) is int and floor <= generation <= 2**31 - 1,
          "missing or stale simulated revocation record")
    _must(type(record["revoked"]) is bool and record["revoked"] is False and
          record["reason"] == "None", "grant revoked or record invalid")

    # Verify M1's complete data contract (still no runtime capability).
    try:
        m1.assess_offline_enrollment(
            config_raw, enrollment_raw, verified_account=account,
            verified_source_commit=facts["source"]["commit_sha"],
        )
    except m1.PolicyError as exc:
        raise OfflineAuthorizationError("M1 enrollment binding failed") from exc

    return {
        "source": "OnyxV080M2BOfflineAuthorization",
        "simulated_preflight": "EligibleDataOnly",
        "simulation_only": True,
        "identity_authenticated_in_windows": False,
        "windows_acls_verified": False,
        "revocation_authoritative": False,
        "runtime_enabled": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "store_modified": False,
        "repair_action": "None",
    }


def _not_redirected(path: Path) -> None:
    _must(not path.is_symlink() and not bool(getattr(path, "is_junction", lambda: False)()),
          "redirected synthetic fixture path refused")


def assess_temporary_fixture(directory: Path) -> dict:
    """Read exactly four bounded files from a test-owned temp directory.

    Does not create, delete, repair, or write any path. Never accesses the
    production worktree, v0.7.0 histories or actual v0.8.0 authorization files.
    """
    _must(isinstance(directory, Path) and directory.is_absolute(),
          "absolute temporary fixture directory required")
    _must(directory.name.startswith(FIXTURE_PREFIX) and
          directory.parent.resolve() == SIM_ROOT, "only direct test temp fixtures allowed")
    _not_redirected(directory)
    _must(directory.is_dir(), "temporary fixture directory missing")
    entries = tuple(directory.iterdir())
    _must({p.name for p in entries} == FILES and len(entries) == len(FILES),
          "temporary fixture must contain exactly four files")
    for path in entries:
        _not_redirected(path)
        _must(path.is_file(), "fixture entry is not a regular file")
    def bounded(name: str, max_size: int) -> bytes:
        # Read no more than the stated limit before parsing; do not mmap or
        # load arbitrary fixture files into memory first.
        with (directory / name).open("rb") as handle:
            return handle.read(max_size + 1)

    try:
        config = bounded("config.json", m1.MAX_CONFIG_BYTES)
        enrollment = bounded("enrollment.json", m1.MAX_ENROLLMENT_BYTES)
        revocation = bounded("revocation.json", MAX_REVOCATION_BYTES)
        facts = bounded("facts.json", MAX_FACTS_BYTES)
    except OSError as exc:
        raise OfflineAuthorizationError("synthetic fixture unreadable") from exc
    return assess_simulated_preflight(config, enrollment, revocation, facts)


def check_inert() -> dict:
    return {
        "source": "OnyxV080M2BOfflineAuthorization",
        "simulation_only": True,
        "runtime_enabled": False,
        "identity_authenticated_in_windows": False,
        "windows_acls_verified": False,
        "revocation_authoritative": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "store_modified": False,
        "repair_action": "None",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True,
                        help="fixed output; never reads a config or accesses the system")
    parser.parse_args(argv)
    print(json.dumps(check_inert(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
