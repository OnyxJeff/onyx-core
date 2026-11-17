#!/usr/bin/env python3
"""ONYX CORE release artifact builder/verifier (stdlib; no installation).

Builds solely from committed Git objects, not the working directory. Archives use
stored ZIP entries, fixed metadata, sorted paths and canonical JSON to make two
consecutive builds byte-identical across supported hosts.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

FORMAT_VERSION = 1
PRODUCT = "ONYX CORE"
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][A-Za-z0-9.-]+)?\Z")
PLATFORMS = ("windows", "pi-armv6")


def die(message: str) -> None:
    raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def run_git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if result.returncode:
        die("git command failed: " + " ".join(args) + ": " +
            result.stderr.decode("utf-8", "replace").strip()[:300])
    return result.stdout


def assert_commit(repo: Path, commit: str) -> None:
    if not HEX40.fullmatch(commit):
        die("--commit must be a full lowercase 40-character Git SHA")
    value = run_git(repo, "cat-file", "-t", commit).decode().strip()
    if value != "commit":
        die("source SHA is not a Git commit")
    resolved = run_git(repo, "rev-parse", "--verify", commit + "^{commit}").decode().strip()
    if resolved != commit:
        die("source commit mismatch")


def admissible_path(path: str) -> bool:
    p = PurePosixPath(path)
    if not path or p.is_absolute() or "\\" in path or p.as_posix() != path:
        return False
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    low = path.lower()
    if any(low.endswith(ext) for ext in (
        ".env", ".key", ".pem", ".pfx", ".p12", ".db", ".sqlite",
        ".sqlite3", ".db-wal", ".db-shm", ".dpapi", ".pyc")):
        return False
    if p.parts[0].lower() in ("backups", "logs", "recovery"):
        return False
    if any(part.lower() in (".git", "__pycache__") for part in p.parts):
        return False
    return True


def selected(platform: str, path: str) -> bool:
    if platform not in PLATFORMS:
        return False
    common = (path == "README.md" or path == "CHANGELOG.md" or
              path.startswith("docs/installation/") or
              path.startswith("docs/v0.9.0/") or
              path.startswith("tools/release/") or
              path.startswith("tools/installation/common/"))
    if platform == "windows":
        return common or path.startswith((
            "windows/collector/", "windows/gateway/", "windows/networking/",
            "windows/monitoring/", "tools/installation/windows/"))
    return common or path.startswith((
        "pi/services/receiver/", "pi/scripts/", "tools/installation/pi/"))


def tracked_payload(repo: Path, commit: str) -> dict[str, bytes]:
    """Use git archive to read the immutable commit independent of checkout EOL."""
    archive = run_git(repo, "archive", "--format=tar", commit)
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
        for item in tf:
            if item.isdir():
                continue
            name = item.name
            if not admissible_path(name):
                die("unsafe or private tracked content: " + name)
            if not item.isfile() or item.issym() or item.islnk():
                die("non-regular tracked content refused: " + name)
            if name in result:
                die("duplicate Git archive member: " + name)
            source = tf.extractfile(item)
            if source is None:
                die("unable to read Git archive member")
            result[name] = source.read()
    return result


def encode_zip(platform: str, version: str, commit: str,
               all_files: dict[str, bytes]) -> bytes:
    subset = {p: b for p, b in all_files.items() if selected(platform, p)}
    essential = "windows/collector/Send-OnyxTelemetry.ps1" if platform == "windows" else "pi/services/receiver/receiver.py"
    if essential not in subset:
        die("required runtime file missing: " + essential)
    manifest = {
        "schema_version": FORMAT_VERSION,
        "product": PRODUCT,
        "version": version,
        "platform": platform,
        "source_commit": commit,
        "files": [{"path": path, "size": len(subset[path]),
                   "sha256": sha256(subset[path])} for path in sorted(subset)],
    }
    data = {"manifest.json": canonical(manifest)}
    data.update(subset)
    sink = io.BytesIO()
    with zipfile.ZipFile(sink, mode="w", allowZip64=True) as zf:
        for name in sorted(data):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (0o100644 << 16)
            zf.writestr(info, data[name])
    return sink.getvalue()


def verify_archive(path: Path) -> dict:
    with zipfile.ZipFile(path, mode="r") as zf:
        infos = zf.infolist()
        names = [entry.filename for entry in infos]
        if len(names) != len(set(names)) or not names or names != sorted(names):
            die("duplicate, empty or unsorted archive entries")
        if "manifest.json" not in names:
            die("manifest.json missing")
        if any(not admissible_path(n) for n in names):
            die("unsafe file in package")
        for entry in infos:
            if entry.is_dir() or entry.compress_type != zipfile.ZIP_STORED or entry.date_time != ZIP_DATE:
                die("unexpected archive entry metadata")
        manifest = json.loads(zf.read("manifest.json"))
        if set(manifest) != {"schema_version", "product", "version", "platform", "source_commit", "files"}:
            die("unexpected manifest schema")
        if (manifest["schema_version"] != FORMAT_VERSION or manifest["product"] != PRODUCT or
            manifest["platform"] not in PLATFORMS or
            not HEX40.fullmatch(manifest["source_commit"]) or
            not VERSION.fullmatch(manifest["version"])):
            die("invalid manifest metadata")
        if canonical(manifest) != zf.read("manifest.json"):
            die("noncanonical manifest")
        rows = manifest["files"]
        if type(rows) is not list or any(type(r) is not dict or set(r) != {"path", "size", "sha256"} for r in rows):
            die("invalid file inventory")
        paths = [r["path"] for r in rows]
        if paths != sorted(paths) or len(paths) != len(set(paths)) or set(names) != {"manifest.json", *paths}:
            die("file inventory does not match package")
        for row in rows:
            p = row["path"]
            if (type(p) is not str or not admissible_path(p) or
                not selected(manifest["platform"], p) or
                type(row["size"]) is not int or row["size"] < 0 or
                type(row["sha256"]) is not str or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])):
                die("invalid file inventory entry")
            content = zf.read(p)
            if len(content) != row["size"] or sha256(content) != row["sha256"]:
                die("package file integrity mismatch: " + p)
    return manifest


def write_if_identical_or_new(dest: Path, content: bytes) -> None:
    if dest.exists():
        if dest.read_bytes() != content:
            die("destination exists with different bytes; refusing overwrite: " + str(dest))
    else:
        dest.write_bytes(content)


def build(repo: Path, commit: str, version: str, out: Path) -> None:
    if not VERSION.fullmatch(version):
        die("invalid semantic release version")
    assert_commit(repo, commit)
    files = tracked_payload(repo, commit)
    out.mkdir(parents=True, exist_ok=True)
    for platform in PLATFORMS:
        name = f"ONYX_CORE-v{version}-{platform}.zip"
        dest = out / name
        raw = encode_zip(platform, version, commit, files)
        # Verify bytes in a disposable file before publishing to the output folder.
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            temporary = Path(t) / name
            temporary.write_bytes(raw)
            result = verify_archive(temporary)
        if result["source_commit"] != commit:
            die("built package source does not match requested commit")
        write_if_identical_or_new(dest, raw)
        write_if_identical_or_new(out / (name + ".sha256"),
                                  f"{sha256(raw)}  {name}\n".encode("ascii"))
        print(f"PASS {name}: {len(result['files'])} files, SHA256 {sha256(raw)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build deterministic Windows and Pi archives from a Git commit")
    b.add_argument("--repo", type=Path, required=True)
    b.add_argument("--commit", required=True)
    b.add_argument("--version", required=True)
    b.add_argument("--out", type=Path, required=True)
    v = sub.add_parser("verify", help="verify an archive without extraction or installation")
    v.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args.repo, args.commit, args.version, args.out)
        else:
            result = verify_archive(args.archive)
            print(f"PASS {args.archive.name}: {len(result['files'])} files; "
                  f"{result['platform']} v{result['version']} commit {result['source_commit']}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, zipfile.BadZipFile,
            tarfile.TarError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
