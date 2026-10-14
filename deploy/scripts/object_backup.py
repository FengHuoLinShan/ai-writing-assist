#!/usr/bin/env python3
"""DB-paired private object manifests, streaming mirrors, and restore reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = "ai-writing-object-backup/v1"
CATEGORIES = {"map_page", "map_mask", "world_full", "world_thumbnail"}


def private_dir(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("Unsafe private object directory")


def private_file(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ValueError("Unsafe private object file")


def row_file(row: dict) -> str:
    name = row.get("file", row["bucket"] + "/" + row["key"])
    if (
        not isinstance(name, str)
        or name.startswith("/")
        or "\\" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or any(ord(character) < 32 for character in name)
    ):
        raise ValueError("Unsafe package relative filename")
    return name


def object_path(root: Path, row: dict, *, create: bool = False) -> Path:
    path = root
    name = row_file(row)
    for component in name.split("/")[:-1]:
        path /= component
        if create:
            private_dir(path)
        elif path.is_symlink() or not path.is_dir():
            raise ValueError("Unsafe object path")
    path /= name.split("/")[-1]
    if path.is_symlink():
        raise ValueError("Symlink object path")
    return path


def validate_row(row: dict, buckets: dict[str, str], *, complete: bool = False) -> None:
    row_file(row)
    novel = str(uuid.UUID(row["novel_id"]))
    category = row["category"]
    if category not in CATEGORIES or row["novel_id"] != novel:
        raise ValueError("Invalid object category or novel")
    key = row["key"]
    identifier = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
    if category.startswith("map_"):
        filename = (
            r"mask\.png"
            if category == "map_mask"
            else r"(?:attempts/[a-z0-9-]{1,80}/)?image\.png"
        )
        pattern = rf"map-atlas/{novel}/pages/{identifier}/{filename}"
        bucket = buckets["map"]
    else:
        variant = "full" if category == "world_full" else "thumbnail"
        pattern = rf"world-objects/{novel}/entities/{identifier}/images/{identifier}/{variant}\.webp"
        bucket = buckets["world"]
    if row["bucket"] != bucket or not re.fullmatch(pattern, key):
        raise ValueError("Object key/bucket does not match category and novel")
    digest, size = row.get("sha256"), row.get("byte_size")
    if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid object hash")
    if size is not None and (type(size) is not int or size <= 0):
        raise ValueError("Invalid object size")
    if complete and (digest is None or size is None or row.get("status") != "ok"):
        raise ValueError("Incomplete object record")


def atomic_write(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        private_file(path)
    fd, name = tempfile.mkstemp(prefix=".stage-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def publish(directory: Path, manifest: dict) -> None:
    payload = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    atomic_write(directory / "manifest.json", payload)
    atomic_write(
        directory / "manifest.sha256",
        (hashlib.sha256(payload).hexdigest() + "\n").encode(),
    )


def read_manifest(
    directory: Path, buckets: dict[str, str], *, complete: bool = True
) -> dict:
    private_dir(directory)
    for name in ("manifest.json", "manifest.sha256"):
        private_file(directory / name)
    payload = (directory / "manifest.json").read_bytes()
    if (directory / "manifest.sha256").read_text().strip() != hashlib.sha256(
        payload
    ).hexdigest():
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(payload)
    if manifest["schema"] != SCHEMA or (complete and manifest["status"] != "complete"):
        raise ValueError("Object backup is incomplete or unsupported")
    timestamp = manifest["timestamp"]
    datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    source = manifest["source_kind"]
    if source == "server_snapshot":
        if (
            manifest["db_timestamp"] != timestamp
            or manifest["db_dump"] != f"{timestamp}.dump"
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["db_sha256"])
        ):
            raise ValueError("Invalid paired DB snapshot")
    elif source == "author_export":
        if any(
            manifest.get(key) is not None
            for key in ("db_timestamp", "db_sha256", "db_dump")
        ):
            raise ValueError("Author export must not claim a DB snapshot")
    else:
        raise ValueError("Unknown object manifest source")
    seen = set()
    filenames = set()
    for row in manifest["objects"]:
        validate_row(row, buckets, complete=complete)
        identity = (row["bucket"], row["key"])
        if identity in seen:
            raise ValueError("Duplicate object record")
        seen.add(identity)
        name = row_file(row)
        if name in filenames:
            raise ValueError("Duplicate package filename")
        filenames.add(name)
    return manifest


def digest_file(path: Path) -> tuple[str, int]:
    private_file(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return digest, path.stat().st_size


def valid_image(path: Path, category: str) -> None:
    from PIL import Image

    with Image.open(path) as image:
        expected = "PNG" if category.startswith("map_") else "WEBP"
        if image.format != expected:
            raise ValueError("Unexpected image format")
        image.load()


def mirror_row(client, root: Path, row: dict, cached: dict | None) -> None:
    path = object_path(root, row, create=True)
    if cached and path.exists():
        # Immutable-key cache is trusted only after local hash and live HEAD checks.
        head = client.head_object(Bucket=row["bucket"], Key=row["key"])
        if (
            digest_file(path) == (cached["sha256"], cached["byte_size"])
            and head["ContentLength"] == cached["byte_size"]
            and head.get("Metadata", {}) == cached.get("metadata", {})
            and head.get("ContentType") == cached.get("content_type")
            and (not row.get("sha256") or row["sha256"] == cached["sha256"])
            and (not row.get("byte_size") or row["byte_size"] == cached["byte_size"])
        ):
            row.update(
                sha256=cached["sha256"],
                byte_size=cached["byte_size"],
                metadata=cached.get("metadata", {}),
                content_type=cached["content_type"],
                status="ok",
            )
            return
    response = client.get_object(Bucket=row["bucket"], Key=row["key"])
    body = response["Body"]
    fd, staging = tempfile.mkstemp(prefix=".stage-", dir=path.parent)
    try:
        hasher, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as output:
            for chunk in iter(lambda body=body: body.read(1024 * 1024), b""):
                hasher.update(chunk)
                size += len(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        actual = hasher.hexdigest()
        if (row.get("sha256") and row["sha256"] != actual) or (
            row.get("byte_size") and row["byte_size"] != size
        ):
            raise ValueError("DB object checksum/size mismatch")
        try:
            valid_image(Path(staging), row["category"])
        except Exception as exc:  # noqa: BLE001 - any undecodable body is damage to this one object.
            raise ValueError("Object is not a valid image") from exc
        if not path.exists() or digest_file(path) != (actual, size):
            os.replace(staging, path)
        row.update(
            sha256=actual,
            byte_size=size,
            status="ok",
            content_type=response.get("ContentType", "application/octet-stream"),
            metadata=response.get("Metadata", {}),
        )
    finally:
        body.close()
        Path(staging).unlink(missing_ok=True)


def mirror(
    client,
    root: Path,
    rows: list[dict],
    directory: Path,
    manifest: dict,
    trusted: dict | None = None,
) -> bool:
    """A failed read never publishes a partial object or a complete manifest.

    A missing or damaged object is recorded and later objects are still copied;
    transport, permission and local disk failures stop the run.
    """
    private_dir(root)
    manifest["objects"] = rows
    manifest["status"] = "incomplete"
    for row in rows:
        row["status"] = "pending"
    publish(directory, manifest)
    success = True
    try:
        for row in rows:
            try:
                mirror_row(
                    client, root, row, (trusted or {}).get((row["bucket"], row["key"]))
                )
            except Exception as exc:  # noqa: BLE001 - record any failed copy as incomplete.
                # SDK errors may embed endpoint/request details; save sanitized codes only.
                error = getattr(exc, "response", {}).get("Error", {})
                code = error.get("Code", "read_failed")
                row["status"] = "missing" if code in {"NoSuchKey", "404"} else "failed"
                row["failure_kind"] = type(exc).__name__
                success = False
                if row["status"] == "failed" and not isinstance(exc, ValueError):
                    break
    finally:
        manifest["status"] = "complete" if success else "incomplete"
        publish(directory, manifest)
    return success


def unique_references(rows: list[dict]) -> list[dict]:
    unique = {}
    for row in rows:
        identity = (row["bucket"], row["key"])
        previous = unique.get(identity)
        if previous:
            for field in ("novel_id", "category", "sha256", "byte_size"):
                if previous.get(field) != row.get(field):
                    raise ValueError("Conflicting duplicate DB object reference")
        else:
            unique[identity] = row
    return list(unique.values())


def trusted_objects(root: Path, buckets: dict[str, str], days: int) -> dict:
    now = datetime.now(UTC)
    trusted = {}
    for path in (root / "snapshots").iterdir():
        try:
            manifest = read_manifest(path, buckets, complete=False)
            for row in manifest["objects"]:
                if row.get("status") == "ok":
                    validate_row(row, buckets, complete=True)
        except Exception as exc:  # noqa: BLE001 - unreadable optional cache must not block new backups.
            print(
                f"Object backup history unreadable ({type(exc).__name__}); "
                "cache ignored; retention requires reconciliation.",
                file=sys.stderr,
            )
            continue
        timestamp = datetime.strptime(manifest["timestamp"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        if (
            manifest["source_kind"] != "server_snapshot"
            or not now - timedelta(days=days) <= timestamp <= now
        ):
            continue
        for row in manifest["objects"]:
            if row.get("status") != "ok":
                continue
            identity = (row["bucket"], row["key"])
            previous = trusted.get(identity)
            if previous and (previous["sha256"], previous["byte_size"]) != (
                row["sha256"],
                row["byte_size"],
            ):
                raise ValueError("Immutable-key backup history has conflicting hashes")
            trusted[identity] = row
    return trusted


def require_target_references(
    manifest: dict, references: list[dict], buckets: dict[str, str]
) -> None:
    owned = {}
    for row in references:
        validate_row(row, buckets)
        owned[(row["novel_id"], row["bucket"], row["key"])] = row
    for row in manifest["objects"]:
        target = owned.get((row["novel_id"], row["bucket"], row["key"]))
        if target is None:
            raise ValueError("Object is not referenced by the target DB")
        if (target.get("sha256") and target["sha256"] != row["sha256"]) or (
            target.get("byte_size") and target["byte_size"] != row["byte_size"]
        ):
            raise ValueError("Object differs from the target DB reference")


def verify_local(root: Path, manifest: dict) -> None:
    # Check every local object before writing any remote bytes.
    for row in manifest["objects"]:
        path = object_path(root, row)
        if digest_file(path) != (row["sha256"], row["byte_size"]):
            raise ValueError("Local object checksum/size mismatch")
        valid_image(path, row["category"])


def restore(client, root: Path, manifest: dict) -> None:
    verify_local(root, manifest)
    for row in manifest["objects"]:
        path = object_path(root, row)
        with path.open("rb") as stream:
            client.put_object(
                Bucket=row["bucket"],
                Key=row["key"],
                Body=stream,
                ContentLength=row["byte_size"],
                ContentType=row.get("content_type", "application/octet-stream"),
                Metadata=row.get("metadata", {}),
            )
        response = client.get_object(Bucket=row["bucket"], Key=row["key"])
        body = response["Body"]
        hasher, size = hashlib.sha256(), 0
        fd, staging = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as output:
                for chunk in iter(lambda body=body: body.read(1024 * 1024), b""):
                    hasher.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            if (hasher.hexdigest(), size) != (row["sha256"], row["byte_size"]):
                raise ValueError("Restored object checksum/size mismatch")
            if response.get("Metadata", {}) != row.get("metadata", {}) or response.get(
                "ContentType"
            ) != row.get("content_type"):
                raise ValueError("Restored object metadata mismatch")
            valid_image(Path(staging), row["category"])
        finally:
            body.close()
            Path(staging).unlink(missing_ok=True)


def prune(
    root: Path, buckets: dict[str, str], days: int, *, now: datetime | None = None
) -> None:
    if not 1 <= days <= 30:
        raise ValueError("Retention must be within 30 days")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    references = set()
    snapshots = root / "snapshots"
    private_dir(snapshots)
    # Validate all manifests first: corruption must not cause collection of their objects.
    manifests = [
        (path, read_manifest(path, buckets, complete=False))
        for path in snapshots.iterdir()
    ]
    for path, manifest in manifests:
        timestamp = datetime.strptime(manifest["timestamp"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=UTC
        )
        if timestamp < cutoff:
            (path / "manifest.sha256").unlink()
            (path / "manifest.json").unlink()
            path.rmdir()
        else:
            references.update(
                (row["bucket"], row["key"]) for row in manifest["objects"]
            )
    objects = root / "objects"
    private_dir(objects)
    for path in objects.rglob("*"):
        if path.is_symlink():
            raise ValueError("Unsafe mirror symlink")
        if not path.is_file():
            continue
        private_file(path)
        parts = path.relative_to(objects).parts
        identity = (parts[0], "/".join(parts[1:]))
        if (
            identity not in references
            and datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
        ):
            path.unlink()
    for path in sorted(
        objects.rglob("*"), key=lambda path: len(path.parts), reverse=True
    ):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def unpack_package(source: Path, target: Path, buckets: dict[str, str]) -> str:
    """v1 image ZIP uses the identical snapshots/objects layout; no arbitrary extraction."""
    private_file(source)
    private_dir(target)
    if any(target.iterdir()):
        raise ValueError("Package target must be empty")
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        manifests = [
            name
            for name in names
            if re.fullmatch(r"snapshots/[0-9]{8}T[0-9]{6}Z/manifest.json", name)
        ]
        if len(manifests) != 1 or len(set(names)) != len(names):
            raise ValueError(
                "Package must contain one manifest and no duplicate members"
            )
        manifest_name = manifests[0]
        digest_name = manifest_name.replace("manifest.json", "manifest.sha256")
        payload = archive.read(manifest_name)
        if (
            archive.read(digest_name).decode().strip()
            != hashlib.sha256(payload).hexdigest()
        ):
            raise ValueError("Package manifest checksum mismatch")
        manifest = json.loads(payload)
        if manifest["schema"] != SCHEMA or manifest["status"] != "complete":
            raise ValueError("Package incomplete or unsupported")
        timestamp = manifest_name.split("/")[1]
        if timestamp != manifest["timestamp"]:
            raise ValueError("Package DB timestamp mismatch")
        allowed = {manifest_name, digest_name}
        for row in manifest["objects"]:
            validate_row(row, buckets, complete=True)
            allowed.add("objects/" + row_file(row))
        if set(names) != allowed:
            raise ValueError("Package contains unexpected or missing files")
        for name in names:
            destination = target / name
            for parent in reversed(destination.parents):
                if parent == target or target in parent.parents:
                    private_dir(parent)
            with archive.open(name) as body, destination.open("xb") as output:
                os.fchmod(output.fileno(), 0o600)
                for chunk in iter(lambda: body.read(1024 * 1024), b""):
                    output.write(chunk)
        checked = read_manifest(target / "snapshots" / timestamp, buckets)
        for row in checked["objects"]:
            path = object_path(target / "objects", row)
            if digest_file(path) != (row["sha256"], row["byte_size"]):
                raise ValueError("Package object checksum mismatch")
            valid_image(path, row["category"])
    return timestamp


def s3_client(*, backup: bool):
    import boto3
    from botocore.config import Config

    prefix = "MINIO_BACKUP" if backup else "MAP_ATLAS_S3"
    access = os.environ[f"{prefix}_ACCESS_KEY" if backup else f"{prefix}_ACCESS_KEY_ID"]
    secret = os.environ[
        f"{prefix}_SECRET_KEY" if backup else f"{prefix}_SECRET_ACCESS_KEY"
    ]
    return boto3.client(
        "s3",
        endpoint_url=os.environ["MAP_ATLAS_S3_ENDPOINT_URL"],
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name=os.environ.get("MAP_ATLAS_S3_REGION", "us-east-1"),
        config=Config(
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=60,
            retries={"max_attempts": 2},
        ),
    )


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("backup", "restore", "verify", "prune", "unpack")
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--references", type=Path)
    parser.add_argument("--timestamp")
    parser.add_argument("--db-sha256")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--target-references", type=Path)
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    buckets = {
        "map": os.environ["MAP_ATLAS_S3_BUCKET"],
        "world": os.environ["WORLD_OBJECT_S3_BUCKET"],
    }
    try:
        private_dir(args.root)
        if args.operation == "unpack":
            print(unpack_package(args.package, args.root, buckets))
            return 0
        if args.operation == "backup":
            rows = unique_references(json.loads(args.references.read_text()))
            for row in rows:
                validate_row(row, buckets)
            datetime.strptime(args.timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            if not re.fullmatch(r"[0-9a-f]{64}", args.db_sha256):
                raise ValueError("Invalid DB checksum")
            private_dir(args.root / "snapshots")
            cache = trusted_objects(args.root, buckets, args.retention_days)
            directory = args.root / "snapshots" / args.timestamp
            directory.mkdir(mode=0o700)
            manifest = {
                "schema": SCHEMA,
                "source_kind": "server_snapshot",
                "timestamp": args.timestamp,
                "db_timestamp": args.timestamp,
                "db_sha256": args.db_sha256,
                "db_dump": f"{args.timestamp}.dump",
            }
            success = mirror(
                s3_client(backup=True),
                args.root / "objects",
                rows,
                directory,
                manifest,
                cache,
            )
            counts = Counter(row["status"] for row in rows)
            print(
                f"Object backup {'complete' if success else 'incomplete'}: "
                f"objects={len(rows)} "
                + " ".join(f"{status}={counts[status]}" for status in sorted(counts))
            )
            try:
                prune(args.root, buckets, args.retention_days)
            except Exception as exc:  # noqa: BLE001 - preserve the new snapshot and signal failed retention.
                print(
                    f"Object retention incomplete ({type(exc).__name__}); "
                    "private history requires reconciliation.",
                    file=sys.stderr,
                )
                return 1
            return 0 if success else 1
        if args.operation == "prune":
            prune(args.root, buckets, args.retention_days)
        else:
            manifest = read_manifest(args.snapshot, buckets)
            if args.target_references is None:
                raise ValueError("Restore requires target DB object references")
            require_target_references(
                manifest, json.loads(args.target_references.read_text()), buckets
            )
            if args.operation == "verify":
                verify_local(args.root / "objects", manifest)
                print("Object package and target references verified")
                return 0
            restore(s3_client(backup=False), args.root / "objects", manifest)
            print(f"Object restore complete: objects={len(manifest['objects'])}")
        return 0
    except Exception as exc:  # noqa: BLE001 - operator output must never leak SDK credential details.
        print(
            f"Object operation incomplete ({type(exc).__name__}); private manifest/objects require reconciliation.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
