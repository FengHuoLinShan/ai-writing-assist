#!/usr/bin/env python3
"""G4b browser-package restore drill.

Restores a browser-produced author_export image package (real ZIP bytes built by
``frontend-console/scripts/generate-image-export-fixture.mjs`` with the exact
browser packing logic) through ``deploy/scripts/restore_objects.sh`` inside the
same isolated Linux container topology as the G4a drill: docker ``none``
network, synthetic MinIO/Postgres, compose shim, synthetic data only.

Usage: python3 deploy/tests/run_browser_export_restore_drill.py [--browser] [--keep]
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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


def synthetic_image(image_format: str, color: str) -> bytes:
    from PIL import Image

    output = io.BytesIO()
    Image.new("RGB", (16, 12), color).save(output, image_format)
    return output.getvalue()


def build_fixture(root: Path) -> tuple[list[dict], list[dict]]:
    """Host-side synthetic fixture: drill rows + browser spec items + bytes."""
    seed = root / "seed"
    seed.mkdir(mode=0o700)
    rows = []
    items = []
    colors = ("blue", "green", "red", "purple", "yellow", "orange", "pink")
    titles = ("主世界", "主世界", "🗺️ 精灵领地", "地" * 300 + "🐉", "ABC", "abc", "备选大陆")
    for index, (color, title) in enumerate(zip(colors, titles, strict=True), 1):
        page = f"44444444-4444-4444-8444-{index:012d}"
        payload = synthetic_image("PNG", color)
        name = f"page-{index}.png"
        (seed / name).write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        key = f"map-atlas/{NOVEL}/pages/{page}/image.png"
        rows.append(
            {
                "novel_id": NOVEL,
                "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
                "key": key,
                "category": "map_page",
                "sha256": digest,
                "byte_size": len(payload),
                "content_type": "image/png",
                "byte_file": f"seed/{name}",
                "page_id": page,
                "review_status": "adopted" if index % 2 else "rejected",
            }
        )
        # 浏览器清单端点口径：地图页行携带 DB 记录的 sha256/byte_size。
        items.append(
            {
                "novel_id": NOVEL,
                "category": "map_page",
                "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
                "key": key,
                "content_type": "image/png",
                "sha256": digest,
                "byte_size": len(payload),
                "page_id": page,
                "title": title,
                "bytes_file": str((seed / name).resolve()),
            }
        )
    mask_payload = synthetic_image("PNG", "gray")
    (seed / "mask.png").write_bytes(mask_payload)
    mask_key = f"map-atlas/{NOVEL}/pages/{rows[0]['page_id']}/mask.png"
    rows.append(
        {
            "novel_id": NOVEL,
            "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
            "key": mask_key,
            "category": "map_mask",
            "sha256": hashlib.sha256(mask_payload).hexdigest(),
            "byte_size": len(mask_payload),
            "content_type": "image/png",
            "byte_file": "seed/mask.png",
            "page_id": rows[0]["page_id"],
        }
    )
    items.append(
        {
            "novel_id": NOVEL,
            "category": "map_mask",
            "bucket": ENV["MAP_ATLAS_S3_BUCKET"],
            "key": mask_key,
            "content_type": "image/png",
            "sha256": None,
            "byte_size": None,
            "page_id": rows[0]["page_id"],
            "title": "主世界",
            "bytes_file": str((seed / "mask.png").resolve()),
        }
    )
    for variant, color in (("full", "teal"), ("thumbnail", "navy")):
        payload = synthetic_image("WEBP", color)
        name = f"entity-{variant}.webp"
        (seed / name).write_bytes(payload)
        key = f"world-objects/{NOVEL}/entities/{ENTITY}/images/{VERSION}/{variant}.webp"
        rows.append(
            {
                "novel_id": NOVEL,
                "bucket": ENV["WORLD_OBJECT_S3_BUCKET"],
                "key": key,
                "category": f"world_{variant}",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "byte_size": len(payload),
                "content_type": "image/webp",
                "byte_file": f"seed/{name}",
            }
        )
        items.append(
            {
                "novel_id": NOVEL,
                "category": f"world_{variant}",
                "bucket": ENV["WORLD_OBJECT_S3_BUCKET"],
                "key": key,
                "content_type": "image/webp",
                "sha256": None,
                "byte_size": None,
                "entity_id": ENTITY,
                "image_version": VERSION,
                "title": "主角·林绪",
                "bytes_file": str((seed / name).resolve()),
            }
        )
    return rows, items


def runtime(phase: str, path: Path):
    """Container-side phases (seed / wipe / check) against the drill MinIO."""
    spec = importlib.util.spec_from_file_location(
        "object_backup", ROOT / "deploy/scripts/object_backup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = module.s3_client(backup=False)
    fixture = json.loads((path / "fixture.json").read_text())
    if phase == "seed":
        for row in fixture:
            app.put_object(
                Bucket=row["bucket"],
                Key=row["key"],
                Body=(path / row["byte_file"]).read_bytes(),
                ContentType=row["content_type"],
                Metadata={"synthetic": "true"},
            )
        return
    if phase == "wipe":
        for row in fixture:
            app.delete_object(Bucket=row["bucket"], Key=row["key"])
        return
    if phase == "check":
        matched = []
        for row in fixture:
            response = app.get_object(Bucket=row["bucket"], Key=row["key"])
            body = response["Body"].read()
            assert hashlib.sha256(body).hexdigest() == row["sha256"], row["key"]
            assert len(body) == row["byte_size"], row["key"]
            assert response["ContentType"] == row["content_type"], row["key"]
            matched.append(row["key"])
        print(json.dumps({"objects": len(matched), "matched": matched}))
        return
    raise SystemExit(f"unknown phase: {phase}")


def host() -> None:
    from PIL import Image  # Verify the host interpreter before building fixtures.

    assert Image
    os.umask(0o077)
    frontend = ROOT / "frontend-console"
    node = shutil.which("node")
    assert node, "node is required to build the browser package"
    assert (frontend / "node_modules/fflate").is_dir(), (
        "frontend-console node_modules missing; run npm ci first"
    )
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
    containers: list[str] = []
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
    keep = "--keep" in sys.argv
    with tempfile.TemporaryDirectory(
        prefix="audit-g4b-browser-drill-", ignore_cleanup_errors=keep
    ) as temporary:
        path = Path(temporary).resolve()
        root = path / "backup"
        root.mkdir(mode=0o700)

        # 1) 浏览器产物：与线上完全相同的打包逻辑生成真实 ZIP。
        rows, items = build_fixture(root)
        (root / "fixture.json").write_text(json.dumps(rows))
        browser_dir = root / "browser-package"
        browser_dir.mkdir(mode=0o700)
        spec_path = root / "browser-spec.json"
        spec_path.write_text(json.dumps({"items": items, "expect_failures": 0}))
        generator = (
            [node, "scripts/verify-image-export-browser.mjs", str(spec_path), str(browser_dir)]
            if "--browser" in sys.argv
            else [node, "scripts/generate-image-export-fixture.mjs", "--from", str(spec_path), str(browser_dir)]
        )
        generated = command(*generator, cwd=frontend)
        summary = json.loads(generated)
        assert summary["failures"] == 0, summary
        packages = sorted(browser_dir.glob("package-*.zip"))
        assert len(packages) == len(summary["packages"]) == 1, summary
        for package in packages:
            package.chmod(0o600)

        def create(name: str, *args: str) -> str:
            labels = (
                [
                    "--label",
                    f"com.docker.compose.project=audit-g4b-browser-{suffix}",
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
                    f"audit-g4b-{name}-{suffix}",
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

        def initialize(container: str) -> None:
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

        def runtime_command(container: str, *args: str):
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
                "/source/deploy/tests/run_browser_export_restore_drill.py",
                "seed",
                "/backup",
            )
            sql = (
                "CREATE TABLE map_atlas_pages (novel_id uuid, id uuid, object_key text,"
                " mask_object_key text, sha256 text, byte_size bigint, review_status text);"
                " CREATE TABLE core_entities (novel_id uuid, id uuid, image_version uuid);"
            )
            for row in [item for item in rows if item["category"] == "map_page"]:
                mask = (
                    f"'{next(item['key'] for item in rows if item['category'] == 'map_mask')}'"
                    if row is rows[0]
                    else "NULL"
                )
                sql += (
                    f"INSERT INTO map_atlas_pages VALUES ('{NOVEL}', '{row['page_id']}',"
                    f" '{row['key']}', {mask}, '{row['sha256']}', {row['byte_size']},"
                    f" '{row['review_status']}');"
                )
            sql += (
                f"INSERT INTO core_entities VALUES ('{NOVEL}', '{ENTITY}', '{VERSION}');"
            )
            command("docker", "exec", database, "createdb", "-U", "fixture", "snapshot")
            command(
                "docker",
                "exec",
                database,
                "psql",
                "-U",
                "fixture",
                "-d",
                "snapshot",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            )
            # 模拟对象丢失：恢复前清空源桶。
            runtime_command(
                source,
                "/source/deploy/tests/run_browser_export_restore_drill.py",
                "wipe",
                "/backup",
            )

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
                "git", "-C", str(path), "config", "user.name", "Browser Export Drill"
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
                    {"name": f"audit-g4b-browser-{suffix}", "services": services}
                )
            )
            output = command(
                "bash",
                str(deploy / "scripts/restore_objects.sh"),
                str(packages[0]),
                env=os.environ | {"ENV_FILE": str(env_file)},
            )
            assert f"Object restore complete: objects={len(rows)}".encode() in output, output
            print(output.decode().strip())
            reconciliation = json.loads(
                runtime_command(
                    source,
                    "/source/deploy/tests/run_browser_export_restore_drill.py",
                    "check",
                    "/backup",
                )
            )
            assert reconciliation["objects"] == len(rows), reconciliation
            assert not list(backup_dir.glob(".object-restore.*"))
            assert not list(backup_dir.glob(".restore-object-references.*"))
            print(
                json.dumps(
                    {
                        "result": "complete",
                        "package": packages[0].name,
                        "package_mode": "0600",
                        "objects": len(rows),
                        "restore_entry": "restore_objects.sh <browser zip>",
                        "reconciled": reconciliation["objects"],
                        "unicode_duplicate_names": ["主世界", "主世界-2"],
                    },
                    sort_keys=True,
                )
            )
        finally:
            if not keep:
                for container in reversed(containers):
                    subprocess.run(
                        ["docker", "rm", "-fv", container],
                        check=True,
                        stdout=subprocess.DEVNULL,
                    )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in {"seed", "wipe", "check"}:
        ROOT = Path("/source")
        runtime(sys.argv[1], Path(sys.argv[2]))
    else:
        host()
