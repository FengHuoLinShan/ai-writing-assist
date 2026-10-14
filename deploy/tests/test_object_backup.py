from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

SCRIPT = Path(__file__).parents[1] / "scripts" / "object_backup.py"
spec = importlib.util.spec_from_file_location("object_backup", SCRIPT)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
NOVEL = "11111111-1111-4111-8111-111111111111"
PAGE = "22222222-2222-4222-8222-222222222222"
BUCKETS = {"map": "private-maps", "world": "private-world"}


def image_bytes(format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (12, 16), "blue").save(stream, format=format)
    return stream.getvalue()


def row():
    payload = image_bytes()
    return {
        "novel_id": NOVEL,
        "bucket": BUCKETS["map"],
        "key": f"map-atlas/{NOVEL}/pages/{PAGE}/image.png",
        "category": "map_page",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byte_size": len(payload),
    }


class ObjectClient:
    def __init__(self, objects, fail_after=None):
        self.objects = objects
        self.reads = 0
        self.fail_after = fail_after

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:

            class MissingObject(Exception):
                def __init__(self):
                    self.response = {"Error": {"Code": "NoSuchKey"}}

            raise MissingObject()
        payload, content_type, metadata = self.objects[Bucket, Key]
        return {
            "ContentLength": len(payload),
            "ContentType": content_type,
            "Metadata": metadata,
        }

    def get_object(self, Bucket, Key):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise OSError("secret source endpoint deliberately never serialized")
        self.reads += 1
        payload, content_type, metadata = self.objects[Bucket, Key]
        return {
            "Body": io.BytesIO(payload),
            "ContentType": content_type,
            "Metadata": metadata,
        }

    def put_object(self, Bucket, Key, Body, ContentLength, ContentType, Metadata):
        self.objects[Bucket, Key] = Body.read(), ContentType, Metadata


def setup_backup(tmp_path, *, timestamp="20261014T000000Z", fail_after=None):
    tmp_path.chmod(0o700)
    root = tmp_path / "objects"
    backup.private_dir(root)
    backup.private_dir(root / "snapshots")
    directory = root / "snapshots" / timestamp
    backup.private_dir(directory)
    rows = [row()]
    client = ObjectClient(
        {
            (rows[0]["bucket"], rows[0]["key"]): (
                image_bytes(),
                "image/png",
                {"test": "synthetic"},
            )
        },
        fail_after,
    )
    manifest = {
        "schema": backup.SCHEMA,
        "source_kind": "server_snapshot",
        "timestamp": timestamp,
        "db_timestamp": timestamp,
        "db_sha256": "f" * 64,
        "db_dump": f"{timestamp}.dump",
    }
    result = backup.mirror(client, root / "objects", rows, directory, manifest)
    return root, directory, manifest, client, result


def test_streaming_mirror_restore_metadata_and_incremental_identity(tmp_path):
    root, directory, manifest, client, result = setup_backup(tmp_path)
    assert result
    manifest = backup.read_manifest(directory, BUCKETS)
    path = backup.object_path(root / "objects", manifest["objects"][0])
    before = path.stat().st_ino
    reads = client.reads
    trusted = {(r["bucket"], r["key"]): copy.deepcopy(r) for r in manifest["objects"]}
    backup.mirror(
        client, root / "objects", manifest["objects"], directory, manifest, trusted
    )
    assert client.reads == reads
    assert path.stat().st_ino == before
    target = ObjectClient({})
    backup.restore(target, root / "objects", backup.read_manifest(directory, BUCKETS))
    assert target.objects == client.objects
    assert path.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700


def test_interrupted_copy_is_incomplete_and_cannot_restore(tmp_path):
    root, directory, manifest, _, result = setup_backup(tmp_path, fail_after=0)
    assert not result
    assert manifest["status"] == "incomplete"
    assert "secret" not in (directory / "manifest.json").read_text()
    with pytest.raises(ValueError, match="incomplete"):
        backup.read_manifest(directory, BUCKETS)
    assert not list((root / "objects").rglob("*.png"))
    assert not list((root / "objects").rglob(".stage-*"))


def test_missing_file_and_hash_tamper_fail_before_remote_write(tmp_path):
    root, _directory, manifest, _, _ = setup_backup(tmp_path)
    path = backup.object_path(root / "objects", manifest["objects"][0])
    target = ObjectClient({})
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        backup.restore(target, root / "objects", manifest)
    assert target.objects == {}
    path.unlink()
    with pytest.raises(FileNotFoundError):
        backup.restore(target, root / "objects", manifest)
    assert target.objects == {}


@pytest.mark.parametrize(
    "change",
    [
        {"novel_id": "33333333-3333-4333-8333-333333333333"},
        {"key": "../../outside"},
        {"bucket": "another-bucket"},
        {"sha256": "invalid"},
        {"byte_size": -1},
        {"category": "other"},
    ],
)
def test_manifest_key_and_novel_boundary(change):
    with pytest.raises(ValueError):
        backup.validate_row(row() | change, BUCKETS)


def test_corrupt_manifest_stops_retention_before_deletion(tmp_path):
    root, directory, manifest, _, _ = setup_backup(
        tmp_path, timestamp="20260801T000000Z"
    )
    (directory / "manifest.json").write_text("tampered")
    with pytest.raises(ValueError, match="checksum"):
        backup.prune(root, BUCKETS, 30)
    assert directory.exists()
    assert backup.object_path(root / "objects", manifest["objects"][0]).exists()


def test_retention_removes_old_manifest_and_only_aged_unreferenced_objects(tmp_path):
    root, old, manifest, _client, _ = setup_backup(
        tmp_path, timestamp="20260901T000000Z"
    )
    current = root / "snapshots" / "20261014T000000Z"
    backup.private_dir(current)
    retained = copy.deepcopy(manifest)
    retained["timestamp"] = "20261014T000000Z"
    retained["db_timestamp"] = "20261014T000000Z"
    retained["db_dump"] = "20261014T000000Z.dump"
    backup.publish(current, retained)
    path = backup.object_path(root / "objects", manifest["objects"][0])
    old_time = datetime(2026, 9, 1, tzinfo=UTC).timestamp()
    os.utime(path, (old_time, old_time))
    now = datetime(2026, 10, 14, tzinfo=UTC)
    backup.prune(root, BUCKETS, 30, now=now)
    assert not old.exists()
    assert path.exists()
    retained["objects"] = []
    backup.publish(current, retained)
    backup.prune(root, BUCKETS, 30, now=now)
    assert not path.exists()
    assert not (root / "objects" / BUCKETS["map"] / "map-atlas" / NOVEL).exists()


def test_symlink_mirror_cannot_escape_root(tmp_path):
    root, _directory, manifest, _, _ = setup_backup(tmp_path)
    path = backup.object_path(root / "objects", manifest["objects"][0])
    path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="Symlink"):
        backup.restore(ObjectClient({}), root / "objects", manifest)
    assert outside.read_bytes() == b"untouched"


def test_package_uses_same_manifest_and_rejects_extra_paths(tmp_path):
    import zipfile

    root, _directory, manifest, _, _ = setup_backup(tmp_path)
    package = tmp_path / "images.zip"
    with zipfile.ZipFile(package, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, str(path.relative_to(root)))
    package.chmod(0o600)
    target = tmp_path / "unpacked"
    backup.private_dir(target)
    assert backup.unpack_package(package, target, BUCKETS) == manifest["db_timestamp"]
    restored = backup.read_manifest(
        target / "snapshots" / manifest["db_timestamp"], BUCKETS
    )
    client = ObjectClient({})
    backup.restore(client, target / "objects", restored)
    assert len(client.objects) == 1
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("../../escape", b"bad")
    with pytest.raises(ValueError, match="unexpected"):
        backup.unpack_package(package, tmp_path / "rejected", BUCKETS)
    assert not (tmp_path / "escape").exists()


def test_author_export_does_not_claim_db_pair_and_requires_target_ownership(tmp_path):
    _root, directory, manifest, _, _ = setup_backup(tmp_path)
    manifest.update(
        source_kind="author_export", db_timestamp=None, db_sha256=None, db_dump=None
    )
    backup.publish(directory, manifest)
    checked = backup.read_manifest(directory, BUCKETS)
    backup.require_target_references(checked, [row()], BUCKETS)
    with pytest.raises(ValueError, match="target DB"):
        backup.require_target_references(checked, [], BUCKETS)
    manifest["db_sha256"] = "f" * 64
    backup.publish(directory, manifest)
    with pytest.raises(ValueError, match="must not claim"):
        backup.read_manifest(directory, BUCKETS)


@pytest.mark.parametrize(
    "filename", ("../escape.png", "/absolute", "images/../x", "a\\b", "a//b")
)
def test_package_relative_names_cannot_escape(filename):
    with pytest.raises(ValueError, match="relative filename"):
        backup.validate_row(row() | {"file": filename}, BUCKETS)


def test_incremental_cache_reloads_corrupt_local_file_and_detects_remote_deletion(
    tmp_path,
):
    root, directory, manifest, client, _ = setup_backup(tmp_path)
    trusted = {(r["bucket"], r["key"]): copy.deepcopy(r) for r in manifest["objects"]}
    path = backup.object_path(root / "objects", manifest["objects"][0])
    path.write_bytes(b"bad cache")
    before = client.reads
    assert backup.mirror(
        client, root / "objects", manifest["objects"], directory, manifest, trusted
    )
    assert client.reads == before + 1
    client.objects.clear()
    assert not backup.mirror(
        client, root / "objects", manifest["objects"], directory, manifest, trusted
    )
    assert manifest["status"] == "incomplete"
    assert manifest["objects"][0]["status"] == "missing"


def test_duplicate_db_references_collapse_but_conflicts_fail_closed():
    assert backup.unique_references([row(), row()]) == [row()]
    with pytest.raises(ValueError, match="Conflicting"):
        backup.unique_references([row(), row() | {"sha256": "0" * 64}])
