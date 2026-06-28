"""
混沌测试 — 地图模块（动态标记、势力范围、聚合状态）

测试范围：
- 动态标记: marker creation, validation, scene filtering, update/delete, defaults
- 势力范围: territory creation, validation, batch, update/delete, focus mode
- 聚合状态: get_state edge cases, markers/territories presence,
  scene filtering, breadcrumbs

运行: 从 backend/ 目录执行
    python -m tests.chaos.map_chaos
"""

from __future__ import annotations

import json
import sys
import time
import traceback
import uuid
from typing import Any

import requests

BASE_URL = "http://localhost:8000"

# 与 ideal-user-paths-chaos-matrix.json 对齐的主路径编号。
# 本文件主要承接 M1-M6 的 API chaos；M7 仍是 spec_only，不在这里实现。
MATRIX_ALIGNED_PATHS = ("M1", "M2", "M3", "M4", "M5", "M6")

# ============================================================
# 测试结果收集
# ============================================================

results: list[dict[str, Any]] = []
bugs: list[dict[str, Any]] = []


def record(
    test_id: int,
    name: str,
    passed: bool,
    detail: str = "",
    bug: dict[str, Any] | None = None,
) -> None:
    results.append({"id": test_id, "name": name, "passed": passed, "detail": detail})
    if bug:
        bugs.append(bug)
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] #{test_id:02d} {name}")
    if detail:
        print(f"         {detail}")


def report_bug(
    priority: str,
    api: str,
    input_data: str,
    expected: str,
    actual: str,
    status_code: int,
    root_cause: str = "",
) -> dict[str, Any]:
    print(f"         >>> BUG [{priority}] {api}")
    return {
        "priority": priority,
        "api": api,
        "input": input_data,
        "expected": expected,
        "actual": actual,
        "status_code": status_code,
        "root_cause": root_cause,
    }


# ============================================================
# 测试夹具 — 创建测试数据
# ============================================================


class TestFixture:
    """管理测试用项目/地图/实体/场景等资源。"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        self.novel_id: str | None = None
        self.map_id: str | None = None
        self.alt_novel_id: str | None = None  # 用于跨 novel 测试
        self.character_entity_id: str | None = None
        self.event_entity_id: str | None = None
        self.item_entity_id: str | None = None
        self.org_entity_id: str | None = None
        self.scene_id: str | None = None
        self.alt_scene_id: str | None = None
        self.alt_entity_id: str | None = None  # 不同 novel 的实体

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{BASE_URL}{path}"
        return self.session.request(method, url, **kwargs)

    def setup(self) -> None:
        print("\n=== 设置测试夹具 ===")

        # 创建主项目
        proj_name = f"map-chaos-{int(time.time())}"
        r = self._req(
            "POST", "/api/projects", json={"title": proj_name, "genre": "fantasy"}
        )
        assert r.status_code == 201, f"Failed to create project: {r.text}"
        self.novel_id = r.json()["id"]
        print(f"  项目 novel_id: {self.novel_id}")

        # 创建另一个项目（用于跨 novel 隔离测试）
        r = self._req(
            "POST",
            "/api/projects",
            json={"title": f"{proj_name}-alt", "genre": "fantasy"},
        )
        assert r.status_code == 201, f"Failed to create alt project: {r.text}"
        self.alt_novel_id = r.json()["id"]
        print(f"  备用 novel_id: {self.alt_novel_id}")

        # 在世界地图项目下创建各种实体
        entities = [
            ("character", "英雄王"),
            ("event", "天启之战"),
            ("item", "圣剑"),
            ("organization", "光明教廷"),
        ]
        for ent_type, ent_name in entities:
            r = self._req(
                "POST",
                f"/api/world/entities?novel_id={self.novel_id}",
                json={"entity_type": ent_type, "name": ent_name},
            )
            assert r.status_code == 201, f"Failed to create entity {ent_name}: {r.text}"
            eid = r.json()["id"]
            if ent_type == "character":
                self.character_entity_id = eid
            elif ent_type == "event":
                self.event_entity_id = eid
            elif ent_type == "item":
                self.item_entity_id = eid
            elif ent_type == "organization":
                self.org_entity_id = eid
            print(f"  实体 {ent_name} ({ent_type}): {eid}")

        # 在另一个项目创建实体（用于跨 novel 隔离测试）
        r = self._req(
            "POST",
            f"/api/world/entities?novel_id={self.alt_novel_id}",
            json={"entity_type": "character", "name": "异世界角色"},
        )
        assert r.status_code == 201
        self.alt_entity_id = r.json()["id"]
        print(f"  异项目实体: {self.alt_entity_id}")

        # 创建地图 (20x20 world)
        r = self._req(
            "POST",
            f"/api/world/maps?novel_id={self.novel_id}",
            json={
                "name": "混沌测试地图",
                "map_type": "world",
                "grid_width": 20,
                "grid_height": 20,
                "hex_size": 30,
                "template": "blank",
            },
        )
        assert r.status_code == 201, f"Failed to create map: {r.text}"
        self.map_id = r.json()["id"]
        print(f"  地图 map_id: {self.map_id}")

        # 在另一个项目创建地图（非本项目的，用于跨 novel 测试）
        r = self._req(
            "POST",
            f"/api/world/maps?novel_id={self.alt_novel_id}",
            json={
                "name": "异世界地图",
                "map_type": "world",
                "grid_width": 10,
                "grid_height": 10,
            },
        )
        assert r.status_code == 201
        self.alt_map_id = r.json()["id"]
        print(f"  异项目地图: {self.alt_map_id}")

        # 创建 Scene
        r = self._req(
            "POST",
            f"/api/outline/scenes?novel_id={self.novel_id}",
            json={"scene_index": 1, "title": "测试场景1"},
        )
        assert r.status_code == 201, f"Failed to create scene: {r.text}"
        self.scene_id = r.json()["id"]
        print(f"  Scene ID: {self.scene_id}")

        r = self._req(
            "POST",
            f"/api/outline/scenes?novel_id={self.novel_id}",
            json={"scene_index": 2, "title": "测试场景2"},
        )
        assert r.status_code == 201
        self.scene_id_2 = r.json()["id"]
        print(f"  Scene2 ID: {self.scene_id_2}")

        # 在异项目创建 scene（用于跨 novel 测试）
        r = self._req(
            "POST",
            f"/api/outline/scenes?novel_id={self.alt_novel_id}",
            json={"scene_index": 1, "title": "异世界场景"},
        )
        assert r.status_code == 201
        self.alt_scene_id = r.json()["id"]
        print(f"  异项目 Scene: {self.alt_scene_id}")

    def cleanup(self) -> None:
        print("\n=== 清理测试夹具 ===")
        # Demo 阶段，删除项目级联删除所有关联数据
        if self.novel_id:
            r = self._req("DELETE", f"/api/projects/{self.novel_id}")
            print(f"  删除主项目: {r.status_code}")
        if self.alt_novel_id:
            r = self._req("DELETE", f"/api/projects/{self.alt_novel_id}")
            print(f"  删除备用项目: {r.status_code}")


# ============================================================
# 测试函数（每个测试点对应一个独立函数）
# ============================================================


def test_marker_create_character(f: TestFixture) -> None:
    """1. 创建 marker_type="character" 的标记"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 5,
            "hex_r": 5,
            "label": "英雄王的位置",
        },
    )
    if r.status_code != 201:
        record(
            1,
            "创建 character 标记",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/markers",
                json.dumps(
                    {
                        "entity_id": f.character_entity_id,
                        "marker_type": "character",
                        "hex_q": 5,
                        "hex_r": 5,
                    }
                ),
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return

    data = r.json()
    passed = (
        data["marker_type"] == "character"
        and data["entity_id"] == f.character_entity_id
        and data["visible"] is True
    )
    f.marker_char_id = data["id"]
    record(1, "创建 character 标记", passed)


def test_marker_create_event(f: TestFixture) -> None:
    """2. 创建 marker_type="event" 的标记"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.event_entity_id,
            "marker_type": "event",
            "hex_q": 3,
            "hex_r": 7,
        },
    )
    if r.status_code != 201:
        record(
            2,
            "创建 event 标记",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/markers",
                f"entity_id={f.event_entity_id}, marker_type=event",
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return
    data = r.json()
    passed = data["marker_type"] == "event" and data["entity_id"] == f.event_entity_id
    f.marker_event_id = data["id"]
    record(2, "创建 event 标记", passed)


def test_marker_create_item(f: TestFixture) -> None:
    """3. 创建 marker_type="item" 的标记"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.item_entity_id,
            "marker_type": "item",
            "hex_q": 10,
            "hex_r": 10,
        },
    )
    if r.status_code != 201:
        record(
            3,
            "创建 item 标记",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/markers",
                f"entity_id={f.item_entity_id}, marker_type=item",
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return
    data = r.json()
    passed = data["marker_type"] == "item" and data["entity_id"] == f.item_entity_id
    f.marker_item_id = data["id"]
    record(3, "创建 item 标记", passed)


def test_marker_invalid_type(f: TestFixture) -> None:
    """4. marker_type='invalid_type' 返回 422"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "invalid_type",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    passed = r.status_code == 422
    if not passed:
        record(
            4,
            "无效 marker_type 返回 422",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/markers",
                'marker_type="invalid_type"',
                "422 Validation Error",
                f"{r.status_code} {r.text}",
                r.status_code,
                "marker_type 白名单校验未生效",
            ),
        )
    else:
        record(4, "无效 marker_type 返回 422", True)


def test_marker_nonexistent_entity(f: TestFixture) -> None:
    """5. entity_id 不存在返回 404（或 400）"""
    fake_id = str(uuid.uuid4())
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": fake_id,
            "marker_type": "character",
            "hex_q": 2,
            "hex_r": 2,
        },
    )
    passed = r.status_code in (404, 400)
    if not passed:
        record(
            5,
            "不存在的 entity_id 返回 404/400",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/markers",
                f"entity_id={fake_id} (不存在)",
                "404 或 400",
                f"{r.status_code} {r.text}",
                r.status_code,
                "不存在实体的标记创建应被拒绝",
            ),
        )
    else:
        record(5, "不存在的 entity_id 返回 404/400", True)


def test_marker_entity_wrong_novel(f: TestFixture) -> None:
    """6. entity_id 属于不同 novel 返回 404"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.alt_entity_id,
            "marker_type": "character",
            "hex_q": 2,
            "hex_r": 2,
        },
    )
    passed = r.status_code == 404
    if not passed:
        record(
            6,
            "跨 novel entity_id 返回 404",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/markers",
                f"entity_id={f.alt_entity_id} (不同 novel)",
                "404",
                f"{r.status_code} {r.text}",
                r.status_code,
                "novel_id 隔离校验可能缺失",
            ),
        )
    else:
        record(6, "跨 novel entity_id 返回 404", True)


def test_marker_cross_novel_delete(f: TestFixture) -> None:
    """7. 跨 novel 删除标记返回 404"""
    # 先在主项目建标记，然后用异项目 novel_id 删除
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 7,
            "hex_r": 7,
        },
    )
    if r.status_code != 201:
        record(7, "跨 novel 删除标记返回 404", False, detail="前置创建标记失败")
        return
    mid = r.json()["id"]

    # 用异项目的 novel_id 删除
    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/markers/{mid}?novel_id={f.alt_novel_id}",
    )
    passed = r.status_code == 404
    if not passed:
        record(
            7,
            "跨 novel 删除标记返回 404",
            False,
            bug=report_bug(
                "P1",
                f"DELETE /api/world/maps/{f.map_id}/markers/{mid}",
                f"novel_id={f.alt_novel_id} (不同 novel)",
                "404",
                f"{r.status_code} {r.text}",
                r.status_code,
                "novel_id 隔离校验可能缺失",
            ),
        )
    else:
        record(7, "跨 novel 删除标记返回 404", True)

    # 恢复：用正确 novel_id 删掉
    f._req("DELETE", f"/api/world/maps/{f.map_id}/markers/{mid}?novel_id={f.novel_id}")


def test_marker_scene_id_filter(f: TestFixture) -> None:
    """8. 设置 start_scene_id 后，按该 scene_id 查询能命中标记"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 8,
            "hex_r": 8,
            "start_scene_id": f.scene_id,
        },
    )
    if r.status_code != 201:
        record(8, "start_scene_id 场景过滤", False, detail="前置创建标记失败")
        return
    marker_id = r.json()["id"]

    # 查询时传 scene_id
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}&scene_id={f.scene_id}",
    )
    if r.status_code != 200:
        record(
            8,
            "start_scene_id 场景过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/markers",
                f"scene_id={f.scene_id}",
                "200",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return

    ids = [m["id"] for m in r.json()]
    passed = marker_id in ids
    if not passed:
        record(
            8,
            "start_scene_id 场景过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/markers",
                f"scene_id={f.scene_id}",
                f"标记 {marker_id} 应出现在结果中",
                f"未命中，结果IDs={ids}",
                200,
                "start_scene_id 场景过滤逻辑可能有误",
            ),
        )
    else:
        record(8, "start_scene_id 场景过滤", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}"
    )


def test_marker_scene_index_filter(f: TestFixture) -> None:
    """9. 设置 start_scene_index/end_scene_index 后，按中间 scene 查询能命中标记"""
    # 标记覆盖 scene_index 范围 1~2
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.event_entity_id,
            "marker_type": "event",
            "hex_q": 9,
            "hex_r": 9,
            "start_scene_index": 1,
            "end_scene_index": 2,
        },
    )
    if r.status_code != 201:
        record(9, "scene_index 范围过滤", False, detail="前置创建标记失败")
        return
    marker_id = r.json()["id"]

    # 按 scene_id=场景1 查询（应命中，因为 scene_index=1 在范围内）
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}&scene_id={f.scene_id}",
    )
    if r.status_code != 200:
        record(
            9,
            "scene_index 范围过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/markers",
                f"scene_id={f.scene_id} (index=1)",
                "200",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return

    ids = [m["id"] for m in r.json()]
    passed = marker_id in ids
    if not passed:
        record(
            9,
            "scene_index 范围过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/markers",
                f"scene_id={f.scene_id} (index=1, 应在 1..2 范围内)",
                f"标记 {marker_id} 应出现",
                f"未命中, ids={ids}",
                200,
                "start_scene_index/end_scene_index 范围查询异常",
            ),
        )
    else:
        record(9, "scene_index 范围过滤", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}"
    )


def test_marker_no_scene_limit(f: TestFixture) -> None:
    """10. 没有 scene 范围限制的标记在所有查询中都能命中"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.item_entity_id,
            "marker_type": "item",
            "hex_q": 11,
            "hex_r": 11,
        },
    )
    if r.status_code != 201:
        record(10, "无 scene 范围标记可查询", False, detail="前置创建标记失败")
        return
    marker_id = r.json()["id"]

    # 带 scene_id 查询
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}&scene_id={f.scene_id}",
    )
    passed = r.status_code == 200 and marker_id in [m["id"] for m in r.json()]
    if not passed:
        record(
            10,
            "无 scene 范围标记可查询",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/markers",
                f"scene_id={f.scene_id}",
                f"无范围标记 {marker_id} 应始终命中",
                f"未命中或 {r.status_code}",
                r.status_code,
                "无 scene 范围标记未在全部查询中返回",
            ),
        )
    else:
        record(10, "无 scene 范围标记可查询", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}"
    )


def test_marker_update(f: TestFixture) -> None:
    """11. PATCH 更新标记的 label / offset_x / offset_y / visible"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 12,
            "hex_r": 12,
            "label": "旧标签",
            "offset_x": 0,
            "offset_y": 0,
            "visible": True,
        },
    )
    if r.status_code != 201:
        record(11, "PATCH 更新标记", False, detail="前置创建失败")
        return
    marker_id = r.json()["id"]

    r = f._req(
        "PATCH",
        f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}",
        json={
            "label": "新标签",
            "offset_x": 0.5,
            "offset_y": -0.3,
            "visible": False,
        },
    )
    passed = (
        r.status_code == 200
        and r.json()["label"] == "新标签"
        and r.json()["offset_x"] == 0.5
        and r.json()["offset_y"] == -0.3
        and r.json()["visible"] is False
    )
    if not passed:
        record(
            11,
            "PATCH 更新标记",
            False,
            bug=report_bug(
                "P0",
                f"PATCH /api/world/maps/{f.map_id}/markers/{marker_id}",
                '{"label":"新标签","offset_x":0.5,"offset_y":-0.3,"visible":false}',
                "200 + 字段值更新",
                f"{r.status_code} {r.text}",
                r.status_code,
                "标记更新字段未正确传递",
            ),
        )
    else:
        record(11, "PATCH 更新标记", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}"
    )


def test_marker_delete(f: TestFixture) -> None:
    """12. DELETE 删除标记"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 13,
            "hex_r": 13,
        },
    )
    if r.status_code != 201:
        record(12, "DELETE 删除标记", False, detail="前置创建失败")
        return
    marker_id = r.json()["id"]

    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}",
    )
    passed = r.status_code == 204
    if not passed:
        record(
            12,
            "DELETE 删除标记",
            False,
            bug=report_bug(
                "P0",
                f"DELETE /api/world/maps/{f.map_id}/markers/{marker_id}",
                "",
                "204 No Content",
                f"{r.status_code} {r.text}",
                r.status_code,
                "删除标记未返回 204",
            ),
        )
    else:
        record(12, "DELETE 删除标记", True)

    # 验证已删除
    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/markers/{marker_id}?novel_id={f.novel_id}",
    )
    if r.status_code != 404:
        record(
            12,
            "DELETE 删除标记（再次删除应 404）",
            False,
            bug=report_bug(
                "P1",
                f"DELETE /api/world/maps/{f.map_id}/markers/{marker_id} (再次删除)",
                "",
                "404",
                f"{r.status_code} {r.text}",
                r.status_code,
                "已删除标记再次删除应返回 404",
            ),
        )
    else:
        record(12, "DELETE 删除标记（再次删除应 404）", True)


def test_marker_default_offsets(f: TestFixture) -> None:
    """13. 标记的 offset_x/offset_y 不传时使用默认值 0"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 14,
            "hex_r": 14,
        },
    )
    if r.status_code != 201:
        record(
            13,
            "offset 默认值 0",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/markers",
                "无 offset_x/offset_y",
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return
    data = r.json()
    passed = data["offset_x"] == 0 and data["offset_y"] == 0
    if not passed:
        record(
            13,
            "offset 默认值 0",
            False,
            bug=report_bug(
                "P2",
                f"POST /api/world/maps/{f.map_id}/markers",
                "无 offset_x/offset_y",
                "offset_x=0, offset_y=0",
                f"offset_x={data['offset_x']}, offset_y={data['offset_y']}",
                201,
                "offset 默认值未正确设置",
            ),
        )
    else:
        record(13, "offset 默认值 0", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{data['id']}?novel_id={f.novel_id}"
    )


def test_marker_default_visible(f: TestFixture) -> None:
    """14. visible 字段默认为 true"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/markers?novel_id={f.novel_id}",
        json={
            "entity_id": f.character_entity_id,
            "marker_type": "character",
            "hex_q": 15,
            "hex_r": 15,
        },
    )
    if r.status_code != 201:
        record(
            14,
            "visible 默认值 true",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/markers",
                "无 visible 字段",
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return
    data = r.json()
    passed = data["visible"] is True
    if not passed:
        record(
            14,
            "visible 默认值 true",
            False,
            bug=report_bug(
                "P2",
                f"POST /api/world/maps/{f.map_id}/markers",
                "无 visible",
                "visible=true",
                f"visible={data['visible']}",
                201,
                "visible 默认值未正确设置",
            ),
        )
    else:
        record(14, "visible 默认值 true", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/markers/{data['id']}?novel_id={f.novel_id}"
    )


# ============================================================
# 势力范围测试
# ============================================================


def test_territory_create_organization(f: TestFixture) -> None:
    """15. 用 organization 实体创建势力范围成功"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [
                {"hex_q": 5, "hex_r": 5},
                {"hex_q": 5, "hex_r": 6},
                {"hex_q": 6, "hex_r": 5},
            ],
        },
    )
    if r.status_code != 201:
        record(
            15,
            "创建组织势力范围",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/territories",
                f"faction_entity_id={f.org_entity_id}",
                "201 Created",
                f"{r.status_code} {r.text}",
                r.status_code,
                "组织势力范围创建失败",
            ),
        )
        return

    data = r.json()
    passed = (
        isinstance(data, list)
        and len(data) == 3
        and all(t["faction_entity_id"] == f.org_entity_id for t in data)
    )
    if not passed:
        record(
            15,
            "创建组织势力范围",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/territories",
                "3 个 hex",
                "list of 3 territories",
                f"count={len(data) if isinstance(data, list) else type(data)}",
                r.status_code,
                "势力范围返回格式/数量异常",
            ),
        )
    else:
        record(15, "创建组织势力范围", True)

    # 记住创建的 territory ids
    f.territory_ids = [t["id"] for t in (data if isinstance(data, list) else [])]


def test_territory_non_organization(f: TestFixture) -> None:
    """16. 用非 organization 实体创建势力范围返回 400"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.character_entity_id,
            "hexes": [{"hex_q": 3, "hex_r": 3}],
        },
    )
    passed = r.status_code == 400
    if not passed:
        record(
            16,
            "非组织实体创建势力范围拒接",
            False,
            bug=report_bug(
                "P0",
                f"POST /api/world/maps/{f.map_id}/territories",
                "entity_type=character",
                "400 Bad Request",
                f"{r.status_code} {r.text}",
                r.status_code,
                "非组织实体创建势力范围应返回 400",
            ),
        )
    else:
        record(16, "非组织实体创建势力范围拒接", True)


def test_territory_hex_out_of_bounds(f: TestFixture) -> None:
    """17. 势力范围 hex 越界返回 400"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [{"hex_q": 100, "hex_r": 100}],
        },
    )
    passed = r.status_code == 400
    if not passed:
        record(
            17,
            "hex 越界返回 400",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/territories",
                "hex_q=100, hex_r=100 (grid 20x20)",
                "400 Bad Request",
                f"{r.status_code} {r.text}",
                r.status_code,
                "hex 越界校验未生效",
            ),
        )
    else:
        record(17, "hex 越界返回 400", True)


def test_territory_batch_create(f: TestFixture) -> None:
    """18. 批量创建势力范围"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [
                {"hex_q": 7, "hex_r": 7},
                {"hex_q": 7, "hex_r": 8},
                {"hex_q": 8, "hex_r": 7},
                {"hex_q": 8, "hex_r": 8},
            ],
        },
    )
    passed = r.status_code == 201 and len(r.json()) == 4
    if not passed:
        record(
            18,
            "批量创建势力范围",
            False,
            bug=report_bug(
                "P1",
                f"POST /api/world/maps/{f.map_id}/territories",
                "4 hexes",
                "201 + 4 territories",
                f"{r.status_code} {r.text}",
                r.status_code,
                "批量创建势力范围异常",
            ),
        )
    else:
        record(18, "批量创建势力范围", True)

    f.territory_batch_ids = [t["id"] for t in r.json()]


def test_territory_update_style(f: TestFixture) -> None:
    """19. PATCH 更新单格 style_override"""
    # 先创建
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [{"hex_q": 9, "hex_r": 9}],
        },
    )
    if r.status_code != 201 or not r.json():
        record(19, "PATCH 更新势力范围 style", False, detail="前置创建失败")
        return
    tid = r.json()[0]["id"]

    r = f._req(
        "PATCH",
        f"/api/world/maps/{f.map_id}/territories/{tid}?novel_id={f.novel_id}",
        json={"style_override": {"fill": "#ff0000", "opacity": 0.8}},
    )
    passed = r.status_code == 200 and r.json()["style_override"] == {
        "fill": "#ff0000",
        "opacity": 0.8,
    }
    if not passed:
        record(
            19,
            "PATCH 更新势力范围 style",
            False,
            bug=report_bug(
                "P1",
                f"PATCH /api/world/maps/{f.map_id}/territories/{tid}",
                '{"style_override": {"fill":"#ff0000","opacity":0.8}}',
                "200 + style_override 更新",
                f"{r.status_code} {r.text}",
                r.status_code,
                "势力范围 style_override 更新失败",
            ),
        )
    else:
        record(19, "PATCH 更新势力范围 style", True)

    f._req(
        "DELETE", f"/api/world/maps/{f.map_id}/territories/{tid}?novel_id={f.novel_id}"
    )


def test_territory_delete_single(f: TestFixture) -> None:
    """20. DELETE 删除单格势力范围"""
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [{"hex_q": 10, "hex_r": 10}],
        },
    )
    if r.status_code != 201 or not r.json():
        record(20, "DELETE 单格势力范围", False, detail="前置创建失败")
        return
    tid = r.json()[0]["id"]

    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories/{tid}?novel_id={f.novel_id}",
    )
    passed = r.status_code == 204
    if not passed:
        record(
            20,
            "DELETE 单格势力范围",
            False,
            bug=report_bug(
                "P0",
                f"DELETE /api/world/maps/{f.map_id}/territories/{tid}",
                "",
                "204 No Content",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
    else:
        record(20, "DELETE 单格势力范围", True)

    # 再次删除验证 404
    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories/{tid}?novel_id={f.novel_id}",
    )
    if r.status_code != 404:
        record(
            20,
            "DELETE 势力范围（再次删除 404）",
            False,
            bug=report_bug(
                "P1",
                f"DELETE /api/world/maps/{f.map_id}/territories/{tid} (again)",
                "",
                "404",
                f"{r.status_code}",
                r.status_code,
            ),
        )
    else:
        record(20, "DELETE 势力范围（再次删除 404）", True)


def test_territory_delete_by_faction(f: TestFixture) -> None:
    """21. delete_by_faction 返回正确删除行数"""
    # 先创建一批势力范围
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [
                {"hex_q": 12, "hex_r": 12},
                {"hex_q": 12, "hex_r": 13},
                {"hex_q": 13, "hex_r": 12},
            ],
        },
    )
    if r.status_code != 201:
        record(21, "delete_by_faction 删除行数", False, detail="前置创建失败")
        return

    r = f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}&faction_entity_id={f.org_entity_id}",
    )
    # 注意：API 返回 204，不返回行数。我们验证返回码和删除后列表为空。
    passed = r.status_code == 204
    if not passed:
        record(
            21,
            "delete_by_faction 删除行数",
            False,
            bug=report_bug(
                "P0",
                (
                    f"DELETE /api/world/maps/{f.map_id}/territories"
                    f"?faction_entity_id={f.org_entity_id}"
                ),
                "",
                "204 No Content",
                f"{r.status_code} {r.text}",
                r.status_code,
                "delete_by_faction 失败",
            ),
        )
    else:
        record(21, "delete_by_faction 删除行数", True)

    # 确认已删除
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
    )
    if r.status_code == 200:
        org_territories = [
            t for t in r.json() if t.get("faction_entity_id") == f.org_entity_id
        ]
        if len(org_territories) > 0:
            record(
                21,
                "delete_by_faction 验证删除",
                False,
                bug=report_bug(
                    "P1",
                    f"GET /api/world/maps/{f.map_id}/territories",
                    "验证删除后 organization 势力范围应为空",
                    "0",
                    f"{len(org_territories)}",
                    200,
                    "delete_by_faction 未实际删除",
                ),
            )
        else:
            record(21, "delete_by_faction 验证删除", True)


def test_territory_focus_mode(f: TestFixture) -> None:
    """22. 聚焦模式只返回指定组织的势力范围"""
    # 清理之前的势力范围
    f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}&faction_entity_id={f.org_entity_id}",
    )

    # 为组织创建势力范围
    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": f.org_entity_id,
            "hexes": [{"hex_q": 14, "hex_r": 14}, {"hex_q": 15, "hex_r": 15}],
        },
    )
    if r.status_code != 201:
        record(22, "聚焦模式势力范围过滤", False, detail="前置创建失败")
        return

    # 为某个 character 也创建势力范围（虽不应是 organization，但测试过滤）
    # 创建另一个组织
    r = f._req(
        "POST",
        f"/api/world/entities?novel_id={f.novel_id}",
        json={"entity_type": "organization", "name": "第二组织"},
    )
    if r.status_code != 201:
        record(22, "聚焦模式势力范围过滤", False, detail="前置创建第二组织失败")
        return
    org2_id = r.json()["id"]

    r = f._req(
        "POST",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}",
        json={
            "faction_entity_id": org2_id,
            "hexes": [{"hex_q": 16, "hex_r": 16}],
        },
    )
    if r.status_code != 201:
        record(22, "聚焦模式势力范围过滤", False, detail="前置为第二组织创建势力范围失败")
        return

    # 聚焦模式查询第一个组织
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/focus?novel_id={f.novel_id}&faction_entity_id={f.org_entity_id}",
    )
    if r.status_code != 200:
        record(
            22,
            "聚焦模式势力范围过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/focus",
                f"faction_entity_id={f.org_entity_id}",
                "200",
                f"{r.status_code} {r.text}",
                r.status_code,
            ),
        )
        return

    data = r.json()
    # 只应包含 org 的势力范围
    territories = data.get("territories", [])
    faction_ids = set(t["faction_entity_id"] for t in territories)
    passed = len(faction_ids) == 1 and f.org_entity_id in faction_ids
    if not passed:
        record(
            22,
            "聚焦模式势力范围过滤",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/focus",
                f"faction_entity_id={f.org_entity_id}",
                f"只含组织 {f.org_entity_id} 的势力范围",
                f"faction_ids={faction_ids}",
                200,
                "聚焦模式未正确过滤势力范围",
            ),
        )
    else:
        record(22, "聚焦模式势力范围过滤", True)

    # 清理
    f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}&faction_entity_id={f.org_entity_id}",
    )
    f._req(
        "DELETE",
        f"/api/world/maps/{f.map_id}/territories?novel_id={f.novel_id}&faction_entity_id={org2_id}",
    )


def test_focus_mode_other_fields(f: TestFixture) -> None:
    """23. 聚焦模式其他字段保持完整"""
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/focus?novel_id={f.novel_id}&faction_entity_id={f.org_entity_id}",
    )
    if r.status_code != 200:
        record(23, "聚焦模式字段完整性", False, detail="聚焦模式不可用")
        return

    data = r.json()
    required_keys = [
        "map",
        "breadcrumbs",
        "tiles",
        "location_bindings",
        "markers",
        "territories",
    ]
    missing = [k for k in required_keys if k not in data]
    passed = len(missing) == 0
    if not passed:
        record(
            23,
            "聚焦模式字段完整性",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/focus",
                "verify all fields present",
                f"{required_keys}",
                f"missing: {missing}",
                200,
                "聚焦模式缺少字段",
            ),
        )
    else:
        record(23, "聚焦模式字段完整性", True)


# ============================================================
# 聚合状态测试
# ============================================================


def test_get_state_nonexistent_map(f: TestFixture) -> None:
    """24. get_state 对不存在的地图返回 404"""
    r = f._req(
        "GET",
        f"/api/world/maps/{str(uuid.uuid4())}/state?novel_id={f.novel_id}",
    )
    passed = r.status_code == 404
    if not passed:
        record(
            24,
            "不存在地图 get_state 返回 404",
            False,
            bug=report_bug(
                "P0",
                "GET /api/world/maps/<fake>/state",
                "不存在的地图 ID",
                "404",
                f"{r.status_code} {r.text}",
                r.status_code,
                "不存在地图的 get_state 未正确返回 404",
            ),
        )
    else:
        record(24, "不存在地图 get_state 返回 404", True)


def test_state_markers_and_territories_always_list(f: TestFixture) -> None:
    """25. markers 和 territories 字段始终存在且为 list"""
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/state?novel_id={f.novel_id}",
    )
    if r.status_code != 200:
        record(
            25,
            "state markers/territories 始终为 list",
            False,
            detail=f"get_state 失败 {r.status_code}",
        )
        return

    data = r.json()
    markers_ok = isinstance(data.get("markers"), list)
    territories_ok = isinstance(data.get("territories"), list)
    passed = markers_ok and territories_ok
    if not passed:
        detail_parts = []
        if not markers_ok:
            detail_parts.append(f"markers type={type(data.get('markers'))}")
        if not territories_ok:
            detail_parts.append(f"territories type={type(data.get('territories'))}")
        record(
            25,
            "state markers/territories 始终为 list",
            False,
            bug=report_bug(
                "P0",
                f"GET /api/world/maps/{f.map_id}/state",
                "期望 markers/territories 为 list",
                "list",
                "; ".join(detail_parts),
                200,
                "聚合状态中 markers 或 territories 可能为 null",
            ),
        )
    else:
        record(25, "state markers/territories 始终为 list", True)


def test_state_with_scene_id(f: TestFixture) -> None:
    """26. 带 scene_id 查询时 scene 字段包含场景信息"""
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/state?novel_id={f.novel_id}&scene_id={f.scene_id}",
    )
    if r.status_code != 200:
        record(
            26, "state 带 scene_id 查询", False, detail=f"get_state 失败 {r.status_code}"
        )
        return

    data = r.json()
    scene = data.get("scene")
    if scene is None:
        record(
            26,
            "state 带 scene_id 查询",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/state?scene_id={f.scene_id}",
                f"scene_id={f.scene_id}",
                "scene 字段包含场景信息",
                "scene is None",
                200,
                "带 scene_id 查询时 scene 字段未填充",
            ),
        )
        return

    passed = scene.get("id") == f.scene_id and scene.get("index") is not None
    if not passed:
        record(
            26,
            "state 带 scene_id 查询",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{f.map_id}/state?scene_id={f.scene_id}",
                f"scene_id={f.scene_id}",
                "scene.id 匹配且 scene.index 存在",
                f"scene={scene}",
                200,
                "scene 字段内容异常",
            ),
        )
    else:
        record(26, "state 带 scene_id 查询", True)


def test_state_without_scene_id(f: TestFixture) -> None:
    """27. 不带 scene_id 时 scene 字段为 null"""
    r = f._req(
        "GET",
        f"/api/world/maps/{f.map_id}/state?novel_id={f.novel_id}",
    )
    if r.status_code != 200:
        record(
            27,
            "state 无 scene_id scene 为 null",
            False,
            detail=f"get_state 失败 {r.status_code}",
        )
        return

    passed = r.json().get("scene") is None
    if not passed:
        record(
            27,
            "state 无 scene_id scene 为 null",
            False,
            bug=report_bug(
                "P2",
                f"GET /api/world/maps/{f.map_id}/state",
                "无 scene_id",
                "scene is None",
                f"scene={r.json().get('scene')}",
                200,
                "无 scene_id 时 scene 字段不为 null",
            ),
        )
    else:
        record(27, "state 无 scene_id scene 为 null", True)


def test_state_filter_types(f: TestFixture) -> None:
    """28. filter_types 传 all/location/任意字符串均不导致后端错误"""
    for ft in ("all", "location", "nonexistent_filter_type"):
        r = f._req(
            "GET",
            f"/api/world/maps/{f.map_id}/state?novel_id={f.novel_id}&filter_types={ft}",
        )
        if r.status_code != 200:
            record(
                28,
                f"filter_types={ft} 不报错",
                False,
                bug=report_bug(
                    "P1",
                    f"GET /api/world/maps/{f.map_id}/state?filter_types={ft}",
                    f"filter_types={ft}",
                    "200",
                    f"{r.status_code} {r.text}",
                    r.status_code,
                    "filter_types 传未知值导致后端错误",
                ),
            )
            return
    record(28, "filter_types 任意值不报错", True)


def test_state_breadcrumbs(f: TestFixture) -> None:
    """29. breadcrumbs 包含从顶层到当前地图的路径"""
    # 创建子地图测试 breadcrumbs
    r = f._req(
        "POST",
        f"/api/world/maps?novel_id={f.novel_id}",
        json={
            "name": "子地图",
            "map_type": "region",
            "grid_width": 10,
            "grid_height": 10,
            "parent_map_id": f.map_id,
        },
    )
    if r.status_code != 201:
        record(29, "breadcrumbs 层级路径", False, detail="子地图创建失败")
        return
    child_map_id = r.json()["id"]

    # 查子地图的 state
    r = f._req(
        "GET",
        f"/api/world/maps/{child_map_id}/state?novel_id={f.novel_id}",
    )
    if r.status_code != 200:
        record(
            29,
            "breadcrumbs 层级路径",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{child_map_id}/state",
                "",
                "200",
                f"{r.status_code}",
                r.status_code,
            ),
        )
        return

    data = r.json()
    crumbs = data.get("breadcrumbs", [])
    crumb_ids = [c["id"] for c in crumbs]
    passed = (
        len(crumbs) >= 2 and crumb_ids[0] == f.map_id and crumb_ids[-1] == child_map_id
    )
    if not passed:
        record(
            29,
            "breadcrumbs 层级路径",
            False,
            bug=report_bug(
                "P1",
                f"GET /api/world/maps/{child_map_id}/state",
                f"父 {f.map_id} -> 子 {child_map_id}",
                f"crumbs=[{f.map_id}, ..., {child_map_id}]",
                f"crumbs={crumb_ids}",
                200,
                "breadcrumbs 路径不正确",
            ),
        )
    else:
        record(29, "breadcrumbs 层级路径", True)

    # 清理子地图
    f._req("DELETE", f"/api/world/maps/{child_map_id}?novel_id={f.novel_id}")


# ============================================================
# 主入口
# ============================================================


def main() -> int:
    global results, bugs
    results = []
    bugs = []

    fixture = TestFixture()
    try:
        fixture.setup()

        all_tests = [
            # Dynamic markers (1-14)
            test_marker_create_character,
            test_marker_create_event,
            test_marker_create_item,
            test_marker_invalid_type,
            test_marker_nonexistent_entity,
            test_marker_entity_wrong_novel,
            test_marker_cross_novel_delete,
            test_marker_scene_id_filter,
            test_marker_scene_index_filter,
            test_marker_no_scene_limit,
            test_marker_update,
            test_marker_delete,
            test_marker_default_offsets,
            test_marker_default_visible,
            # Territories (15-23)
            test_territory_create_organization,
            test_territory_non_organization,
            test_territory_hex_out_of_bounds,
            test_territory_batch_create,
            test_territory_update_style,
            test_territory_delete_single,
            test_territory_delete_by_faction,
            test_territory_focus_mode,
            test_focus_mode_other_fields,
            # State aggregation (24-29)
            test_get_state_nonexistent_map,
            test_state_markers_and_territories_always_list,
            test_state_with_scene_id,
            test_state_without_scene_id,
            test_state_filter_types,
            test_state_breadcrumbs,
        ]

        print(f"\n{'=' * 60}")
        print(f"开始混沌测试: {len(all_tests)} 个测试点")
        print(f"{'=' * 60}\n")

        for test_fn in all_tests:
            try:
                test_fn(fixture)
            except Exception as e:
                tid = all_tests.index(test_fn) + 1
                results.append(
                    {
                        "id": tid,
                        "name": test_fn.__name__,
                        "passed": False,
                        "detail": str(e),
                    }
                )
                print(f"  [FAIL] #{tid:02d} {test_fn.__name__}")
                print(f"         EXCEPTION: {traceback.format_exc()}")

        # ============================================================
        # 生成报告
        # ============================================================
        print(f"\n{'=' * 60}")
        print("混沌测试报告")
        print(f"{'=' * 60}")

        total = len(results)
        passed_count = sum(1 for r in results if r["passed"])

        print(f"\n测试通过数 / 总数: {passed_count} / {total}")
        print(f"通过率: {passed_count / total * 100:.1f}%")

        # 按优先级归类 Bug
        if bugs:
            by_priority: dict[str, list[dict[str, Any]]] = {}
            for b in bugs:
                bp = b["priority"]
                by_priority.setdefault(bp, []).append(b)

            print("\n发现 Bug 列表:")
            for pri in ("P0", "P1", "P2"):
                if pri in by_priority:
                    print(f"\n  [{pri}] ({len(by_priority[pri])} 个)")
                    for b in by_priority[pri]:
                        print(f"    API: {b['api']}")
                        print(f"    输入: {b['input']}")
                        print(f"    期望: {b['expected']}")
                        print(f"    实际: {b['actual']}")
                        print(f"    HTTP: {b['status_code']}")
                        if b.get("root_cause"):
                            print(f"    根因: {b['root_cause']}")
                        print()
        else:
            print("\n未发现 Bug。")

        return 0 if passed_count == total else 1

    finally:
        try:
            fixture.cleanup()
        except Exception as e:
            print(f"  清理异常: {e}")


if __name__ == "__main__":
    sys.exit(main())
