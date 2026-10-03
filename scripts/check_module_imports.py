"""跨模块 import 守护门（B2）。

生产代码跨业务模块只能经合法形态导入：contracts/facade 或仅静态再出口这些稳定接口的包成员；ORM 等有限
例外按调用位置显式登记。其余跨模块 import 必须在 EXEMPT_IMPORTS 登记理由，否则失败。

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
import importlib.util
import json
import sys
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_DOC = REPO_ROOT / "docs/architecture/architecture-documents.toml"

# 跨模块 import 的合法形态（相对 modules/ 的导入路径片段）。
_LEGAL_SUFFIXES = ("_contracts", "_facade")


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
    """只有明确的稳定 contracts/facade 入口可直接跨域；models 须逐点豁免。"""
    segments = _import_segments(target)
    if len(segments) < 2 or segments[0] != "modules":
        return True
    last = segments[-1]
    return len(segments) > 2 and (
        last in {"facade", "contracts"} or last.endswith(_LEGAL_SUFFIXES)
    )


def _absolute_from(node: ast.ImportFrom, relative: str) -> str:
    if not node.level:
        return node.module or ""
    package = relative.removesuffix(".py").replace("/", ".")
    if not relative.endswith("/__init__.py"):
        package = package.rpartition(".")[0]
    else:
        package = package.removesuffix(".__init__")
    return importlib.util.resolve_name("." * node.level + (node.module or ""), package)


def _member_target(
    target: str, member: str, backend_root: Path, seen: frozenset[str] = frozenset()
) -> str:
    """解析包成员的静态再出口，绝不 import/执行业务包；未知成员失败关闭。"""
    if target in seen:
        return target
    module_path = backend_root.joinpath(*target.split("."))
    if module_path.with_suffix(".py").is_file():
        return target
    init = module_path / "__init__.py"
    if not init.is_file():
        if not module_path.is_dir() and len(target.split(".")) > 2:
            return target
        return f"{target}.{member}"
    tree = ast.parse(init.read_text(encoding="utf-8"))
    relative = init.relative_to(backend_root).as_posix()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            origin = _absolute_from(node, relative)
            for alias in node.names:
                if (alias.asname or alias.name) == member:
                    return _member_target(
                        origin, alias.name, backend_root, seen | {target}
                    )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.asname or alias.name) == member:
                    return alias.name
    return f"{target}.{member}"


def iter_violations(
    modules: dict[str, tuple[str, ...]], *, exempt: dict[str, str]
) -> list[dict]:
    return iter_violations_for_paths(
        modules,
        sorted((REPO_ROOT / "backend").glob("modules/**/*.py")),
        repo_root=REPO_ROOT,
        exempt=exempt,
    )


def iter_violations_for_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
    exempt: dict[str, str],
) -> list[dict]:
    backend_root = (
        repo_root / "backend" if (repo_root / "backend").is_dir() else repo_root
    )
    violations: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.is_absolute():
            path = repo_root / path
        if path.suffix != ".py":
            continue
        relative = path.relative_to(backend_root).as_posix()
        owner = owning_module(relative, modules)
        if (
            owner is None
            or "/tests/" in f"/{relative}"
            or relative.endswith("_test.py")
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    target = _absolute_from(node, relative)
                    targets = [
                        _member_target(target, alias.name, backend_root)
                        for alias in node.names
                    ]
                elif isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                for target in targets:
                    segments = _import_segments(target)
                    if (
                        len(segments) < 2
                        or segments[0] != "modules"
                        or segments[1] == owner
                    ):
                        continue
                    if is_legal_cross_import(target, modules) or _is_exempt(
                        relative, target, exempt
                    ):
                        continue
                    violations.append(
                        {
                            "path": relative,
                            "line": node.lineno,
                            "target": target,
                            "reason": f"跨模块导入 {target} 不经 contracts/facade 或已登记 DI/有限例外",
                        }
                    )
        except (OSError, SyntaxError, ImportError, ValueError) as exc:
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "target": "",
                    "reason": f"AST/导入解析失败: {exc}",
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
    if not modules:
        print(
            "FAIL architecture-documents.toml 未登记任何 business 组件，"
            "import 门无法工作（fail-closed）",
            file=sys.stderr,
        )
        return 1
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
# 存量实现直引逐点登记；ORM 仅限模型注册兼容出口，不能全局放行。
EXEMPT_IMPORTS: dict[str, str] = {
    "modules/world/models/cocreation.py:modules.assistant.session_models": (
        "ORM metadata 兼容再出口；仅此模型注册位置，不授权业务调用实现"
    ),
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
