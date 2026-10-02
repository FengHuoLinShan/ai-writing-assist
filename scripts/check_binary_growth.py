#!/usr/bin/env python3
"""二进制增量体积门（B11）。

PR 新增或修改的二进制文件单文件超过 1MB 即失败；单 PR 二进制增量超过
5MB 即失败。豁免须在 EXEMPT_PATHS 登记路径与理由。删除文件不会缩小
历史 pack，改写 Git 历史须用户另行确认，不在本门范围。

用法（CI / 本地）：
    python scripts/check_binary_growth.py --base origin/main --head HEAD
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SINGLE_FILE_LIMIT_BYTES = 1024 * 1024
PR_TOTAL_LIMIT_BYTES = 5 * 1024 * 1024

# 豁免登记：glob 模式 → 必填理由。新增豁免须在此登记并说明为什么该资产
# 必须以二进制形式入库且无法压缩到 1MB 以下。
EXEMPT_PATHS: dict[str, str] = {
    # 目前无豁免。backend/.test-logs 已被 .gitignore 忽略，历史入库的
    # 240 个账本文件不会再出现在变更里，无需豁免。
}


@dataclass(frozen=True)
class BinaryChange:
    path: str
    status: str  # "A" 新增 / "M" 修改
    delta_bytes: int
    size_bytes: int


def _git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        check=True,
    )
    return result.stdout


def changed_paths(base: str, head: str) -> list[tuple[str, str]]:
    """返回 (status, path)，仅新增/修改；删除不产生体积。"""
    out = _git("diff", "--name-status", "-z", f"{base}...{head}")
    entries: list[tuple[str, str]] = []
    fields = out.decode("utf-8", "surrogateescape").split("\0")
    i = 0
    while i < len(fields):
        status = fields[i]
        if not status:
            i += 1
            continue
        # R（重命名）形如 R100；C 形如 C75。二进制重命名/复制同样占体积。
        if status.startswith(("R", "C")) and i + 2 < len(fields):
            entries.append((status[0], fields[i + 2]))
            i += 3
        else:
            entries.append((status[0], fields[i + 1]))
            i += 2
    return [
        (status, path)
        for status, path in entries
        if status in {"A", "M", "R", "C"}
    ]


def is_binary_file(path: str) -> bool:
    target = REPO_ROOT / path
    if not target.is_file():
        return False
    try:
        head_bytes = target.read_bytes()[:8192]
    except OSError:
        return False
    return b"\x00" in head_bytes


def size_at(ref: str, path: str) -> int | None:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-s", f"{ref}:{path}"],
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.decode().strip())
    except ValueError:
        return None


def is_exempt(path: str) -> str | None:
    for pattern, reason in EXEMPT_PATHS.items():
        if fnmatch.fnmatch(path, pattern):
            return reason
    return None


def collect_binary_changes(
    base: str, head: str, *, binary_probe=is_binary_file, sizer=size_at
) -> list[BinaryChange]:
    changes: list[BinaryChange] = []
    for status, path in changed_paths(base, head):
        if is_exempt(path) is not None:
            continue
        if not binary_probe(path):
            continue
        new_size = (REPO_ROOT / path).stat().st_size
        old_size = sizer(base, path) if status in {"M", "R"} else 0
        delta = max(0, new_size - (old_size or 0))
        changes.append(
            BinaryChange(
                path=path,
                status=status,
                delta_bytes=delta,
                size_bytes=new_size,
            )
        )
    return changes


def check(
    changes: list[BinaryChange],
    *,
    single_limit: int = SINGLE_FILE_LIMIT_BYTES,
    total_limit: int = PR_TOTAL_LIMIT_BYTES,
) -> list[str]:
    problems: list[str] = []
    for change in changes:
        if change.size_bytes > single_limit:
            problems.append(
                f"{change.path}: 单文件 {change.size_bytes} 字节超过 "
                f"{single_limit} 上限（二进制；豁免须在 "
                f"scripts/check_binary_growth.py 的 EXEMPT_PATHS 登记理由）"
            )
    total = sum(change.delta_bytes for change in changes)
    if total > total_limit:
        listing = ", ".join(
            f"{change.path}(+{change.delta_bytes})" for change in changes
        )
        problems.append(
            f"本变更二进制总增量 {total} 字节超过 {total_limit} 上限：{listing}"
        )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    changes = collect_binary_changes(args.base, args.head)
    for change in changes:
        print(
            f"binary {change.status} {change.path}: "
            f"{change.size_bytes} bytes (delta +{change.delta_bytes})"
        )
    problems = check(changes)
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"binary growth gate passed ({len(changes)} binary change(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
