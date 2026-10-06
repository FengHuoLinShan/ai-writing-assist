"""跨模块 import 守护门（B2）。

生产代码跨业务模块只能经合法形态导入：contracts/facade 或仅静态再出口这些
稳定接口的包成员；ORM 等有限例外按调用位置显式登记。其余跨模块 import 必须
在 EXEMPT_IMPORTS 登记理由，否则失败。

在形态校验之外，本门禁对模块间依赖**方向**做棘轮统计（AO-1）：有向边、双向对、
顶层双向对、函数内导入与 world 内部 core↔worldbuilding 流量的基线冻结在
``_DEPENDENCY_BASELINE``，任一指标超过基线即失败，只降不升。棘轮统计的是事实
依赖，不论导入形态是否合法、是否豁免。分层目标态见
docs/architecture/README.md 的「模块依赖方向分层（目标态）」。

第三项检查是 facade 薄层门禁（AO-8）：各业务模块（含子包）的 ``facade.py`` 只做
参数适配、稳定返回与 service 委托，禁止出现 SQLAlchemy 直接操作——调用名
``select``/``text``/``delete``/``update``/``insert`` 以及任何 ``.execute(...)``。
查库、聚合与告警编排必须下沉所属模块 service 层；facade 里的再导出、类型标注
与请求模型构造不受影响。

模块清单事实源：docs/architecture/architecture-documents.toml 的 components
（kind="business"）。豁免清单即本文件的 EXEMPT_IMPORTS：键为
``路径:目标模块``（支持 fnmatch 通配），值为必填理由。

用法：
    python scripts/check_module_imports.py [--json] [--directional-json]
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_DOC = REPO_ROOT / "docs/architecture/architecture-documents.toml"

# 跨模块 import 的合法形态（相对 modules/ 的导入路径片段）。
_LEGAL_SUFFIXES = ("_contracts", "_facade")

# world 模块内部 core↔worldbuilding 子包边界（AO-1 棘轮统计，子包更深层级计入）。
_WORLD_CORE_DIR = "modules/world/services/core/"
_WORLD_WORLDBUILDING_DIR = "modules/world/services/worldbuilding/"
_WORLD_CORE_PKG = "modules.world.services.core"
_WORLD_WORLDBUILDING_PKG = "modules.world.services.worldbuilding"

# 依赖方向棘轮基线（AO-1）。数值为 2026-10-06 在提交 e43500d2d 工作树的 AST
# 实测事实（与本门禁同一遍历口径），冻结现状、只降不升：任一指标超过基线即
# FAIL，低于基线时提示可下调。解除依赖后应随手调低对应值
# （function_level_imports 已随 AO-3 插件 SPI 下沉 572→560；AO-4 身份根去业务
# 聚合把 project→world/story/writing 与 account→project 顶层对清零：
# top_level_bidirectional_pairs 17→13，function_level_imports 560→559，后者
# 因 facade SQL 下沉把 project→account 一条函数内导入转正为顶层；AO-8 把
# assistant→project 的批注提案编排移入 comment_proposals 顶层导入：
# 559→558）。
# 分层目标态见 docs/architecture/README.md「模块依赖方向分层（目标态）」。
_DEPENDENCY_BASELINE: dict[str, int] = {
    "directed_edges": 90,
    "bidirectional_pairs": 33,
    "top_level_bidirectional_pairs": 13,
    "function_level_imports": 558,
    "world_core_to_worldbuilding": 23,
    "world_worldbuilding_to_core": 27,
}


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


def _nested_def_node_ids(tree: ast.Module) -> frozenset[int]:
    """位于 FunctionDef/AsyncFunctionDef/ClassDef 体内的节点 id 集合。

    顶层判断标准：不在任何函数/类定义体内；模块级 if/try 等语句块内仍算顶层。
    """
    nested: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(node):
                if child is not node:
                    nested.add(id(child))
    return frozenset(nested)


def _import_targets(node: ast.stmt, relative: str, backend_root: Path) -> list[str]:
    """一条 import 语句解析出的全部目标模块路径（复用形态校验的解析口径）。"""
    if isinstance(node, ast.ImportFrom):
        target = _absolute_from(node, relative)
        return [
            _member_target(target, alias.name, backend_root) for alias in node.names
        ]
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return []


def _matches_package(target: str, package: str) -> bool:
    return target == package or target.startswith(package + ".")


def iter_violations_for_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
    exempt: dict[str, str],
) -> list[dict]:
    violations, _stats, _edges = _analyze_paths(
        modules, paths, repo_root=repo_root, exempt=exempt
    )
    return violations


def iter_directional_stats_for_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
) -> tuple[dict[str, int], list[dict]]:
    """对任意文件集合做方向棘轮统计，返回（指标, 有向边明细）。"""
    _violations, stats, edges = _analyze_paths(
        modules, paths, repo_root=repo_root, exempt={}
    )
    return stats, edges


def analyze_repository(
    *, exempt: dict[str, str]
) -> tuple[list[dict], dict[str, int], list[dict]]:
    """一遍遍历真实仓库，返回（形态违规, 方向指标, 有向边明细）。"""
    return _analyze_paths(
        load_business_modules(),
        sorted((REPO_ROOT / "backend").glob("modules/**/*.py")),
        repo_root=REPO_ROOT,
        exempt=exempt,
    )


def _analyze_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
    exempt: dict[str, str],
) -> tuple[list[dict], dict[str, int], list[dict]]:
    backend_root = (
        repo_root / "backend" if (repo_root / "backend").is_dir() else repo_root
    )
    violations: list[dict] = []
    # 有向边 (owner, 目标模块) → [顶层导入语句数, 函数内导入语句数]
    edge_counts: dict[tuple[str, str], list[int]] = {}
    function_level_imports = 0
    world_core_to_worldbuilding = 0
    world_worldbuilding_to_core = 0
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
            nested_def_ids = _nested_def_node_ids(tree)
            for node in ast.walk(tree):
                targets = _import_targets(node, relative, backend_root)
                if not targets:
                    continue
                # 方向棘轮：统计事实依赖，不论形态是否合法、是否豁免。
                cross_modules = set()
                for target in targets:
                    segments = _import_segments(target)
                    if (
                        len(segments) >= 2
                        and segments[0] == "modules"
                        and segments[1] != owner
                    ):
                        cross_modules.add(segments[1])
                if cross_modules:
                    top_level = id(node) not in nested_def_ids
                    if not top_level:
                        function_level_imports += len(cross_modules)
                    for target_module in cross_modules:
                        counts = edge_counts.setdefault(
                            (owner, target_module), [0, 0]
                        )
                        counts[0 if top_level else 1] += 1
                # world 内部 core↔worldbuilding 语句流量（同一业务模块，不计入跨模块边）。
                if relative.startswith(_WORLD_CORE_DIR) and any(
                    _matches_package(target, _WORLD_WORLDBUILDING_PKG)
                    for target in targets
                ):
                    world_core_to_worldbuilding += 1
                elif relative.startswith(_WORLD_WORLDBUILDING_DIR) and any(
                    _matches_package(target, _WORLD_CORE_PKG) for target in targets
                ):
                    world_worldbuilding_to_core += 1
                # 形态校验（原逻辑不变）。
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
                            "reason": (
                                f"跨模块导入 {target} 不经 contracts/facade"
                                " 或已登记 DI/有限例外"
                            ),
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
    directed = set(edge_counts)
    bidirectional_pairs = 0
    top_level_bidirectional_pairs = 0
    for source, target_module in directed:
        reverse = edge_counts.get((target_module, source))
        if reverse is None or not source < target_module:
            continue
        bidirectional_pairs += 1
        if edge_counts[(source, target_module)][0] > 0 and reverse[0] > 0:
            top_level_bidirectional_pairs += 1
    stats = {
        "directed_edges": len(directed),
        "bidirectional_pairs": bidirectional_pairs,
        "top_level_bidirectional_pairs": top_level_bidirectional_pairs,
        "function_level_imports": function_level_imports,
        "world_core_to_worldbuilding": world_core_to_worldbuilding,
        "world_worldbuilding_to_core": world_worldbuilding_to_core,
    }
    edges = [
        {
            "from": source,
            "to": target_module,
            "top_level": counts[0],
            "function_level": counts[1],
        }
        for (source, target_module), counts in sorted(edge_counts.items())
    ]
    return violations, stats, edges


def _is_exempt(path: str, target: str, exempt: dict[str, str]) -> bool:
    for pattern in exempt:
        file_glob, _, target_glob = pattern.rpartition(":")
        if fnmatch.fnmatch(path, file_glob) and fnmatch.fnmatch(target, target_glob):
            return True
    return False


def check_direction_ratchet(
    stats: dict[str, int], baseline: dict[str, int] | None = None
) -> list[str]:
    """任一指标超过基线即返回失败原因列表；等于或低于基线返回空列表。"""
    limits = _DEPENDENCY_BASELINE if baseline is None else baseline
    failures = []
    for name, limit in limits.items():
        current = stats.get(name, 0)
        if current > limit:
            failures.append(
                f"依赖方向棘轮: {name} 当前 {current} 超过基线 {limit}"
                "（模块间依赖只减不增，须先消除依赖并下调基线再合入）"
            )
    return failures


def _direction_report_lines(
    stats: dict[str, int], baseline: dict[str, int]
) -> list[str]:
    summary = ", ".join(
        f"{name}={stats.get(name, 0)}/{baseline[name]}" for name in baseline
    )
    lines = [f"依赖方向棘轮通过（{summary}）"]
    for name, limit in baseline.items():
        current = stats.get(name, 0)
        if current < limit:
            lines.append(
                f"提示: {name} 当前 {current} 低于基线 {limit}，"
                f"基线可下调至 {current}"
            )
    return lines


# facade 薄层门禁（AO-8）：facade 只适配与委托，禁止 SQLAlchemy 直接操作。
# 裸调用名一律拦（不论 import 来源，fail-closed）；.execute( 覆盖 session 与
# 其他连接对象的直接执行。facade 的再导出、类型标注与请求模型构造不受影响。
_FACADE_SQL_NAMES = frozenset({"select", "text", "delete", "update", "insert"})


def iter_facade_sql_violations_for_paths(
    modules: dict[str, tuple[str, ...]],
    paths,
    *,
    repo_root: Path,
) -> list[dict]:
    """扫描业务模块（含子包）facade.py 内的 SQLAlchemy 直接调用。"""
    backend_root = (
        repo_root / "backend" if (repo_root / "backend").is_dir() else repo_root
    )
    violations: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.is_absolute():
            path = repo_root / path
        if path.name != "facade.py" or path.suffix != ".py":
            continue
        relative = path.relative_to(backend_root).as_posix()
        if owning_module(relative, modules) is None:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError) as exc:
            violations.append(
                {
                    "path": relative,
                    "line": 0,
                    "name": "",
                    "reason": f"facade 薄层门禁: AST 解析失败: {exc}",
                }
            )
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue
            if name in _FACADE_SQL_NAMES or name == "execute":
                violations.append(
                    {
                        "path": relative,
                        "line": node.lineno,
                        "name": name,
                        "reason": (
                            f"facade 薄层门禁: 直接调用 {name}(...)；"
                            "SQLAlchemy 查询与执行须下沉所属模块 service 层，"
                            "facade 仅适配与委托"
                        ),
                    }
                )
    return violations


def analyze_facade_sql() -> list[dict]:
    """对真实仓库全部业务模块 facade.py 做薄层检查。"""
    return iter_facade_sql_violations_for_paths(
        load_business_modules(),
        sorted((REPO_ROOT / "backend").glob("modules/**/*.py")),
        repo_root=REPO_ROOT,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--directional-json",
        action="store_true",
        help="输出方向棘轮指标、基线与有向边明细 JSON",
    )
    args = parser.parse_args(argv)

    modules = load_business_modules()
    if not modules:
        print(
            "FAIL architecture-documents.toml 未登记任何 business 组件，"
            "import 门无法工作（fail-closed）",
            file=sys.stderr,
        )
        return 1
    violations, stats, edges = analyze_repository(exempt=EXEMPT_IMPORTS)
    if args.json:
        print(json.dumps(violations, ensure_ascii=False, indent=2))
    if args.directional_json:
        print(
            json.dumps(
                {
                    "metrics": stats,
                    "baseline": _DEPENDENCY_BASELINE,
                    "directed_edges": edges,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    for item in violations:
        print(
            f"FAIL {item['path']}:{item['line']} {item['reason']}",
            file=sys.stderr,
        )
    direction_failures = check_direction_ratchet(stats)
    for reason in direction_failures:
        print(f"FAIL {reason}", file=sys.stderr)
    facade_failures = analyze_facade_sql()
    for item in facade_failures:
        print(f"FAIL {item['path']}:{item['line']} {item['reason']}", file=sys.stderr)
    if violations:
        print(
            f"{len(violations)} violation(s); 登记豁免须在 "
            f"scripts/check_module_imports.py 的 EXEMPT_IMPORTS 写明理由",
            file=sys.stderr,
        )
        return 1
    if direction_failures:
        print(
            f"{len(direction_failures)} direction ratchet overrun(s); "
            "基线见 scripts/check_module_imports.py 的 _DEPENDENCY_BASELINE，"
            "只降不升",
            file=sys.stderr,
        )
        return 1
    if facade_failures:
        print(
            f"{len(facade_failures)} facade thin-layer violation(s); "
            "SQLAlchemy 操作须下沉所属模块 service 层",
            file=sys.stderr,
        )
        return 1
    print(
        f"module import gate passed "
        f"({len(modules)} business module(s), "
        f"{len(EXEMPT_IMPORTS)} exemption(s), "
        "facade thin-layer check passed)"
    )
    for line in _direction_report_lines(stats, _DEPENDENCY_BASELINE):
        print(line)
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
