"""Versioned desktop artifacts and fixed-main-SHA release checks (stdlib only)."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {
    "macos-arm64": ".dmg",
    "macos-x64": ".dmg",
    "windows-x64": "-Setup.exe",
}
DEFAULT_TARGET = "macos-arm64"
TARGETS = (*PLATFORMS, "all")
REQUIRED_WORKFLOWS = {
    "backend-ci.yml",
    "frontend-ci.yml",
    "codeql.yml",
    "architecture-docs.yml",
    "repo-gates.yml",
}


def selected_platforms(target: str) -> tuple[str, ...]:
    if target not in TARGETS:
        raise ValueError(f"Unknown build target: {target}")
    return tuple(PLATFORMS) if target == "all" else (target,)


def build_matrix(target: str, root: Path = ROOT) -> list[dict]:
    python = (root / "backend/.python-version").read_text().strip()
    runners = {
        "macos-arm64": ("macos-15", python),
        "macos-x64": ("macos-15-intel", "3.13.15"),
        "windows-x64": ("windows-2025", python),
    }
    return [
        {"platform": platform, "os": runners[platform][0], "python": runners[platform][1]}
        for platform in selected_platforms(target)
    ]


def version(root: Path = ROOT) -> str:
    value = (root / "desktop/VERSION").read_text().strip()
    if not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.[1-9]\d*)?", value
    ):
        raise ValueError("desktop/VERSION must be X.Y.Z or X.Y.Z-alpha/beta/rc.N")
    if any(int(part) > 65535 for part in value.split("-")[0].split(".")):
        raise ValueError("Version exceeds native Windows version fields")
    return value


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def build_metadata(root: Path = ROOT) -> dict:
    return {
        "version": version(root),
        "commit": git("rev-parse", "HEAD", root=root),
        "dirty": bool(git("status", "--porcelain", root=root)),
    }


def verify_ci(runs: list[dict], sha: str):
    latest = {}
    for run in runs:
        name = Path(run["path"]).name
        if (
            run["head_sha"] == sha
            and run["event"] == "push"
            and name in REQUIRED_WORKFLOWS
        ):
            if name not in latest or run["id"] > latest[name]["id"]:
                latest[name] = run
    failed = [
        name
        for name in sorted(REQUIRED_WORKFLOWS)
        if name not in latest or latest[name]["conclusion"] != "success"
    ]
    if failed:
        raise ValueError("Target SHA main CI missing/not green: " + ", ".join(failed))


def verify_source(sha: str, root: Path = ROOT) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Release requires a full 40-character commit SHA")
    if git("rev-parse", "HEAD", root=root) != sha:
        raise ValueError("Checkout does not match the release SHA")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=root, check=True
    )
    metadata = build_metadata(root)
    if metadata["dirty"]:
        raise ValueError("Release checkout must be clean")
    notes = root / "desktop/changes" / (metadata["version"] + ".md")
    if not notes.is_file() or not notes.read_text().strip():
        raise ValueError("Release notes are missing")
    return metadata


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def artifact_name(v: str, platform: str) -> str:
    return f"NovelCraft-{v}-{platform}{PLATFORMS[platform]}"


def package(source: Path, platform: str, signed: bool, output: Path, root: Path = ROOT):
    metadata = json.loads((root / "desktop/build/assets/build.json").read_text())
    if metadata != build_metadata(root):
        raise ValueError("Build provenance differs from the current checkout")
    if signed and metadata["dirty"]:
        raise ValueError("Signed releases require a clean source checkout")
    output.mkdir(parents=True, exist_ok=True)
    target = output / artifact_name(metadata["version"], platform)
    shutil.copy2(source, target)
    record = {
        **metadata,
        "platform": platform,
        "signed": signed,
        "file": target.name,
        "sha256": digest(target),
        "size": target.stat().st_size,
    }
    (output / (platform + ".json")).write_text(json.dumps(record, indent=2) + "\n")


def assemble(directory: Path, sha: str, root: Path = ROOT, target: str = DEFAULT_TARGET):
    v = version(root)
    platforms = selected_platforms(target)
    for platform in PLATFORMS:
        if platform not in platforms and list(directory.rglob(platform + ".json")):
            raise ValueError(f"Unrequested platform artifact: {platform}")
    records = []
    for platform in platforms:
        matches = list(directory.rglob(platform + ".json"))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one artifact for {platform}")
        record = json.loads(matches[0].read_text())
        expected = artifact_name(v, platform)
        if (
            record["version"] != v
            or record["commit"] != sha
            or record["dirty"]
            or record["platform"] != platform
            or record["file"] != expected
        ):
            raise ValueError(f"Artifact provenance mismatch: {platform}")
        if "-" not in v and record["signed"] is not True:
            raise ValueError("Stable releases require verified signing/notarization")
        artifact = matches[0].parent / expected
        if (
            artifact.stat().st_size != record["size"]
            or digest(artifact) != record["sha256"]
        ):
            raise ValueError(f"Artifact checksum mismatch: {platform}")
        records.append(record)
    output = directory / "release"
    output.mkdir(exist_ok=False)
    for record in records:
        source = (
            next(directory.rglob(record["platform"] + ".json")).parent / record["file"]
        )
        shutil.copy2(source, output / record["file"])
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{r['sha256']}  {r['file']}\n" for r in records)
    )
    (output / "release.json").write_text(
        json.dumps({"version": v, "commit": sha, "artifacts": records}, indent=2) + "\n"
    )
    shutil.copy2(root / "desktop/INSTALL.txt", output / "安装说明.txt")
    shutil.copy2(root / "desktop/changes" / (v + ".md"), output / "RELEASE-NOTES.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("target", choices=TARGETS, nargs="?", default=DEFAULT_TARGET)
    verify = commands.add_parser("verify-source")
    verify.add_argument("sha")
    verify.add_argument("--ci-runs", type=Path, required=True)
    pack = commands.add_parser("package")
    pack.add_argument("source", type=Path)
    pack.add_argument("platform", choices=PLATFORMS)
    pack.add_argument("--signed", action="store_true")
    pack.add_argument("--output", type=Path, default=ROOT / "desktop/dist/release")
    collect = commands.add_parser("assemble")
    collect.add_argument("directory", type=Path)
    collect.add_argument("sha")
    collect.add_argument("--target", choices=TARGETS, default=DEFAULT_TARGET)
    args = parser.parse_args()
    if args.command == "matrix":
        print("matrix=" + json.dumps(build_matrix(args.target)))
    elif args.command == "verify-source":
        metadata = verify_source(args.sha)
        pages = json.loads(args.ci_runs.read_text())
        verify_ci([run for page in pages for run in page["workflow_runs"]], args.sha)
        print("version=" + metadata["version"])
        print("signed=" + str("-" not in metadata["version"]).lower())
    elif args.command == "package":
        package(args.source, args.platform, args.signed, args.output)
    else:
        assemble(args.directory, args.sha, target=args.target)


if __name__ == "__main__":
    main()
