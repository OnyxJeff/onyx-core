#!/usr/bin/env python3
"""ONYX CORE v0.8.0 R1: purely synthetic Windows trust-boundary contract.

NO Windows APIs, file reads, scheduled task changes, enrollment writes, probes,
network, or process launches. Caller-supplied snapshots are untrusted mock data;
even a passing mock NEVER authorizes real operations. A future OS-backed attestor
must be separately implemented, authorized, reviewed, and tested.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import ntpath
import re
from typing import Any

SCHEMA = 1
MAX_BYTES = 65536
ROLES = frozenset(("worktree", "config", "enrollment", "revocation", "state", "python", "ssh"))
TRUSTED_SIDS = frozenset(("S-1-5-18", "S-1-5-32-544"))
SID = re.compile(r"^S-1-5-21-(?:[0-9]{1,10}-){3}[0-9]{1,10}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
GRANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")
FILE_ID = re.compile(r"^[0-9a-f]{32}$")
VOLUME = re.compile(r"^[0-9a-f]{8}$")
ACCOUNT = re.compile(r"^[A-Za-z0-9_.-]{1,64}\\[A-Za-z0-9_.-]{1,64}$")
BRANCH = "feature/v0.8.0-continuous-monitoring"
DEV_ROOT = r"D:\github_repos\onyx-core-v080"


class OfflineTrustError(ValueError):
    """A simulated trust claim fails its contract; no live rights were involved."""


def need(value: bool, why: str) -> None:
    if not value:
        raise OfflineTrustError(why)


def fields(value: Any, expected: set[str] | frozenset[str], name: str) -> dict:
    need(type(value) is dict and set(value) == set(expected), name + " fields invalid")
    return value


def parse(raw: bytes) -> dict:
    need(type(raw) is bytes and 1 <= len(raw) <= MAX_BYTES, "invalid mock JSON size")
    def unique(pairs: list[tuple[str, Any]]) -> dict:
        seen: dict = {}
        for key, value in pairs:
            if key in seen:
                raise OfflineTrustError("duplicate JSON property")
            seen[key] = value
        return seen
    def nonfinite(_: str) -> None:
        raise OfflineTrustError("nonfinite JSON number")
    try:
        obj = json.loads(raw.decode("utf-8", errors="strict"),
                         object_pairs_hook=unique, parse_constant=nonfinite)
    except (UnicodeError, ValueError) as exc:
        raise OfflineTrustError("invalid synthetic JSON") from exc
    need(type(obj) is dict, "JSON root must be object")
    return obj


def fixed_sha(value: Any, name: str) -> None:
    need(type(value) is str and SHA256.fullmatch(value) is not None, name + " invalid SHA256")


def date(value: Any) -> datetime:
    need(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) is not None,
         "timestamp must be canonical UTC")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise OfflineTrustError("invalid UTC timestamp") from exc
    need(parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value, "noncanonical time")
    return parsed


def windows_path(path: Any) -> str:
    need(type(path) is str and 3 <= len(path) <= 250, "invalid synthetic Windows path")
    need("/" not in path and "%" not in path and not path.startswith("\\\\"),
         "UNC, device, environment or slash path refused")
    drive, tail = ntpath.splitdrive(path)
    need(re.fullmatch(r"[A-Za-z]:", drive) is not None and tail.startswith("\\"),
         "only drive-absolute paths allowed")
    need(ntpath.normpath(path) == path and
         (not tail.endswith("\\") or tail == "\\"), "noncanonical path")
    segments = tail.lstrip("\\").split("\\") if tail != "\\" else []
    need(all(segment and segment not in (".", "..") and not segment.endswith((".", " "))
             and not any(char in segment for char in '<>:"|?*\x00')
             and not any(ord(char) < 32 for char in segment)
             and segment.split(".")[0].casefold() not in {"con", "prn", "aux", "nul", "com1", "lpt1"}
             for segment in segments), "ambiguous Windows path component")
    need("onyxcore-v070" not in path.casefold() and
         "\\github_repos\\onyx-core\\" not in path.casefold(), "protected path")
    return path.casefold()


def prefixes(path: str) -> list[str]:
    drive, tail = ntpath.splitdrive(path)
    result = [drive + "\\"]
    for segment in tail.lstrip("\\").split("\\"):
        if segment:
            result.append(ntpath.join(result[-1], segment))
    return result


def check_grant(grant: dict) -> None:
    fields(grant, {"schema_version", "simulation_only", "approval_method", "grant_id",
                   "approved_account", "approved_sid", "source_commit", "tree_sha256",
                   "config_sha256", "generation_floor", "expires_utc", "paths"}, "mock grant")
    need(type(grant["schema_version"]) is int and grant["schema_version"] == SCHEMA and
         grant["simulation_only"] is True and grant["approval_method"] == "SyntheticOnly",
         "grant can only be simulated")
    need(type(grant["grant_id"]) is str and GRANT_ID.fullmatch(grant["grant_id"]) is not None,
         "invalid grant id")
    need(type(grant["approved_account"]) is str and ACCOUNT.fullmatch(grant["approved_account"]) is not None,
         "invalid Windows account")
    need(type(grant["approved_sid"]) is str and SID.fullmatch(grant["approved_sid"]) is not None,
         "invalid operator SID")
    need(type(grant["source_commit"]) is str and SHA40.fullmatch(grant["source_commit"]) is not None,
         "source commit invalid")
    for field in ("tree_sha256", "config_sha256"):
        fixed_sha(grant[field], field)
    need(type(grant["generation_floor"]) is int and 1 <= grant["generation_floor"] < 2**31,
         "revocation floor invalid")
    date(grant["expires_utc"])
    paths = fields(grant["paths"], ROLES, "approved path roles")
    used = set()
    for role in ROLES:
        val = windows_path(paths[role])
        need(val not in used, "overlapping approved resource")
        used.add(val)
    need(paths["worktree"].casefold() == DEV_ROOT.casefold(), "unexpected development root")
    root = DEV_ROOT.casefold() + "\\"
    need(paths["config"].casefold().startswith(root), "config must be development isolated")
    need(paths["python"].casefold() == r"c:\python313\python.exe", "unexpected Python")
    need("\\onyxcore-v080\\" in paths["enrollment"].casefold() and
         "\\onyxcore-v080\\" in paths["revocation"].casefold() and
         "\\onyxcore-v080\\" in paths["state"].casefold(), "isolated v0.8 state paths required")
    need(paths["ssh"].casefold().endswith(r"\.ssh\onyxcore_monitor_ed25519"), "unexpected SSH key path")


def check_token(token: Any, grant: dict) -> None:
    fields(token, {"account", "sid", "session_id", "logon_type", "is_elevated",
                   "windows_authenticated", "claim_origin"}, "mock token")
    need(type(token["account"]) is str and token["account"].casefold() == grant["approved_account"].casefold() and
         token["sid"] == grant["approved_sid"], "operator identity mismatch")
    need(type(token["session_id"]) is int and 1 <= token["session_id"] <= 65535 and
         token["logon_type"] == "Interactive" and token["is_elevated"] is False and
         token["windows_authenticated"] is False and token["claim_origin"] == "SyntheticFixture",
         "mock token is not a safe synthetic interactive claim")


def check_chain(role: str, data: Any, expected_path: str, approved_sid: str) -> None:
    fields(data, {"path", "final_path", "components", "source_handle_stable"}, "mock path")
    need(windows_path(data["path"]) == windows_path(expected_path) and
         windows_path(data["final_path"]) == windows_path(expected_path) and
         data["source_handle_stable"] is True, "final path or mock handle mismatch")
    required = prefixes(expected_path)
    components = data["components"]
    need(type(components) is list and len(components) == len(required), "ancestor inventory incomplete")
    seen = set()
    volume = None
    for expected, obj in zip(required, components):
        fields(obj, {"path", "volume_id", "file_id", "reparse_tag", "dacl_examined",
                     "owner_sid", "effective_writers", "inherited_untrusted_write"}, "mock path ancestor")
        need(windows_path(obj["path"]) == windows_path(expected), "ancestor path mismatch")
        need(type(obj["volume_id"]) is str and VOLUME.fullmatch(obj["volume_id"]) is not None and
             type(obj["file_id"]) is str and FILE_ID.fullmatch(obj["file_id"]) is not None,
             "invalid mock file identity")
        if volume is None:
            volume = obj["volume_id"]
        need(obj["volume_id"] == volume and obj["file_id"] not in seen,
             "volume swap, inode collision, or loop")
        seen.add(obj["file_id"])
        need(type(obj["reparse_tag"]) is int and obj["reparse_tag"] == 0 and
             obj["dacl_examined"] is True and obj["inherited_untrusted_write"] is False,
             "reparse point or unverified ancestor ACL")
        need(type(obj["owner_sid"]) is str and
             obj["owner_sid"] in TRUSTED_SIDS | {approved_sid}, "untrusted owner")
        writers = obj["effective_writers"]
        need(type(writers) is list and 1 <= len(writers) <= 3 and
             all(type(v) is str for v in writers) and len(set(writers)) == len(writers) and
             set(writers).issubset(TRUSTED_SIDS | {approved_sid}), "untrusted or malformed writers")


def check_snapshot(s: dict, grant: dict) -> datetime:
    fields(s, {"schema_version", "simulation_only", "mock_provider", "sequence", "captured_at_utc",
               "token", "source", "paths", "consent", "revocation"}, "mock snapshot")
    need(type(s["schema_version"]) is int and s["schema_version"] == SCHEMA and
         s["simulation_only"] is True and s["mock_provider"] == "SyntheticWindowsTrustProvider",
         "only mock provider allowed")
    need(type(s["sequence"]) is int and s["sequence"] in (1, 2), "invalid sequence")
    now = date(s["captured_at_utc"])
    need(now < date(grant["expires_utc"]), "synthetic consent expired")
    check_token(s["token"], grant)
    source = fields(s["source"], {"branch", "commit", "tree_sha256", "config_sha256",
                                  "clean", "source_handle_stable"}, "mock source")
    need(source["branch"] == BRANCH and source["commit"] == grant["source_commit"] and
         source["tree_sha256"] == grant["tree_sha256"] and
         source["config_sha256"] == grant["config_sha256"] and
         source["clean"] is True and source["source_handle_stable"] is True,
         "source commit, digest, or handle mismatch")
    consent = fields(s["consent"], {"grant_id", "approved_digest", "approved_by_windows"}, "mock consent")
    need(consent["grant_id"] == grant["grant_id"] and
         consent["approved_digest"] == grant["config_sha256"] and
         consent["approved_by_windows"] is False, "only hypothetical consent allowed")
    revoke = fields(s["revocation"], {"grant_id", "generation", "revoked", "authoritative"}, "mock revocation")
    need(revoke["grant_id"] == grant["grant_id"] and
         type(revoke["generation"]) is int and revoke["generation"] >= grant["generation_floor"] and
         revoke["generation"] < 2**31 and revoke["revoked"] is False and
         revoke["authoritative"] is False, "revocation gate fails closed")
    paths = fields(s["paths"], ROLES, "mock observed paths")
    for role in ROLES:
        check_chain(role, paths[role], grant["paths"][role], grant["approved_sid"])
    return now


def assess_synthetic_trust(grant_raw: bytes, before_raw: bytes, after_raw: bytes) -> dict:
    """Validate mock before/after observations, ALWAYS return no live authority.

    A malicious fixture can forge every assertion; this is a data-contract test,
    NOT Windows authentication, a usable grant, or a live safety attestation.
    """
    grant = parse(grant_raw)
    before = parse(before_raw)
    after = parse(after_raw)
    check_grant(grant)
    btime = check_snapshot(before, grant)
    atime = check_snapshot(after, grant)
    need(before["sequence"] == 1 and after["sequence"] == 2 and
         0 < (atime - btime).total_seconds() <= 90, "stale, reversed or unbounded mock cycle")
    # Revalidation model: every security-sensitive observation must remain stable.
    identical_before = {k: v for k, v in before.items() if k not in ("sequence", "captured_at_utc")}
    identical_after = {k: v for k, v in after.items() if k not in ("sequence", "captured_at_utc")}
    need(identical_before == identical_after, "token, path, ACL, source, consent or revocation changed")
    return check_inert()


def check_inert() -> dict:
    return {
        "source": "OnyxV080R1SyntheticWindowsTrust",
        "simulation_only": True,
        "runtime_enabled": False,
        "identity_authenticated_in_windows": False,
        "windows_acls_verified": False,
        "revocation_authoritative": False,
        "live_probe_authorized": False,
        "task_creation_authorized": False,
        "enrollment_authorized": False,
        "notification_enabled": False,
        "delivery_permitted": False,
        "store_modified": False,
        "repair_action": "None",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inert", action="store_true", required=True,
                        help="emit constant denial; no files, Windows API calls or fixtures")
    parser.parse_args(argv)
    print(json.dumps(check_inert(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
