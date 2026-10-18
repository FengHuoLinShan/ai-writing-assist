"""Build platform-native PostgreSQL and fetch a pinned offline ONNX model."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "desktop/build"
ASSETS = BUILD / "assets"
PG_VERSION = "17.10"
PG_SHA = "078a03516dcdbdb705fecaf415ea3d13a956c589e46f09fed68a06fb00598c90"
VECTOR_VERSION = "0.8.6"
VECTOR_SHA = "10bf9938906e5d643bbc4a7eea104b6f57ba4898e5b76b20e60484ea1d5a7f8f"
MODEL_REVISION = "71e50dc531959f9e04ebf190ea25b00261a0a186"
MODEL_SHA = "b665f3bba56c3119bc76ba131ebcc544d720a7408cb11581bdf354aaa0198d43"
WEBVIEW_SHA = "90ae8eb0d9d22d6e51fccde49e4d25d266ff9343ad0cc931faa6f482569cea62"


def download(url: str, target: Path, sha: str | None = None):
    import certifi
    import httpx

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        with httpx.stream(
            "GET", url, follow_redirects=True, verify=certifi.where(), timeout=120
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        temporary.replace(target)
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if sha and digest != sha:
        raise ValueError(f"Dependency checksum mismatch: {target.name}")
    return digest


def source(name: str, url: str, sha: str) -> Path:
    archive = BUILD / (name + ".tar.gz")
    download(url, archive, sha)
    directory = BUILD / name
    if not directory.exists():
        with tarfile.open(archive) as compressed:
            compressed.extractall(BUILD, filter="data")
    return directory


def run(*args: str, cwd: Path, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    pg = source(
        "postgresql-" + PG_VERSION,
        f"https://ftp.postgresql.org/pub/source/v{PG_VERSION}/"
        f"postgresql-{PG_VERSION}.tar.bz2",
        PG_SHA,
    )
    vector = source(
        "pgvector-" + VECTOR_VERSION,
        f"https://github.com/pgvector/pgvector/archive/refs/tags/"
        f"v{VECTOR_VERSION}.tar.gz",
        VECTOR_SHA,
    )
    prefix = ASSETS / "postgres"
    target_stamp = BUILD / "macos-deployment-target"
    if sys.platform == "darwin":
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = "14.0"
        if not target_stamp.exists() or target_stamp.read_text() != "14.0":
            if (pg / "config.status").exists():
                run("make", "distclean", cwd=pg)
            run("make", "clean", cwd=vector)
    if os.name == "nt":
        download(
            "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
            ASSETS / "WebView2Setup.exe",
            WEBVIEW_SHA,
        )
        build = BUILD / "pg-build"
        if not build.exists():
            run(
                sys.executable,
                "-m",
                "mesonbuild.mesonmain",
                "setup",
                str(build),
                str(pg),
                "--prefix=" + str(prefix),
                "--buildtype=release",
                *[
                    "-D" + name + "=disabled"
                    for name in (
                        "icu",
                        "readline",
                        "zlib",
                        "lz4",
                        "zstd",
                        "gssapi",
                        "nls",
                        "ldap",
                        "libxml",
                        "libxslt",
                        "plperl",
                        "plpython",
                        "pltcl",
                        "docs",
                        "tap_tests",
                    )
                ],
                "-Dssl=none",
                cwd=BUILD,
            )
        run(
            sys.executable,
            "-m",
            "mesonbuild.mesonmain",
            "compile",
            "-C",
            str(build),
            cwd=BUILD,
        )
        run(
            sys.executable,
            "-m",
            "mesonbuild.mesonmain",
            "install",
            "-C",
            str(build),
            cwd=BUILD,
        )
        env = {**os.environ, "PGROOT": str(prefix)}
        run("nmake", "/F", "Makefile.win", cwd=vector, env=env)
        run("nmake", "/F", "Makefile.win", "install", cwd=vector, env=env)
    else:
        if not (pg / "config.status").exists():
            run(
                "./configure",
                "--prefix=" + str(prefix),
                "--without-readline",
                "--without-zlib",
                "--without-icu",
                "--without-lz4",
                "--without-zstd",
                "--without-gssapi",
                "--without-openssl",
                cwd=pg,
            )
        jobs = str(min(os.cpu_count() or 2, 8))
        run("make", "-j" + jobs, cwd=pg)
        run("make", "install", cwd=pg)
        run("make", "install", cwd=pg / "contrib/pg_trgm")
        env = {**os.environ, "PG_CONFIG": str(prefix / "bin/pg_config")}
        run("make", "-j" + jobs, "OPTFLAGS=", cwd=vector, env=env)
        run("make", "install", "OPTFLAGS=", cwd=vector, env=env)
    (ASSETS / "licenses").mkdir(parents=True, exist_ok=True)
    shutil.copy2(pg / "COPYRIGHT", ASSETS / "licenses/PostgreSQL.txt")
    shutil.copy2(vector / "LICENSE", ASSETS / "licenses/pgvector.txt")
    model = ASSETS / "model"
    base = f"https://huggingface.co/Xenova/bge-base-zh-v1.5/resolve/{MODEL_REVISION}/"
    download(base + "onnx/model_quantized.onnx", model / "model.onnx", MODEL_SHA)
    tokenizer = download(base + "tokenizer.json", model / "tokenizer.json")
    download(base + "README.md", ASSETS / "licenses/Embedding-model.md")
    if sys.platform == "darwin":
        target_stamp.write_text("14.0")
    (ASSETS / "manifest.json").write_text(
        json.dumps(
            {
                "postgres": PG_VERSION,
                "pgvector": VECTOR_VERSION,
                "model_revision": MODEL_REVISION,
                "model_sha256": MODEL_SHA,
                "tokenizer_sha256": tokenizer,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
