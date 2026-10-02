#!/usr/bin/env python3
"""跨模块 import 守护门（B2）。

生产代码跨业务模块只能经合法形态导入：顶层 contracts/facade、包
``__init__`` 再出口、嵌套 facade/contracts、ORM models（AGENTS 允许的
有限例外）。其余跨模块 import 必须在 EXEMPT_IMPORTS 登记理由，否则失败。

模块清单事实源：docs/architecture/architecture-documents.toml 的 components
（kind="business"）。豁免清单即本文件的 EXEMPT_IMPORTS：键为
``路径:目标模块``（支持 fnmatch 通配），值为必填理由。

用法：
    python scripts/check_module_imports.py [--json]
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_DOC = REPO_ROOT / "docs/architecture/architecture-documents.toml"

# 跨模块 import 的合法形态（相对 modules/ 的导入路径片段）。
_LEGAL_SUFFIXES = (
    ".contracts",
    ".facade",
    ".models",
)


def load_business_modules() -> dict[str, tuple[str, ...]]:
    """component name → source_roots（backend 相对路径）。"""
    data = tomllib.loads(ARCH_DOC.read_text(encoding="utf-8"))
    modules: dict[str, tuple[str, ...]] = {}
    for component in data.get("components", []):
        if component.get("kind") != "business":
            continue
        modules[str(component["name"])] = tuple(
            str(root).removeprefix("backend/") for root in component["source_roots"]
        )
    return modules


def owning_module(path: str, modules: dict[str, tuple[str, ...]]) -> str | None:
    for name, roots in modules.items():
        for root in roots:
            if path.startswith(root + "/"):
                return name
    return None


def _import_segments(module_path: str) -> tuple[str, ...]:
    return tuple(segment for segment in module_path.split(".") if segment)


def is_legal_cross_import(target: str, modules: dict[str, tuple[str, ...]]) -> bool:
    """判定一个 modules.* 导入目标是否为合法形态。

    合法形态（AGENTS「生产业务跨模块仅依赖 contracts.py、facade.py 或已
    注册 DI port」+ ORM metadata 有限例外的可扫描化）：
    - 顶层/嵌套 contracts、facade，以及命名 facade（map_atlas_facade、
      worldbuilding_facade 等，文件名以 facade 结尾即为显式门面模块）；
    - 包 ``__init__`` 再出口；
    - ORM models（models、*_models、models.* 子包：AGENTS 允许的有限例外）。
    """
    segments = _import_segments(target)
    if len(segments) < 2 or segments[0] != "modules":
        return True  # 非跨模块目标（core/shared/infrastructure 等基建层）
    target_module = segments[1]
    if target_module not in modules:
        return True  # 未登记组件（如新增模块尚未登记），由 docs-check 管
    rest = segments[2:]
    if not rest:
        return True  # 包 __init__ 再出口
    last = rest[-1]
    if last.endswith("facade") or last.endswith("contracts"):
        return True
    if any(
        segment == "models" or segment.endswith("_models") for segment in rest
    ):
        return True  # ORM models / session_models 等
    joined = ".".join(rest)
    return any(joined.endswith(suffix) for suffix in _LEGAL_SUFFIXES)


def iter_violations(
    modules: dict[str, tuple[str, ...]],
    *,
    exempt: dict[str, str],
) -> list[dict]:
    backend_root = REPO_ROOT / "backend"
    violations: list[dict] = []
    for path in sorted(backend_root.glob("modules/**/*.py")):
        relative = path.relative_to(backend_root).as_posix()
        if "/tests/" in f"/{relative}" or relative.endswith("_test.py"):
            continue
        owner = owning_module(relative, modules)
        if owner is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "target": "",
                    "reason": f"AST 解析失败: {exc}",
                }
            )
            continue
        for node in ast.walk(tree):
            targets: list[tuple[int, str]] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                targets.append((node.lineno, node.module))
            elif isinstance(node, ast.Import):
                targets.extend((alias.lineno, alias.name) for alias in node.names)
            for line, target in targets:
                segments = _import_segments(target)
                if len(segments) < 2 or segments[0] != "modules":
                    continue
                target_module = segments[1]
                if target_module == owner or target_module not in modules:
                    continue
                if is_legal_cross_import(target, modules):
                    continue
                if _is_exempt(relative, target, exempt):
                    continue
                violations.append(
                    {
                        "path": relative,
                        "line": line,
                        "target": target,
                        "reason": (
                            f"跨模块导入 {target} 不经 contracts/facade/__init__/ORM models"
                        ),
                    }
                )
    return violations


def iter_violations_for_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
    exempt: dict[str, str],
) -> list[dict]:
    """对给定文件列表执行与 iter_violations 相同的判定（测试/增量入口）。"""
    import ast as _ast

    violations: list[dict] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        # 支持绝对路径（tests）与仓库相对（backend/ 前缀可选）
        rel = None
        try:
            rel = path.relative_to(repo_root).as_posix()
        except ValueError:
            rel = path.as_posix()
        backend_rel = rel.removeprefix("backend/")
        owner = owning_module(backend_rel, modules)
        if owner is None or "/tests/" in f"/{backend_rel}":
            continue
        try:
            tree = _ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            violations.append(
                {"path": backend_rel, "line": 0, "target": "", "reason": f"AST 解析失败: {exc}"}
            )
            continue
        for node in _ast.walk(tree):
            targets: list[tuple[int, str]] = []
            if isinstance(node, _ast.ImportFrom) and node.module:
                targets.append((node.lineno, node.module))
            elif isinstance(node, _ast.Import):
                targets.extend((alias.lineno, alias.name) for alias in node.names)
            for line, target in targets:
                segments = _import_segments(target)
                if len(segments) < 2 or segments[0] != "modules":
                    continue
                target_module = segments[1]
                if target_module == owner or target_module not in modules:
                    continue
                if is_legal_cross_import(target, modules):
                    continue
                if _is_exempt(backend_rel, target, exempt):
                    continue
                violations.append(
                    {
                        "path": backend_rel,
                        "line": line,
                        "target": target,
                        "reason": (
                            f"跨模块导入 {target} 不经 contracts/facade/__init__/ORM models"
                        ),
                    }
                )
    return violations


def _is_exempt(path: str, target: str, exempt: dict[str, str]) -> bool:
    for pattern in exempt:
        file_glob, _, target_glob = pattern.rpartition(":")
        if fnmatch.fnmatch(path, file_glob) and fnmatch.fnmatch(target, target_glob):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    modules = load_business_modules()
    violations = iter_violations(modules, exempt=EXEMPT_IMPORTS)
    if args.json:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
    for item in violations:
        print(
            f"FAIL {item['path']}:{item['line']} {item['reason']}",
            file=sys.stderr,
        )
    if violations:
        print(
            f"{len(violations)} violation(s); 登记豁免须在 "
            f"scripts/check_module_imports.py 的 EXEMPT_IMPORTS 写明理由",
            file=sys.stderr,
        )
        return 1
    print(
        f"module import gate passed "
        f"({len(modules)} business module(s), "
        f"{len(EXEMPT_IMPORTS)} exemption(s))"
    )
    return 0


# 豁免登记：``文件 glob:导入目标 glob`` → 理由。
# 2026-10-02 首轮实测裁定：存量 16 条中 8 条属合法形态（命名 facade / ORM
# _models），其余 8 条为直接引用实现，逐条豁免如下（整改须逐项排期，
# 新增豁免须同步更新本清单并说明为什么无法走 contracts/facade）。
EXEMPT_IMPORTS: dict[str, str] = {
    # collaboration 合并预览消费 assistant 的对话 projection schema；
    # 待 assistant contracts 扩展该 schema 后迁移。
    "modules/collaboration/merge.py:modules.assistant.schemas": (
        "合并预览复用 assistant 对话 projection schema；待 contracts 扩展后迁移"
    ),
    # public demo 只读判定与账户主体读取为读路径 helper，无业务写入。
    "modules/interaction/source_service.py:modules.account.public_demo": (
        "public demo 只读判定 helper（读路径）"
    ),
    "modules/interaction/streaming.py:modules.account.context": (
        "账户主体读取 helper（读路径）"
    ),
    # 本机 CLI 客户端构造；local_agent 尚无 contracts 面。
    "modules/interaction/tasks.py:modules.local_agent.client": (
        "local_agent 无 contracts 面，CLI 客户端构造直引"
    ),
    # demo 项目复制需要对象级跨域复制（图片资产 deep-copy），已有专门
    # 集成测试；待各域提供复制 facade 后收敛。
    "modules/project/demo_copy.py:modules.account.public_demo": (
        "demo 复制的只读判定 helper"
    ),
    "modules/project/demo_copy.py:modules.world.world_object_images": (
        "demo 复制需要对象级图片资产 deep-copy；待复制 facade 收敛"
    ),
    "modules/project/demo_copy.py:modules.world.map_atlas_storage": (
        "demo 复制需要地图册存储对象 deep-copy；待复制 facade 收敛"
    ),
}


if __name__ == "__main__":
    sys.exit(main())
