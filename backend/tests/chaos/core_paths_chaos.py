"""
Core path chaos baseline.

Coverage focus:
- S1 项目创建与管理
- S2 文件上传与章节导入
- S5 世界对象管理
- S6 大纲与结构管理
- S7 RAG 混合检索
- S8 上下文编译

Run from backend/:
    python -m tests.chaos.core_paths_chaos
"""

from __future__ import annotations

import json
import os
import time
import traceback
from typing import Any

import requests

BASE_URL = os.environ.get("CHAOS_BASE_URL", "http://localhost:8000")
TIMEOUT = 30

CASE_CATALOG: list[dict[str, str]] = [
    {"chaos_case_id": "S1-VAL-001", "path_id": "S1", "layer": "api_chaos"},
    {"chaos_case_id": "S1-DNG-001", "path_id": "S1", "layer": "api_chaos"},
    {"chaos_case_id": "S2-VAL-001", "path_id": "S2", "layer": "api_chaos"},
    {"chaos_case_id": "S2-VAL-002", "path_id": "S2", "layer": "api_chaos"},
    {"chaos_case_id": "S5-ISO-001", "path_id": "S5", "layer": "api_chaos"},
    {"chaos_case_id": "S5-DNG-001", "path_id": "S5", "layer": "api_chaos"},
    {"chaos_case_id": "S6-STA-001", "path_id": "S6", "layer": "api_chaos"},
    {"chaos_case_id": "S7-VAL-001", "path_id": "S7", "layer": "api_chaos"},
    {"chaos_case_id": "S8-VAL-001", "path_id": "S8", "layer": "api_chaos"},
    {"chaos_case_id": "S8-VAL-002", "path_id": "S8", "layer": "api_chaos"},
]

results: list[dict[str, Any]] = []
bugs: list[dict[str, Any]] = []


def record(
    chaos_case_id: str,
    name: str,
    passed: bool,
    detail: str = "",
    bug: dict[str, Any] | None = None,
) -> None:
    results.append(
        {
            "chaos_case_id": chaos_case_id,
            "name": name,
            "passed": passed,
            "detail": detail,
        }
    )
    if bug:
        bugs.append(bug)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {chaos_case_id} {name}")
    if detail:
        print(f"         {detail}")


def report_bug(
    chaos_case_id: str,
    api: str,
    expected: str,
    actual: str,
    status_code: int,
) -> dict[str, Any]:
    print(f"         >>> BUG {chaos_case_id} {api}")
    return {
        "chaos_case_id": chaos_case_id,
        "api": api,
        "expected": expected,
        "actual": actual,
        "status_code": status_code,
    }


class Fixture:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self.novel_id: str | None = None
        self.alt_novel_id: str | None = None
        self.main_entity_id: str | None = None
        self.alt_entity_id: str | None = None

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method,
            f"{BASE_URL}{path}",
            timeout=TIMEOUT,
            **kwargs,
        )

    def create_project(self, title: str) -> str:
        resp = self._req(
            "POST",
            "/api/projects",
            json={"title": title, "genre": "fantasy"},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def create_entity(self, novel_id: str, name: str, entity_type: str) -> str:
        resp = self._req(
            "POST",
            f"/api/world/entities?novel_id={novel_id}",
            json={"name": name, "entity_type": entity_type},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def setup(self) -> None:
        stamp = int(time.time())
        self.novel_id = self.create_project(f"core-chaos-{stamp}")
        self.alt_novel_id = self.create_project(f"core-chaos-alt-{stamp}")
        self.main_entity_id = self.create_entity(self.novel_id, "主世界人物", "character")
        self.alt_entity_id = self.create_entity(
            self.alt_novel_id,
            "异世界地点",
            "location",
        )

    def cleanup(self) -> None:
        for project_id in (self.novel_id, self.alt_novel_id):
            if not project_id:
                continue
            try:
                self._req("DELETE", f"/api/projects/{project_id}")
            except Exception:
                pass
            try:
                self._req("DELETE", f"/api/projects/{project_id}/permanent")
            except Exception:
                pass


def test_s1_empty_title_rejected(f: Fixture) -> None:
    resp = f._req("POST", "/api/projects", json={"title": ""})
    passed = resp.status_code == 422
    if not passed:
        record(
            "S1-VAL-001",
            "空标题创建项目被拒绝",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S1-VAL-001",
                "POST /api/projects",
                "422 validation error",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S1-VAL-001", "空标题创建项目被拒绝", True)


def test_s1_deleted_project_returns_404(f: Fixture) -> None:
    project_id = f.create_project(f"to-delete-{int(time.time())}")
    delete_resp = f._req("DELETE", f"/api/projects/{project_id}")
    get_resp = f._req("GET", f"/api/projects/{project_id}")
    passed = delete_resp.status_code == 204 and get_resp.status_code == 404
    if not passed:
        record(
            "S1-DNG-001",
            "软删除后旧项目入口不可再读取",
            False,
            detail=f"delete={delete_resp.status_code} get={get_resp.status_code}",
            bug=report_bug(
                "S1-DNG-001",
                f"GET /api/projects/{project_id}",
                "404 after soft delete",
                get_resp.text[:200],
                get_resp.status_code,
            ),
        )
        return
    record("S1-DNG-001", "软删除后旧项目入口不可再读取", True)


def test_s2_unsupported_format_rejected(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        "/api/imports/upload",
        data={"novel_id": f.novel_id},
        files={"file": ("book.pdf", b"PDF", "application/pdf")},
    )
    passed = resp.status_code == 400 and "不支持" in resp.text
    if not passed:
        record(
            "S2-VAL-001",
            "不支持格式上传被拒绝",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S2-VAL-001",
                "POST /api/imports/upload",
                "400 unsupported type",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S2-VAL-001", "不支持格式上传被拒绝", True)


def test_s2_empty_file_records_failed(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        "/api/imports/upload",
        data={"novel_id": f.novel_id},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    list_resp = f._req("GET", f"/api/imports?novel_id={f.novel_id}")
    items = list_resp.json().get("items", []) if list_resp.ok else []
    passed = (
        resp.status_code == 400
        and list_resp.status_code == 200
        and len(items) >= 1
        and items[-1].get("status") == "failed"
    )
    if not passed:
        record(
            "S2-VAL-002",
            "空文件导入失败且记录为 failed",
            False,
            detail=(
                f"upload={resp.status_code} list={list_resp.status_code} "
                f"last={json.dumps(items[-1] if items else {}, ensure_ascii=False)}"
            ),
            bug=report_bug(
                "S2-VAL-002",
                "POST /api/imports/upload",
                "400 + failed import record",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S2-VAL-002", "空文件导入失败且记录为 failed", True)


def test_s5_cross_novel_relation_rejected(f: Fixture) -> None:
    assert f.novel_id and f.main_entity_id and f.alt_entity_id
    resp = f._req(
        "POST",
        f"/api/world/relations?novel_id={f.novel_id}",
        json={
            "source_id": f.main_entity_id,
            "target_id": f.alt_entity_id,
            "relation_type": "ally_of",
            "description": "不应跨项目成功",
        },
    )
    passed = resp.status_code in {400, 404}
    if not passed:
        record(
            "S5-ISO-001",
            "跨 novel 关系创建被拒绝",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S5-ISO-001",
                "POST /api/world/relations",
                "400 or 404",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S5-ISO-001", "跨 novel 关系创建被拒绝", True)


def test_s5_rollback_without_history_warns(f: Fixture) -> None:
    assert f.novel_id
    entity_id = f.create_entity(f.novel_id, f"待回滚实体-{int(time.time())}", "item")
    resp = f._req(
        "POST",
        f"/api/world/entities/{entity_id}/rollback?novel_id={f.novel_id}",
        json={"scene_index": 1},
    )
    data = resp.json() if resp.ok else {}
    warnings = data.get("warnings") or []
    passed = resp.status_code == 200 and any("rollback" in w.lower() for w in warnings)
    if not passed:
        record(
            "S5-DNG-001",
            "无回滚历史时返回 warning 而非崩溃",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S5-DNG-001",
                f"POST /api/world/entities/{entity_id}/rollback",
                "200 with warnings",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S5-DNG-001", "无回滚历史时返回 warning 而非崩溃", True)


def test_s6_deleted_scene_not_returned(f: Fixture) -> None:
    assert f.novel_id
    create_resp = f._req(
        "POST",
        f"/api/outline/scenes?novel_id={f.novel_id}",
        json={"scene_index": 1, "title": "待删除 Scene"},
    )
    assert create_resp.status_code == 201, create_resp.text
    scene_id = create_resp.json()["id"]
    delete_resp = f._req(
        "DELETE",
        f"/api/outline/scenes/{scene_id}?novel_id={f.novel_id}",
    )
    get_resp = f._req("GET", f"/api/outline/scenes/{scene_id}?novel_id={f.novel_id}")
    ordered_resp = f._req("GET", f"/api/outline/scenes/ordered?novel_id={f.novel_id}")
    ordered_ids = [item["id"] for item in ordered_resp.json()] if ordered_resp.ok else []
    passed = (
        delete_resp.status_code == 204
        and get_resp.status_code == 404
        and scene_id not in ordered_ids
    )
    if not passed:
        record(
            "S6-STA-001",
            "删除 Scene 后旧 ID 不再可读且排序列表无陈旧项",
            False,
            detail=(
                f"delete={delete_resp.status_code} get={get_resp.status_code} "
                f"ordered_contains={scene_id in ordered_ids}"
            ),
            bug=report_bug(
                "S6-STA-001",
                f"GET /api/outline/scenes/{scene_id}",
                "404 and ordered list without deleted scene",
                get_resp.text[:200],
                get_resp.status_code,
            ),
        )
        return
    record("S6-STA-001", "删除 Scene 后旧 ID 不再可读且排序列表无陈旧项", True)


def test_s7_empty_retrieve_safe(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        f"/api/rag/retrieve?novel_id={f.novel_id}",
        json={"query": "不存在的线索", "top_k": 5},
    )
    data = resp.json() if resp.ok else {}
    passed = (
        resp.status_code == 200 and data.get("total") == 0 and data.get("chunks") == []
    )
    if not passed:
        record(
            "S7-VAL-001",
            "空索引检索返回空结果而非崩溃",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S7-VAL-001",
                "POST /api/rag/retrieve",
                "200 with total=0 and empty chunks",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S7-VAL-001", "空索引检索返回空结果而非崩溃", True)


def test_s8_character_mode_requires_pov(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        "/api/context/compile",
        json={
            "novel_id": f.novel_id,
            "task": "测试角色视角",
            "scope": "arc",
            "reveal_mode": "character",
        },
    )
    passed = resp.status_code == 400 and "viewpoint_character_id" in resp.text
    if not passed:
        record(
            "S8-VAL-001",
            "角色视角缺 POV 被拒绝",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S8-VAL-001",
                "POST /api/context/compile",
                "400 with viewpoint_character_id error",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S8-VAL-001", "角色视角缺 POV 被拒绝", True)


def test_s8_invalid_scope_rejected(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        "/api/context/compile",
        json={
            "novel_id": f.novel_id,
            "task": "非法 scope",
            "scope": "not_a_scope",
            "reveal_mode": "author_safe",
        },
    )
    passed = resp.status_code == 400 and "scope" in resp.text
    if not passed:
        record(
            "S8-VAL-002",
            "非法 scope 被拒绝",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
            bug=report_bug(
                "S8-VAL-002",
                "POST /api/context/compile",
                "400 invalid scope",
                resp.text[:200],
                resp.status_code,
            ),
        )
        return
    record("S8-VAL-002", "非法 scope 被拒绝", True)


def main() -> int:
    print("=== Core path chaos baseline ===")
    print(f"Base URL: {BASE_URL}")
    fixture = Fixture()
    try:
        fixture.setup()
        tests = [
            test_s1_empty_title_rejected,
            test_s1_deleted_project_returns_404,
            test_s2_unsupported_format_rejected,
            test_s2_empty_file_records_failed,
            test_s5_cross_novel_relation_rejected,
            test_s5_rollback_without_history_warns,
            test_s6_deleted_scene_not_returned,
            test_s7_empty_retrieve_safe,
            test_s8_character_mode_requires_pov,
            test_s8_invalid_scope_rejected,
        ]
        for test_fn in tests:
            try:
                test_fn(fixture)
            except Exception as exc:  # noqa: BLE001
                case_id = getattr(test_fn, "__name__", "unknown")
                record(case_id, test_fn.__name__, False, detail=str(exc))
                traceback.print_exc()
    finally:
        fixture.cleanup()

    total = len(results)
    failed = sum(1 for item in results if not item["passed"])
    print("\n=== Summary ===")
    print(f"Total: {total}, Failed: {failed}")
    if bugs:
        print(json.dumps(bugs, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
