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
from pathlib import Path

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]


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
        row = json.loads(result.get(timeout=180))
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
    parser.add_argument("--frozen", action="store_true")
    args = parser.parse_args()
    installation = None
    if args.frozen:
        installation = Path(tempfile.mkdtemp(prefix="novelcraft-安装检查-"))
        bundle_name = "NovelCraft.app" if sys.platform == "darwin" else "NovelCraft"
        shutil.copytree(
            ROOT / "desktop/dist" / bundle_name,
            installation / bundle_name,
            symlinks=True,
        )
        relative = (
            "NovelCraft.app/Contents/MacOS/NovelCraftRuntime"
            if sys.platform == "darwin"
            else "NovelCraft/NovelCraftRuntime.exe"
        )
        command = [str(installation / relative)]
    else:
        command = [sys.executable, str(ROOT / "desktop/entry.py")]
    directory = Path(tempfile.mkdtemp(prefix="novelcraft-作品检查-"))
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
        shutil.rmtree(directory)
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
        raise


if __name__ == "__main__":
    main()
