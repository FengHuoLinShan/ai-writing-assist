#!/usr/bin/env python3
"""Real PostgreSQL + S3 restore drill, isolated namespaces and synthetic PNG/WebP only."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NOVEL = "11111111-1111-4111-8111-111111111111"
ENTITY = "22222222-2222-4222-8222-222222222222"
VERSION = "33333333-3333-4333-8333-333333333333"
ENV = {
    "MINIO_ROOT_USER": "synthetic-root",
    "MINIO_ROOT_PASSWORD": "synthetic-root-password",
    "MINIO_APP_ACCESS_KEY": "synthetic-app",
    "MINIO_APP_SECRET_KEY": "synthetic-app-password",
    "MINIO_BACKUP_ACCESS_KEY": "synthetic-backup",
    "MINIO_BACKUP_SECRET_KEY": "synthetic-backup-password",
    "MAP_ATLAS_S3_ACCESS_KEY_ID": "synthetic-app",
    "MAP_ATLAS_S3_SECRET_ACCESS_KEY": "synthetic-app-password",
    "MAP_ATLAS_S3_ENDPOINT_URL": "http://127.0.0.1:9000",
    "MINIO_ENDPOINT_URL": "http://127.0.0.1:9000",
    "MAP_ATLAS_S3_BUCKET": "synthetic-maps",
    "WORLD_OBJECT_S3_BUCKET": "synthetic-world",
    "MC_CONFIG_DIR": "/tmp/mc",
}


def image_bytes(format):
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (16, 12), "blue").save(output, format)
    return output.getvalue()


def rows():
    rows = []
    for i, state in enumerate(("candidate", "adopted", "rejected", "deprecated"), 1):
        page = f"44444444-4444-4444-8444-{i:012d}"
        payload = image_bytes("PNG")
        rows.append(
            {
                "novel_id": NOVEL,
                "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
                "key": f"map-atlas/{NOVEL}/pages/{page}/image.png",
                "category": "map_page",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byte_size": len(payload),
                "page_id": page,
                "review_status": state,
            }
        )
    rows.append(
        {
            "novel_id": NOVEL,
            "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
            "key": f"map-atlas/{NOVEL}/pages/{rows[0]['page_id']}/mask.png",
            "category": "map_mask",
            "sha256": None,
            "byte_size": None,
        }
    )
    for variant in ("full", "thumbnail"):
        rows.append(
            {
                "novel_id": NOVEL,
                "bucket": ENV["WORLD_OBJECT_S3_BUCKET"],
                "key": f"world-objects/{NOVEL}/entities/{ENTITY}/images/{VERSION}/{variant}.webp",
                "category": f"world_{variant}",
                "sha256": None,
                "byte_size": None,
            }
        )
    return rows


def runtime(phase, path):
    spec = importlib.util.spec_from_file_location(
        "object_backup", ROOT / "deploy/scripts/object_backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.s3_client(backup=False)
    readonly = module.s3_client(backup=True)
    buckets = {
        "map": ENV["MAP_ATLAS_S3_BUCKET"],
        "world": ENV["WORLD_OBJECT_S3_BUCKET"],
    }
    if phase == "seed":
        fixture = rows()
        for row in fixture:
            app.put_object(
                Bucket=row["bucket"],
                Key=row["key"],
                Body=image_bytes("PNG" if row["category"].startswith("map_") else "WEBP"),
                ContentType="image/png"
                if row["category"].startswith("map_")
                else "image/webp",
                Metadata={"synthetic": "true"},
            )
        (path / "fixture.json").write_text(json.dumps(fixture))
        return
    if phase == "author":
        import copy
        import zipfile

        snapshot = next(path.glob("snapshots/*/manifest.json")).parent
        manifest = module.read_manifest(snapshot, buckets)
        manifest = copy.deepcopy(manifest)
        manifest.update(
            source_kind="author_export", db_timestamp=None, db_sha256=None, db_dump=None
        )
        package = path / "作者图片包.zip"
        for index, row in enumerate(manifest["objects"], 1):
            suffix = ".png" if row["category"].startswith("map_") else ".webp"
            row["file"] = f"作者图片/图片{index}{suffix}"
        payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode()
        with zipfile.ZipFile(package, "w") as archive:
            prefix = f"snapshots/{manifest['timestamp']}/"
            archive.writestr(prefix + "manifest.json", payload)
            archive.writestr(
                prefix + "manifest.sha256", hashlib.sha256(payload).hexdigest() + "\n"
            )
            for row in manifest["objects"]:
                original = row.copy()
                original.pop("file")
                archive.write(
                    module.object_path(path / "objects", original),
                    "objects/" + row["file"],
                )
        package.chmod(0o600)
        imported = path / "author-import"
        module.private_dir(imported)
        timestamp = module.unpack_package(package, imported, buckets)
        checked = module.read_manifest(imported / "snapshots" / timestamp, buckets)
        module.require_target_references(
            checked, json.loads((path / "references.json").read_text()), buckets
        )
        for row in checked["objects"]:
            app.delete_object(Bucket=row["bucket"], Key=row["key"])
        print(
            json.dumps(
                {
                    "source_kind": "author_export",
                    "db_pair": None,
                    "objects": len(checked["objects"]),
                    "unicode_package_names": True,
                    "target_db_references": "matched",
                    "result": "prepared",
                }
            )
        )
        return
    if phase == "permissions":
        from botocore.exceptions import ClientError

        for bucket in buckets.values():
            readonly.list_objects_v2(Bucket=bucket)
            assert app.get_bucket_location(Bucket=bucket)
        reference = rows()[0]
        readonly.get_object(Bucket=reference["bucket"], Key=reference["key"])[
            "Body"
        ].close()
        denied = [
            lambda: readonly.put_object(
                Bucket=reference["bucket"], Key=reference["key"], Body=b"x"
            ),
            lambda: readonly.delete_object(
                Bucket=reference["bucket"], Key=reference["key"]
            ),
            lambda: readonly.create_bucket(Bucket="synthetic-unauthorized"),
            lambda: readonly.put_bucket_policy(Bucket=reference["bucket"], Policy="{}"),
        ]
        for action in denied:
            try:
                action()
            except ClientError as exc:
                assert exc.response["Error"]["Code"] in {
                    "AccessDenied",
                    "AllAccessDisabled",
                }
            else:
                raise AssertionError("backup identity unexpectedly mutated storage")
        return
    if phase == "delete":
        for row in rows():
            app.delete_object(Bucket=row["bucket"], Key=row["key"])
        return
    if phase in {"missing", "interrupted"}:
        references = json.loads((path / "references.json").read_text())
        directory = (
            path
            / "snapshots"
            / ("20990101T000000Z" if phase == "missing" else "20990101T000001Z")
        )
        module.private_dir(directory)
        client = readonly
        if phase == "interrupted":

            class InterruptedBody:
                def __init__(self, body):
                    self.body = body
                    self.reads = 0

                def read(self, size):
                    if self.reads:
                        raise OSError("synthetic interruption after real S3 bytes")
                    self.reads += 1
                    return self.body.read(8)

                def close(self):
                    self.body.close()

            class InterruptedClient:
                def get_object(self, **kwargs):
                    response = readonly.get_object(**kwargs)
                    response["Body"] = InterruptedBody(response["Body"])
                    return response

            client = InterruptedClient()
        manifest = {
            "schema": module.SCHEMA,
            "source_kind": "server_snapshot",
            "timestamp": directory.name,
            "db_timestamp": directory.name,
            "db_sha256": "f" * 64,
            "db_dump": f"{directory.name}.dump",
        }
        assert not module.mirror(
            client, path / "objects", references, directory, manifest
        )
        assert manifest["status"] == "incomplete"
        if phase == "missing":
            # Every deleted object is reported; one loss must not stop later copies.
            assert all(row["status"] == "missing" for row in references)
        else:
            assert any(row["status"] == "failed" for row in references)
        try:
            module.read_manifest(directory, buckets)
        except ValueError:
            pass
        else:
            raise AssertionError("incomplete backup accepted for restore")
        print(f"Negative control passed: {phase}=incomplete")
        return
    raise ValueError("unknown runtime phase")


def snapshot_volume_drill():
    """Exercise the production anonymous-volume PG mode, including restore failure cleanup."""
    image = os.environ.get(
        "OBJECT_DRILL_POSTGRES_IMAGE",
        "sha256:306e00ca129081f4a69081c09ff0bdf0ef5169779019200a5c22ce9e0c6148f3",
    )

    def command(*args, **kwargs):
        return subprocess.run(
            list(args), check=True, capture_output=True, **kwargs
        ).stdout

    command("docker", "image", "inspect", image)
    for failure in (False, True):
        container = (
            command(
                "docker",
                "create",
                "--name",
                f"audit-g4a-snapshot-volume-{os.getpid()}-{int(failure)}",
                "--pull",
                "never",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "999:999",
                "--volume",
                "/var/lib/postgresql/data",
                "--tmpfs",
                "/var/run/postgresql:rw,nosuid,nodev,size=16m,uid=999,gid=999,mode=0775",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m,uid=999,gid=999,mode=1777",
                "--cpus",
                "1",
                "--memory",
                "2g",
                "--memory-swap",
                "2g",
                "--pids-limit",
                "128",
                "-e",
                "PGDATA=/var/lib/postgresql/data/pgdata",
                "-e",
                "POSTGRES_USER=fixture",
                "-e",
                "POSTGRES_DB=fixture",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                image,
            )
            .decode()
            .strip()
        )
        volume = None
        try:
            details = json.loads(command("docker", "inspect", container))[0]
            mounts = [
                item
                for item in details["Mounts"]
                if item["Destination"] == "/var/lib/postgresql/data"
            ]
            assert len(mounts) == 1 and mounts[0]["Type"] == "volume"
            volume = mounts[0]["Name"]
            assert details["HostConfig"]["NetworkMode"] == "none"
            assert details["HostConfig"]["ReadonlyRootfs"] is True
            command("docker", "start", container)
            for attempt in range(30):
                ready = subprocess.run(
                    ["docker", "exec", container, "pg_isready", "-U", "fixture"],
                    check=False,
                    capture_output=True,
                )
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("anonymous-volume snapshot PG did not start")
            permission = (
                command(
                    "docker",
                    "exec",
                    container,
                    "stat",
                    "-c",
                    "%a:%u:%g",
                    "/var/lib/postgresql/data/pgdata",
                )
                .decode()
                .strip()
            )
            assert permission == "700:999:999", permission
            fixture = rows()[0]
            sql = (
                "CREATE TABLE map_atlas_pages (novel_id uuid, object_key text, mask_object_key text, sha256 text, byte_size bigint);"
                "CREATE TABLE core_entities (novel_id uuid, id uuid, image_version uuid);"
                "CREATE TABLE image_reuse_probe (payload bytea); INSERT INTO image_reuse_probe VALUES (decode(repeat('ab',8192),'hex'));"
                f"INSERT INTO map_atlas_pages VALUES ('{NOVEL}', '{fixture['key']}', NULL, '{fixture['sha256']}', {fixture['byte_size']});"
                f"INSERT INTO core_entities VALUES ('{NOVEL}', '{ENTITY}', '{VERSION}');"
            )
            command(
                "docker",
                "exec",
                container,
                "psql",
                "-U",
                "fixture",
                "-d",
                "fixture",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            )
            dump = command(
                "docker",
                "exec",
                container,
                "pg_dump",
                "-U",
                "fixture",
                "-d",
                "fixture",
                "-Fc",
            )
            command("docker", "exec", container, "createdb", "-U", "fixture", "snapshot")
            restore = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "pg_restore",
                    "-U",
                    "fixture",
                    "-d",
                    "snapshot",
                    "--exit-on-error",
                ],
                input=b"deliberately invalid archive" if failure else dump,
                check=False,
                capture_output=True,
            )
            if failure:
                assert restore.returncode != 0
            else:
                assert restore.returncode == 0, restore.stderr.decode()
                references = command(
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-U",
                    "fixture",
                    "-d",
                    "snapshot",
                    "-At",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-v",
                    f"map_bucket={ENV['MAP_ATLAS_S3_BUCKET']}",
                    "-v",
                    f"world_bucket={ENV['WORLD_OBJECT_S3_BUCKET']}",
                    input=(ROOT / "deploy/scripts/object_references.sql").read_bytes(),
                )
                assert len(json.loads(references)) == 3
                assert (
                    command(
                        "docker",
                        "exec",
                        container,
                        "psql",
                        "-U",
                        "fixture",
                        "-d",
                        "snapshot",
                        "-Atc",
                        "SELECT octet_length(payload) FROM image_reuse_probe",
                    ).strip()
                    == b"8192"
                )
        finally:
            command("docker", "rm", "-fv", container)
            if volume:
                removed = subprocess.run(
                    ["docker", "volume", "inspect", volume],
                    check=False,
                    capture_output=True,
                )
                assert removed.returncode != 0, (
                    "snapshot anonymous volume was not removed"
                )
        print(
            json.dumps(
                {
                    "data_mount": "fresh_anonymous_volume",
                    "pgdata_mode": "0700",
                    "pgdata_owner": "999:999",
                    "network": "none",
                    "fixed_data_size_cap": None,
                    "restore_case": "failure" if failure else "success",
                    "container_and_volume_cleanup": "passed",
                    "result": "complete",
                }
            )
        )


def host():
    from PIL import (
        Image,  # Verify the selected locked interpreter before creating containers.
    )

    assert Image
    os.umask(0o077)
    pg = os.environ.get(
        "OBJECT_DRILL_POSTGRES_IMAGE",
        "sha256:306e00ca129081f4a69081c09ff0bdf0ef5169779019200a5c22ce9e0c6148f3",
    )
    minio = os.environ.get(
        "OBJECT_DRILL_MINIO_IMAGE",
        "sha256:6c83c74c8028019d82d3f20d65cc6645fd5694b82a25dc38733df5227ffa4e8d",
    )
    mc = os.environ.get(
        "OBJECT_DRILL_MC_IMAGE",
        "sha256:217e9b4dd8bcde3a98211a8883824cfa3842b296397ceea876cda2dfb116046c",
    )
    runtime_image = os.environ.get(
        "OBJECT_DRILL_RUNTIME_IMAGE", "audit-g4a-runtime:locked"
    )
    containers = []
    suffix = str(os.getpid())

    def command(*args, **kwargs):
        result = subprocess.run(list(args), check=False, capture_output=True, **kwargs)
        if result.returncode:
            # This runner owns only synthetic credentials and data.
            raise RuntimeError(
                result.stderr.decode(errors="replace")
                + result.stdout.decode(errors="replace")
            )
        return result.stdout

    for image in (pg, minio, mc, runtime_image):
        command("docker", "image", "inspect", image)
    with tempfile.TemporaryDirectory(prefix="audit-g4a-object-drill-") as temporary:
        path = Path(temporary).resolve()
        root = path / "backup"
        root.mkdir(mode=0o700)

        def create(name, *args):
            labels = (
                [
                    "--label",
                    f"com.docker.compose.project=audit-g4a-shell-{suffix}",
                    "--label",
                    "com.docker.compose.service=postgres",
                    "--label",
                    "com.docker.compose.config-hash=synthetic",
                    "--label",
                    "com.docker.compose.oneoff=False",
                    "--label",
                    "com.docker.compose.container-number=1",
                ]
                if name == "pg"
                else []
            )

            container = (
                command(
                    "docker",
                    "create",
                    "--name",
                    f"audit-g4a-{name}-{suffix}",
                    "--pull",
                    "never",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--cpus",
                    "1",
                    "--memory",
                    "1g",
                    "--pids-limit",
                    "128",
                    *labels,
                    *args,
                )
                .decode()
                .strip()
            )
            containers.append(container)
            command("docker", "start", container)
            return container

        def initialize(container):
            command(
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                f"container:{container}",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:mode=1777",
                "-v",
                f"{ROOT}/docker/init-minio.sh:/init.sh:ro",
                *[
                    item
                    for key, value in ENV.items()
                    for item in ("-e", f"{key}={value}")
                ],
                "--entrypoint",
                "/bin/sh",
                mc,
                "/init.sh",
            )

        def runtime_command(container, *args):
            return command(
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                f"container:{container}",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--tmpfs",
                "/tmp:mode=1777",
                "-v",
                f"{ROOT}:/source:ro",
                "-v",
                f"{root}:/backup",
                *[
                    item
                    for key, value in ENV.items()
                    for item in ("-e", f"{key}={value}")
                ],
                "--entrypoint",
                "python",
                runtime_image,
                *args,
            )

        try:
            source = create(
                "source-minio",
                "--user",
                "1000:1000",
                "--tmpfs",
                "/data:rw,uid=1000,gid=1000,mode=0700,size=128m",
                "--tmpfs",
                "/tmp:mode=1777",
                "-e",
                "MINIO_ROOT_USER=synthetic-root",
                "-e",
                "MINIO_ROOT_PASSWORD=synthetic-root-password",
                minio,
                "server",
                "/data",
            )
            database = create(
                "pg",
                "--user",
                "999:999",
                "--volume",
                "/var/lib/postgresql/data",
                "--tmpfs",
                "/var/run/postgresql:rw,uid=999,gid=999,mode=0775",
                "--tmpfs",
                "/tmp:mode=1777",
                "-e",
                "PGDATA=/var/lib/postgresql/data/pgdata",
                "-e",
                "POSTGRES_USER=fixture",
                "-e",
                "POSTGRES_DB=fixture",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                pg,
            )
            for attempt in range(30):
                try:
                    command("docker", "exec", database, "pg_isready", "-U", "fixture")
                    initialize(source)
                    break
                except RuntimeError:
                    time.sleep(1)
            else:
                raise RuntimeError("isolated services not ready")
            runtime_command(
                source,
                "/source/deploy/tests/run_object_restore_drill.py",
                "seed",
                "/backup",
            )
            runtime_command(
                source,
                "/source/deploy/tests/run_object_restore_drill.py",
                "permissions",
                "/backup",
            )
            fixture = json.loads((root / "fixture.json").read_text())
            sql = "CREATE TABLE map_atlas_pages (novel_id uuid, id uuid, object_key text, mask_object_key text, sha256 text, byte_size bigint, review_status text); CREATE TABLE core_entities (novel_id uuid, id uuid, image_version uuid);"
            for row in fixture[:4]:
                mask = "'" + fixture[4]["key"] + "'" if row is fixture[0] else "NULL"
                sql += f"INSERT INTO map_atlas_pages VALUES ('{NOVEL}', '{row['page_id']}', '{row['key']}', {mask}, '{row['sha256']}', {row['byte_size']}, '{row['review_status']}');"
            sql += (
                f"INSERT INTO core_entities VALUES ('{NOVEL}', '{ENTITY}', '{VERSION}');"
            )
            command(
                "docker",
                "exec",
                database,
                "psql",
                "-U",
                "fixture",
                "-d",
                "fixture",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            )
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dump = command(
                "docker",
                "exec",
                database,
                "pg_dump",
                "-U",
                "fixture",
                "-d",
                "fixture",
                "-Fc",
            )
            digest = hashlib.sha256(dump).hexdigest()
            (root / f"{timestamp}.dump").write_bytes(dump)
            command(
                "docker",
                "exec",
                database,
                "psql",
                "-U",
                "fixture",
                "-d",
                "fixture",
                "-c",
                "DELETE FROM map_atlas_pages; DELETE FROM core_entities;",
            )
            command("docker", "exec", database, "createdb", "-U", "fixture", "snapshot")
            command(
                "docker",
                "exec",
                "-i",
                database,
                "pg_restore",
                "-U",
                "fixture",
                "-d",
                "snapshot",
                "--exit-on-error",
                input=dump,
            )
            references = command(
                "docker",
                "exec",
                "-i",
                database,
                "psql",
                "-U",
                "fixture",
                "-d",
                "snapshot",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "-v",
                f"map_bucket={ENV['MAP_ATLAS_S3_BUCKET']}",
                "-v",
                f"world_bucket={ENV['WORLD_OBJECT_S3_BUCKET']}",
                input=(ROOT / "deploy/scripts/object_references.sql").read_bytes(),
            )
            assert len(json.loads(references)) == 7
            (root / "references.json").write_bytes(references)
            print(
                runtime_command(
                    source,
                    "/source/deploy/scripts/object_backup.py",
                    "backup",
                    "/backup",
                    "--references",
                    "/backup/references.json",
                    "--timestamp",
                    timestamp,
                    "--db-sha256",
                    digest,
                )
                .decode()
                .strip()
            )
            if "--author-only" in sys.argv:
                print(
                    runtime_command(
                        source,
                        "/source/deploy/tests/run_object_restore_drill.py",
                        "author",
                        "/backup",
                    )
                    .decode()
                    .strip()
                )
                import shutil

                deploy = path / "deploy"
                deploy.mkdir(mode=0o700)
                shutil.copytree(ROOT / "deploy/scripts", deploy / "scripts")
                backup_dir = deploy / "backups"
                backup_dir.mkdir(mode=0o700)
                values = {}
                for line in (
                    (ROOT / "deploy/tests/fixtures/closed-test.env")
                    .read_text()
                    .splitlines()
                ):
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        values[key] = value
                values.update(
                    {
                        "POSTGRES_USER": "fixture",
                        "POSTGRES_DB": "snapshot",
                        "MAP_ATLAS_S3_BUCKET": ENV["MAP_ATLAS_S3_BUCKET"],
                        "WORLD_OBJECT_S3_BUCKET": ENV["WORLD_OBJECT_S3_BUCKET"],
                    }
                )
                env_file = deploy / ".env.production"
                env_file.write_text(
                    "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
                )
                env_file.chmod(0o600)
                command("git", "init", "-q", str(path))
                command(
                    "git", "-C", str(path), "config", "user.email", "drill@example.com"
                )
                command(
                    "git", "-C", str(path), "config", "user.name", "Object Restore Drill"
                )
                command("git", "-C", str(path), "add", "deploy/scripts")
                command("git", "-C", str(path), "commit", "-qm", "synthetic release")
                release_commit = (
                    command("git", "-C", str(path), "rev-parse", "HEAD").decode().strip()
                )
                command(
                    "git",
                    "-C",
                    str(path),
                    "update-ref",
                    "refs/remotes/origin/main",
                    release_commit,
                )
                release_backup = backup_dir / "synthetic-release.dump"
                release_backup.write_bytes(b"synthetic deployment state backup")
                command(
                    sys.executable,
                    str(deploy / "scripts/deployment_state.py"),
                    "write",
                    str(deploy / ".state"),
                    str(path),
                    "a" * 32,
                    "release",
                    release_commit,
                    release_commit,
                    str(release_backup),
                )
                runtime_service = {
                    "image": runtime_image,
                    "entrypoint": ["python", "/ops/object_backup.py"],
                    "network_mode": f"container:{source}",
                    "environment": ENV,
                    "read_only": True,
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "tmpfs": ["/tmp:mode=1777"],
                }
                services = {
                    "postgres": {"image": pg, "network_mode": "none"},
                    "object-backup": runtime_service
                    | {
                        "volumes": [
                            f"{ROOT}/deploy/scripts/object_backup.py:/ops/object_backup.py:ro",
                            f"{root}:/backup",
                        ]
                    },
                    "object-restore": runtime_service
                    | {
                        "volumes": [
                            f"{ROOT}/deploy/scripts/object_backup.py:/ops/object_backup.py:ro",
                            f"${{OBJECT_RESTORE_DIR:-{root}}}:/backup:ro",
                        ]
                    },
                    "minio-init": {
                        "image": mc,
                        "entrypoint": ["/bin/sh", "/init.sh"],
                        "network_mode": f"container:{source}",
                        "environment": ENV,
                        "volumes": [f"{ROOT}/docker/init-minio.sh:/init.sh:ro"],
                        "tmpfs": ["/tmp:mode=1777"],
                    },
                }
                (deploy / "compose.production.yml").write_text(
                    json.dumps(
                        {"name": f"audit-g4a-shell-{suffix}", "services": services}
                    )
                )
                output = command(
                    "bash",
                    str(deploy / "scripts/restore_objects.sh"),
                    str(root / "作者图片包.zip"),
                    env=os.environ | {"ENV_FILE": str(env_file)},
                )
                assert b"Object restore complete: objects=7" in output
                print(output.decode().strip())
                assert not list(backup_dir.glob(".object-restore.*"))
                assert not list(backup_dir.glob(".restore-object-references.*"))
                print(
                    json.dumps(
                        {
                            "source_kind": "author_export",
                            "db_pair": None,
                            "objects": 7,
                            "unicode_package_names": True,
                            "target_db_references": "matched",
                            "shell_entry": "restore_objects.sh ZIP",
                            "result": "complete",
                        }
                    )
                )
                return
            rpo = (
                time.time()
                - datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=UTC)
                .timestamp()
            )
            print(
                runtime_command(
                    source,
                    "/source/deploy/tests/run_object_restore_drill.py",
                    "interrupted",
                    "/backup",
                )
                .decode()
                .strip()
            )
            runtime_command(
                source,
                "/source/deploy/tests/run_object_restore_drill.py",
                "delete",
                "/backup",
            )
            print(
                runtime_command(
                    source,
                    "/source/deploy/tests/run_object_restore_drill.py",
                    "missing",
                    "/backup",
                )
                .decode()
                .strip()
            )
            started = time.monotonic()
            target = create(
                "target-minio",
                "--user",
                "1000:1000",
                "--tmpfs",
                "/data:rw,uid=1000,gid=1000,mode=0700,size=128m",
                "--tmpfs",
                "/tmp:mode=1777",
                "-e",
                "MINIO_ROOT_USER=synthetic-root",
                "-e",
                "MINIO_ROOT_PASSWORD=synthetic-root-password",
                minio,
                "server",
                "/data",
            )
            for attempt in range(30):
                try:
                    initialize(target)
                    break
                except RuntimeError:
                    time.sleep(1)
            else:
                raise RuntimeError("restore bucket initializer failed")
            print(
                runtime_command(
                    target,
                    "/source/deploy/scripts/object_backup.py",
                    "restore",
                    "/backup",
                    "--snapshot",
                    f"/backup/snapshots/{timestamp}",
                    "--target-references",
                    "/backup/references.json",
                )
                .decode()
                .strip()
            )
            runtime_command(
                target,
                "/source/deploy/tests/run_object_restore_drill.py",
                "permissions",
                "/backup",
            )
            metadata = command(
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                f"container:{target}",
                "--tmpfs",
                "/tmp:mode=1777",
                "--entrypoint",
                "/bin/sh",
                mc,
                "-ec",
                "mc alias set local http://127.0.0.1:9000 synthetic-root synthetic-root-password >/dev/null; "
                "for bucket in synthetic-maps synthetic-world; do mc version info --json local/$bucket; mc quota info --json local/$bucket; mc anonymous get --json local/$bucket; done",
            ).decode()
            records = [json.loads(line) for line in metadata.splitlines()]
            assert (
                sum(
                    item.get("versioning", {}).get("status") == "Enabled"
                    for item in records
                )
                == 2
            ), metadata
            assert sorted(item["quota"] for item in records if "quota" in item) == [
                8 * 1024**3,
                24 * 1024**3,
            ], metadata
            assert sum(item.get("permission") == "private" for item in records) == 2, (
                metadata
            )
            assert (
                hashlib.sha256((root / f"{timestamp}.dump").read_bytes()).hexdigest()
                == digest
            )
            report = {
                "result": "complete",
                "objects": 7,
                "buckets": 2,
                "isolated_network": "none",
                "db_sha256": digest,
                "measured_rpo_seconds": round(rpo, 3),
                "measured_rto_seconds": round(time.monotonic() - started, 3),
                "controls": [
                    "snapshot_after_live_delete",
                    "missing_object_incomplete",
                    "interrupted_stream_incomplete",
                    "read_only_backup_identity",
                    "private_versioned_quotas",
                    "sha256_size_decode_metadata",
                ],
            }
            print(json.dumps(report, sort_keys=True))
        except Exception:
            for manifest_path in root.glob("snapshots/*/manifest.json"):
                print(manifest_path.read_text())
            raise
        finally:
            for container in reversed(containers):
                subprocess.run(
                    ["docker", "rm", "-fv", container],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    if sys.argv[1:] == ["--snapshot-volume-only"]:
        snapshot_volume_drill()
    elif len(sys.argv) == 3 and sys.argv[1] != "--author-only":
        ROOT = Path("/source")
        runtime(sys.argv[1], Path(sys.argv[2]))
    else:
        host()
