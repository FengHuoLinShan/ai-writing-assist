"""Synthetic install/restart checks against a fresh, disposable desktop directory."""

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx
import psycopg2
from infrastructure.os_security import private_directory

ROOT = Path(__file__).resolve().parents[1]


def startup_progress(directory):
    """Report waits in this synthetic database without exposing its credentials."""
    try:
        port = (directory / "database/postmaster.pid").read_text().splitlines()[3]
        saved = json.loads((directory / "secrets.json").read_text())
        with closing(psycopg2.connect(
            host="127.0.0.1", port=port, user="novelcraft", dbname="novelcraft",
            password=saved["database_password"], connect_timeout=2,
        )) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT state, wait_event_type, wait_event, left(query, 140) "
                "FROM pg_stat_activity WHERE datname='novelcraft' "
                "AND pid <> pg_backend_pid() AND backend_type='client backend'"
            )
            print("Synthetic startup progress:", cursor.fetchall(), flush=True)
    except (OSError, ValueError, IndexError, psycopg2.Error):
        pass  # The server may still be starting; the main startup deadline applies.


def launch(command, directory):
    log = (directory / "smoke-supervisor.log").open("ab")
    process = subprocess.Popen(
        [*command, "--role", "supervisor"],
        env={**os.environ, "NOVELCRAFT_DESKTOP_DATA_DIR": str(directory)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
    )
    result = queue.Queue()
    threading.Thread(
        target=lambda: result.put(process.stdout.readline()), daemon=True
    ).start()
    try:
        deadline = time.monotonic() + 900
        while True:
            try:
                remaining = max(0, deadline - time.monotonic())
                row = json.loads(result.get(timeout=min(30, remaining)))
                break
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise
                startup_progress(directory)
        url = row["url"]
        origin = url.split("/_desktop/")[0]
        client = httpx.Client(base_url=origin, timeout=30, trust_env=False)
        assert client.get("/api/projects").status_code == 401
        assert client.get(url).status_code == 303
        assert client.get("/").status_code == 200
        return process, client, log
    except BaseException:
        process.stdin.close()
        process.wait(timeout=180)
        log.close()
        raise


def stop(process, client, log):
    client.close()
    process.stdin.close()
    process.wait(timeout=180)
    log.close()
    assert process.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--frozen", action="store_true")
    target.add_argument("--installed", type=Path, help="Installed app/bundle directory")
    args = parser.parse_args()
    installation = None
    relative = (
        "Contents/MacOS/NovelCraftRuntime"
        if sys.platform == "darwin" else "NovelCraftRuntime.exe"
    )
    if args.installed:
        command = [str(args.installed / relative)]
    elif args.frozen:
        installation = Path(tempfile.mkdtemp(prefix="novelcraft-安装检查-"))
        bundle_name = "NovelCraft.app" if sys.platform == "darwin" else "NovelCraft"
        destination = private_directory(installation / bundle_name)
        shutil.copytree(
            ROOT / "desktop/dist" / bundle_name,
            destination,
            symlinks=True,
            dirs_exist_ok=True,
        )
        command = [str(installation / bundle_name / relative)]
    else:
        command = [sys.executable, str(ROOT / "desktop/entry.py")]
    workspace = Path(tempfile.mkdtemp(prefix="novelcraft-作品检查-"))
    directory = private_directory(workspace / "private")
    try:
        subprocess.run([*command, "--role", "embedding-check"], check=True, timeout=180)
        process, client, log = launch(command, directory)
        original_origin = str(client.base_url)
        try:
            saved = json.loads((directory / "secrets.json").read_text())
            port = (directory / "database/postmaster.pid").read_text().splitlines()[3]
            with psycopg2.connect(
                host="127.0.0.1", port=port, user="novelcraft", dbname="novelcraft",
                password=saved["database_password"],
            ) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT cardinality(show_trgm('青铜古城')), "
                        "vector_dims('[1,2,3]'::vector)"
                    )
                    trigrams, dimensions = cursor.fetchone()
                    assert trigrams > 0 and dimensions == 3
            headers = {
                "Origin": str(client.base_url).rstrip("/"),
                "X-Requested-With": "XMLHttpRequest",
            }
            response = client.post(
                "/api/projects",
                json={"title": "Desktop synthetic persistence"},
                headers=headers,
            )
            assert response.status_code == 201, response.status_code
            project = response.json()
            project_id = project["id"]
            assert client.get("/api/projects/" + project_id).status_code == 200
            duplicate = subprocess.run(
                [*command, "--role", "supervisor"],
                env={**os.environ, "NOVELCRAFT_DESKTOP_DATA_DIR": str(directory)},
                input=b"",
                capture_output=True,
                timeout=15,
            )
            assert duplicate.returncode != 0
            assert client.get("/api/projects/" + project_id).status_code == 200
        finally:
            stop(process, client, log)
        process, client, log = launch(command, directory)
        try:
            assert str(client.base_url) == original_origin
            response = client.get("/api/projects/" + project_id)
            assert response.status_code == 200
            assert response.json()["title"] == "Desktop synthetic persistence"
        finally:
            stop(process, client, log)
        shutil.rmtree(workspace)
        if installation is not None:
            shutil.rmtree(installation)
        print(
            "Desktop smoke passed: new install, isolated session, "
            "single instance, restart."
        )
    except BaseException:
        print(
            f"Smoke failed; isolated evidence retained at {directory}", file=sys.stderr
        )
        from infrastructure.llm.redaction import redact_diagnostic

        if os.name == "nt":
            # Preserve ACL evidence when PostgreSQL's restricted token cannot read a file.
            install = Path(command[0]).parent
            for path in (install, install / "_internal/postgres/bin/initdb.exe"):
                subprocess.run(["icacls", str(path)], check=False)

        for name in ("smoke-supervisor", "setup", "database", "api", "worker"):
            log = directory / (name + ".log")
            if log.exists():
                tail = log.read_text(errors="replace")[-5000:]
                print(name + ": " + redact_diagnostic(tail, limit=5000), file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
