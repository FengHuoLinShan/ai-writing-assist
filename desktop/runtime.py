"""Own only this desktop instance's database, API and worker processes."""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from infrastructure.os_security import open_private_file, private_directory, try_lock

from desktop.gateway import readiness_proof
from desktop.windows_process import WindowsDatabaseProcess


def resource_root() -> Path:
    return (
        Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parents[1]
    )


def backend_root() -> Path:
    return (
        resource_root() if getattr(sys, "frozen", False) else resource_root() / "backend"
    )


def data_directory() -> Path:
    override = os.environ.get("NOVELCRAFT_DESKTOP_DATA_DIR")
    if override:
        return Path(override).absolute()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/NovelCraft"
    if sys.platform == "win32":
        return Path.home() / "AppData/Local/NovelCraft"
    raise RuntimeError("Desktop builds support macOS and Windows")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def entry_command(role: str) -> list[str]:
    command = [sys.executable]
    if getattr(sys, "frozen", False):
        command = [
            str(
                Path(sys.executable).with_name(
                    "NovelCraftRuntime" + (".exe" if os.name == "nt" else "")
                )
            )
        ]
    else:
        command.append(str(resource_root() / "desktop/entry.py"))
    return [*command, "--role", role]


class LocalRuntime:
    def __init__(self, directory: Path) -> None:
        self.directory = private_directory(directory)
        self.lock = open_private_file(directory / "instance.lock", write=True)
        if not try_lock(self.lock):
            os.close(self.lock)
            raise RuntimeError("NovelCraft 已在运行，请切换到已打开的窗口。")
        assets = (
            resource_root()
            if getattr(sys, "frozen", False)
            else (resource_root() / "desktop/build/assets")
        )
        self.pg_bin = assets / "postgres/bin"
        self.model = assets / "model"
        self.processes: list[tuple[str, subprocess.Popen | WindowsDatabaseProcess]] = []
        self.logs = []
        self.stopping = threading.Event()
        self.env = self._environment()
        self.origin = self.env["PUBLIC_BASE_URL"]

    def pg(self, name: str) -> str:
        path = self.pg_bin / (name + (".exe" if os.name == "nt" else ""))
        if not path.is_file():
            raise RuntimeError("安装包缺少数据库组件，请重新安装。作品数据不会被删除。")
        return str(path)

    def _environment(self) -> dict[str, str]:
        state = self.directory / "secrets.json"
        if not state.exists():
            fd, temporary = tempfile.mkstemp(prefix=".secrets-", dir=self.directory)
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(
                        {
                            "database_password": secrets.token_hex(32),
                            "api_port": free_port(),
                            "encryption_key": base64.urlsafe_b64encode(
                                os.urandom(32)
                            ).decode(),
                        },
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, state)
            finally:
                Path(temporary).unlink(missing_ok=True)
        fd = open_private_file(state)
        with os.fdopen(fd) as stream:
            saved = json.load(stream)
        allowed = {
            "PATH",
            "HOME",
            "USERPROFILE",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LANG",
            "LC_ALL",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
            "PYINSTALLER_RESET_ENVIRONMENT",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        api_port = int(saved["api_port"])
        port = free_port()
        while port == api_port:
            port = free_port()
        env.update(
            {
                "APP_ENV": "local",
                "AUTH_MODE": "local",
                "DEBUG": "false",
                "DATABASE_URL": "postgresql+asyncpg://novelcraft:"
                + saved["database_password"]
                + f"@127.0.0.1:{port}/novelcraft",
                "PGHOST": "127.0.0.1",
                "PGPORT": str(port),
                "PGUSER": "novelcraft",
                "PGDATABASE": "novelcraft",
                "PGPASSWORD": saved["database_password"],
                "LLM_SETTINGS_ENCRYPTION_KEY": saved["encryption_key"],
                "WORLD_IMAGES_DIRECTORY": str(self.directory / "images"),
                "MAP_ATLAS_S3_BUCKET": "map-atlas",
                "WORLD_OBJECT_S3_BUCKET": "world-objects",
                "PUBLIC_BASE_URL": f"http://127.0.0.1:{api_port}",
                "ALLOWED_ORIGINS": f"http://127.0.0.1:{api_port}",
                "EMBEDDING_PROVIDER": "bge_onnx",
                "BGE_ONNX_MODEL_PATH": str(self.model),
                "RAG_PREWARM_ON_STARTUP": "false",
                "HF_HUB_OFFLINE": "1",
                "NOVELCRAFT_DESKTOP_TOKEN": secrets.token_urlsafe(32),
                "NOVELCRAFT_DESKTOP_DATA_DIR": str(self.directory),
                "PYTHONUNBUFFERED": "1",
                "PYTHONUTF8": "1",
                "POOL_SIZE": "4",
                "MAX_OVERFLOW": "4",
            }
        )
        return env

    def run(self, command: list[str], *, timeout=180) -> None:
        with (self.directory / "setup.log").open("ab") as log:
            subprocess.run(
                command,
                env=self.env,
                cwd=backend_root(),
                stdout=log,
                stderr=log,
                check=True,
                timeout=timeout,
            )

    def spawn(self, name: str, command: list[str], *, control=False):
        log = (self.directory / f"{name}.log").open("ab")
        self.logs.append(log)
        process = subprocess.Popen(
            command,
            env=self.env,
            cwd=backend_root(),
            stdout=log,
            stderr=log,
            stdin=subprocess.PIPE if control else subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.processes.append((name, process))
        return process

    def _wait(self, probe, *, seconds=90):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.stopping.is_set():
            if any(p.poll() is not None for _, p in self.processes):
                raise RuntimeError("本机服务未能启动，请查看应用数据目录内的日志。")
            try:
                if probe():
                    return
            except (OSError, ConnectionError):
                pass
            self.stopping.wait(0.2)
        raise RuntimeError("启动未完成，作品数据已保留。请重新打开应用。")

    def start(self) -> str:
        import psycopg2

        if not (self.model / "model.onnx").is_file():
            raise RuntimeError("安装包缺少本地检索模型，请重新安装。")
        pgdata = self.directory / "database"
        if pgdata.exists() and not (pgdata / "PG_VERSION").exists():
            raise RuntimeError("数据库初始化尚未完成，请保留数据目录并查看 setup.log。")
        if not pgdata.exists():
            staged = Path(
                tempfile.mkdtemp(prefix=".initial-database-", dir=self.directory)
            )
            password = self.directory / ".initial-password"
            fd = open_private_file(password, write=True)
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(self.env["PGPASSWORD"])
                self.run(
                    [
                        self.pg("initdb"),
                        "-D",
                        str(staged),
                        "-U",
                        "novelcraft",
                        "--pwfile",
                        str(password),
                        "--auth=scram-sha-256",
                        "--encoding=UTF8",
                        "--locale=C",
                        # pg_trgm still uses the OS character classifier in PG 17.
                        "--lc-ctype="
                        + (
                            "English_United States.1252"
                            if os.name == "nt"
                            else "en_US.UTF-8"
                        ),
                        "--locale-provider=builtin",
                        "--builtin-locale=C.UTF-8",
                    ]
                )
                staged.rename(pgdata)
            finally:
                password.unlink(missing_ok=True)
                if staged.exists():
                    shutil.rmtree(staged)
        if (pgdata / "PG_VERSION").read_text().strip() != "17":
            raise RuntimeError("数据版本与应用不兼容，已停止启动以保护作品。")
        options = [
            "-h",
            "127.0.0.1",
            "-p",
            self.env["PGPORT"],
            "-c",
            "shared_buffers=32MB",
            "-c",
            "max_connections=30",
            "-c",
            "unix_socket_directories=",
        ]
        if os.name == "nt":
            # pg_ctl removes administrator privileges before starting PostgreSQL.
            try:
                self.run(
                    [
                        self.pg("pg_ctl"),
                        "-D",
                        str(pgdata),
                        "start",
                        "-w",
                        "-t",
                        "60",
                        "-l",
                        str(self.directory / "database.log"),
                        "-o",
                        subprocess.list2cmdline(options),
                    ]
                )
                pid = int((pgdata / "postmaster.pid").read_text().splitlines()[0])
                process = WindowsDatabaseProcess(pid, self.pg("postgres"))
                self.processes.append(("database", process))
            except BaseException:
                if (pgdata / "postmaster.pid").exists():
                    self.run(
                        [self.pg("pg_ctl"), "-D", str(pgdata), "stop", "-m", "fast", "-w"]
                    )
                raise
        else:
            self.spawn("database", [self.pg("postgres"), "-D", str(pgdata), *options])

        def connect(database="postgres"):
            return psycopg2.connect(
                host="127.0.0.1",
                port=self.env["PGPORT"],
                user="novelcraft",
                password=self.env["PGPASSWORD"],
                dbname=database,
                connect_timeout=1,
            )

        def ready():
            try:
                connection = connect()
                connection.close()
                return True
            except psycopg2.OperationalError:
                return False

        self._wait(ready)
        connection = connect()
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_database WHERE datname='novelcraft'")
                if not cursor.fetchone():
                    cursor.execute("CREATE DATABASE novelcraft")
        finally:
            connection.close()
        connection = connect("novelcraft")
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            connection.commit()
        finally:
            connection.close()
        self.run(entry_command("migrate"))
        self.spawn("api", entry_command("api"), control=True)
        token = self.env["NOVELCRAFT_DESKTOP_TOKEN"]

        def api_ready():
            # A process racing for this port must not receive the session secret.
            with build_opener(ProxyHandler({})).open(
                self.origin + "/_desktop/ready", timeout=1
            ) as response:
                return hmac.compare_digest(
                    response.read(128), readiness_proof(token).encode()
                )

        self._wait(api_ready)
        self.spawn("worker", entry_command("worker"), control=True)
        return self.origin + "/_desktop/open/" + token

    def close(self):
        self.stopping.set()
        try:
            for name, process in reversed(self.processes):
                if process.poll() is not None:
                    continue
                try:
                    if process.stdin:
                        try:
                            process.stdin.close()
                        except BrokenPipeError:
                            pass
                    elif name == "database":
                        try:
                            self.run(
                                [
                                    self.pg("pg_ctl"),
                                    "-D",
                                    str(self.directory / "database"),
                                    "stop",
                                    "-m",
                                    "fast",
                                    "-w",
                                ],
                                timeout=60,
                            )
                        except (OSError, subprocess.SubprocessError):
                            process.terminate()
                    try:
                        process.wait(timeout=135 if name == "worker" else 30)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=15)
                except ProcessLookupError:
                    pass
        finally:
            for _, process in self.processes:
                if isinstance(process, WindowsDatabaseProcess):
                    process.close()
            for log in self.logs:
                log.close()
            os.close(self.lock)
