#!/usr/bin/env python3
"""生产文件行数门（P8）。

生产代码超过 3000 行告警；超过 5000 行且高于入库基线即失败，允许下降。
基线固化 2026-10-02 实测（fa1ccc0 起两处超标文件）；存量豁免不允许
超过该固定基线。

用法：
    python scripts/check_file_sizes.py [--base origin/main --head HEAD]
带 --base 时只检查该变更触碰的文件（CI 增量口径）；否则检查全部生产文件。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

WARN_LINES = 3000
FAIL_LINES = 5000

# 入库基线：2026-10-02（0d555c4）实测的超 5000 行生产文件。允许下降；
# 固定基线只用于存量豁免，其他文件超过 5000 行即失败。
# AO-6（world API/schema/生成中心按子域拆分）后，原基线中的
# world_generation_center_service.py（5232）与 schemas.py（5138）均已拆分
# 退出超大文件清单，条目移除。
SIZE_BASELINE: dict[str, int] = {}

# 生产代码范围：后端业务/基建源码 + 前端运行时代码。排除 tests、tools、
# alembic、evals（评测资产）、原型与构建产物。
INCLUDE_PREFIXES = (
    "backend/modules/",
    "backend/infrastructure/",
    "backend/core/",
    "backend/shared/",
    "backend/app/",
    "frontend-console/vue/",
    "frontend-console/shared/",
    "frontend-console/ui/",
)
ROOT_INCLUDES = {
    "frontend-console/api.js",
    "frontend-console/apiContracts.js",
    "frontend-console/app.js",
    "frontend-console/router.js",
    "frontend-console/state.js",
    "frontend-console/stateSlices.js",
    "frontend-console/commands.js",
    "frontend-console/errorLogger.js",
}
INCLUDE_SUFFIXES = (".py", ".js", ".vue")


def _is_production(path: str) -> bool:
    if path in ROOT_INCLUDES:
        return True
    if not path.endswith(INCLUDE_SUFFIXES):
        return False
    if "/tests/" in f"/{path}" or path.endswith("_test.py"):
        return False
    return path.startswith(INCLUDE_PREFIXES)


def _changed_paths(base: str, head: str) -> set[str] | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
            f"{base}...{head}",
        ],
        capture_output=True,
        check=True,
    )
    return {
        item
        for item in result.stdout.decode("utf-8", "surrogateescape").split("\0")
        if item
    }


def check_files(
    paths: list[str], *, head: str | None = None
) -> tuple[list[str], list[str]]:
    """返回 (failures, warnings)。"""
    failures: list[str] = []
    warnings: list[str] = []
    for path in sorted(paths):
        if head is not None:
            blob = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "show", f"{head}:{path}"],
                capture_output=True,
                check=True,
            )
            lines = len(blob.stdout.splitlines())
        else:
            target = REPO_ROOT / path
            if not target.is_file():
                continue
            with target.open("rb") as handle:
                lines = sum(1 for _ in handle)
        if lines <= WARN_LINES:
            continue
        if lines > FAIL_LINES:
            baseline = SIZE_BASELINE.get(path)
            if baseline is not None and lines <= baseline:
                warnings.append(
                    f"{path}: {lines} 行（超 5000，未超过入库基线 {baseline}；"
                    f"基线只许下降）"
                )
            else:
                failures.append(
                    f"{path}: {lines} 行超过 {FAIL_LINES} 上限"
                    + (
                        f"（入库基线 {baseline}）"
                        if baseline is not None
                        else "（无基线，禁止新增超标文件）"
                    )
                )
        else:
            warnings.append(f"{path}: {lines} 行（超 {WARN_LINES}，建议拆分）")
    return failures, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="只检查变更触碰的文件")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)

    if args.base:
        changed = _changed_paths(args.base, args.head) or set()
        paths = [path for path in changed if _is_production(path)]
    else:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files"],
            capture_output=True,
            check=True,
        )
        paths = [
            path
            for path in result.stdout.decode().splitlines()
            if _is_production(path)
        ]

    failures, warnings = check_files(paths, head=args.head if args.base else None)
    for warning in warnings:
        print(f"WARN {warning}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    if failures:
        return 1
    print(
        f"file size gate passed ({len(paths)} production file(s) checked, "
        f"{len(warnings)} warning(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
