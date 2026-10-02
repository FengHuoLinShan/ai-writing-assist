#!/usr/bin/env python3
"""发布证据账本校验器（B6）。

校验 docs/evidence/*.json 证据文件：
- schema 合法（必填字段与类型，claims_boundary 必须同时写明证明与不证明什么）；
- 关联 commit 在 base 分支可达；
- 引用的数据集/文件 sha256 与实际一致；
- 超过 --max-age-days 未更新标 stale（失败或告警，见 --stale-fails）。

付费原始数据留仓库外；仓库内证据只含去原文的结论与账本快照。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"

SCHEMA_VERSION = "release-evidence-v1"
MAX_AGE_DAYS = 180

REQUIRED_FIELDS = (
    "schema_version",
    "capability",
    "dataset",
    "metrics",
    "generated_at",
    "generator_version",
    "commit",
    "claims_boundary",
)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_payload(payload: dict, path: Path) -> list[str]:
    problems: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"{path.name}: schema_version 必须是 {SCHEMA_VERSION}")
    for field in REQUIRED_FIELDS:
        if field not in payload:
            problems.append(f"{path.name}: 缺少必填字段 {field}")
    if problems:
        return problems

    boundary = payload.get("claims_boundary")
    if not isinstance(boundary, dict) or not isinstance(
        boundary.get("proves"), list
    ) or not isinstance(boundary.get("does_not_prove"), list):
        problems.append(
            f"{path.name}: claims_boundary 必须含 proves / does_not_prove 列表"
        )
    if not isinstance(payload.get("metrics"), list):
        problems.append(f"{path.name}: metrics 必须是列表（无指标时为空列表）")
    try:
        datetime.fromisoformat(str(payload["generated_at"]))
    except ValueError:
        problems.append(f"{path.name}: generated_at 必须是 ISO-8601 时间")
    dataset = payload.get("dataset")
    if not isinstance(dataset, dict) or not dataset.get("name"):
        problems.append(f"{path.name}: dataset 必须含 name")
    return problems


def validate_commit(payload: dict, path: Path, base: str) -> list[str]:
    commit = str(payload.get("commit") or "")
    if not commit:
        return [f"{path.name}: commit 为空"]
    result = _git("merge-base", "--is-ancestor", commit, base)
    if result.returncode != 0:
        return [
            f"{path.name}: commit {commit[:12]} 不在 {base} 可达范围内"
        ]
    return []


def validate_files(payload: dict, path: Path) -> list[str]:
    problems: list[str] = []
    dataset = payload.get("dataset") or {}
    for ref in dataset.get("files", []):
        if not isinstance(ref, dict):
            problems.append(f"{path.name}: dataset.files 含非对象条目")
            continue
        rel = str(ref.get("path") or "")
        expected = str(ref.get("sha256") or "")
        if not rel or not expected:
            problems.append(f"{path.name}: dataset.files 条目缺 path/sha256")
            continue
        target = REPO_ROOT / rel
        if not target.is_file():
            problems.append(f"{path.name}: 数据集文件不存在 {rel}")
            continue
        actual = _file_sha256(target)
        if actual != expected:
            problems.append(
                f"{path.name}: {rel} sha256 不一致（证据 {expected[:12]}，"
                f"实际 {actual[:12]}）"
            )
    return problems


def validate_staleness(payload: dict, path: Path, *, max_age_days: int) -> list[str]:
    try:
        generated = datetime.fromisoformat(str(payload["generated_at"]))
    except (KeyError, ValueError):
        return []
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - generated).days
    if age_days > max_age_days:
        return [
            f"{path.name}: 证据已 {age_days} 天未更新（上限 {max_age_days}），"
            f"请重新生成或更新证据"
        ]
    return []


def check(
    evidence_dir: Path = EVIDENCE_DIR,
    *,
    base: str = "origin/main",
    max_age_days: int = MAX_AGE_DAYS,
    stale_fails: bool = True,
) -> tuple[list[str], list[str]]:
    """返回 (failures, warnings)。"""
    failures: list[str] = []
    warnings: list[str] = []
    files = sorted(evidence_dir.glob("*.json")) if evidence_dir.is_dir() else []
    if not files:
        failures.append(f"{evidence_dir}: 没有可校验的证据文件")
        return failures, warnings
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{path.name}: JSON 解析失败 {exc}")
            continue
        failures.extend(validate_payload(payload, path))
        failures.extend(validate_commit(payload, path, base))
        failures.extend(validate_files(payload, path))
        stale = validate_staleness(payload, path, max_age_days=max_age_days)
        if stale:
            (failures if stale_fails else warnings).extend(stale)
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--max-age-days", type=int, default=MAX_AGE_DAYS)
    parser.add_argument(
        "--stale-warns",
        action="store_true",
        help="stale 只告警不失败（默认失败）",
    )
    args = parser.parse_args(argv)

    failures, warnings = check(
        base=args.base,
        max_age_days=args.max_age_days,
        stale_fails=not args.stale_warns,
    )
    for warning in warnings:
        print(f"WARN {warning}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print("release evidence gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
