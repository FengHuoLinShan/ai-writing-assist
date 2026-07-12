"""
Workflow path chaos baseline.

Coverage focus:
- S3 深度导入流水线
- S4 手工写作工作台

Run from backend/:
    python -m tests.chaos.workflow_paths_chaos
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Any

import requests

BASE_URL = os.environ.get("CHAOS_BASE_URL", "http://localhost:8000")
TIMEOUT = 45

CASE_CATALOG: list[dict[str, str]] = [
    {"chaos_case_id": "S3-IDM-001", "path_id": "S3", "layer": "workflow_chaos"},
    {"chaos_case_id": "S3-VAL-001", "path_id": "S3", "layer": "workflow_chaos"},
    {"chaos_case_id": "S4-CON-001", "path_id": "S4", "layer": "workflow_chaos"},
]

results: list[dict[str, Any]] = []


def record(chaos_case_id: str, name: str, passed: bool, detail: str = "") -> None:
    results.append(
        {
            "chaos_case_id": chaos_case_id,
            "name": name,
            "passed": passed,
            "detail": detail,
        }
    )
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {chaos_case_id} {name}")
    if detail:
        print(f"         {detail}")


class Fixture:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.novel_id: str | None = None

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        return self.session.request(
            method,
            f"{BASE_URL}{path}",
            timeout=TIMEOUT,
            **kwargs,
        )

    def setup(self) -> None:
        stamp = int(time.time())
        resp = self._req(
            "POST",
            "/api/projects",
            json={"title": f"workflow-chaos-{stamp}", "genre": "fantasy"},
        )
        assert resp.status_code == 201, resp.text
        self.novel_id = resp.json()["id"]

    def cleanup(self) -> None:
        if not self.novel_id:
            return
        try:
            self._req("DELETE", f"/api/projects/{self.novel_id}")
        except Exception:
            pass
        try:
            self._req("DELETE", f"/api/projects/{self.novel_id}/permanent")
        except Exception:
            pass

    def upload_three_chapters(self) -> requests.Response:
        assert self.novel_id
        content = "\n".join(
            [
                "第一章 起风",
                "青石镇的清晨有些冷。",
                "",
                "第二章 旧信",
                "信封里没有署名。",
                "",
                "第三章 约定",
                "风已经更急了。",
            ]
        ).encode("utf-8")
        return self._req(
            "POST",
            "/api/imports/upload",
            data={"novel_id": self.novel_id},
            files={"file": ("three-chapter-novel.txt", content, "text/plain")},
        )


def test_s3_repeat_range_requires_confirmation(f: Fixture) -> None:
    assert f.novel_id
    upload_resp = f.upload_three_chapters()
    if upload_resp.status_code != 201:
        record(
            "S3-IDM-001",
            "重复深度导入前置上传成功",
            False,
            detail=f"upload={upload_resp.status_code} body={upload_resp.text[:200]}",
        )
        return

    sync_resp = f._req(
        "POST",
        "/api/imports/deep/sync",
        json={"novel_id": f.novel_id, "start_chapter": 1, "end_chapter": 3},
    )
    if sync_resp.status_code != 201:
        record(
            "S3-IDM-001",
            "同步深度导入建立派生数据",
            False,
            detail=f"sync={sync_resp.status_code} body={sync_resp.text[:200]}",
        )
        return

    repeat_resp = f._req(
        "POST",
        "/api/imports/deep",
        json={"novel_id": f.novel_id, "start_chapter": 1, "end_chapter": 3},
    )
    try:
        data = repeat_resp.json()
    except Exception:  # noqa: BLE001
        data = {}

    passed = (
        repeat_resp.status_code == 201
        and data.get("requires_confirmation") is True
        and data.get("status") == "requires_confirmation"
    )
    if not passed:
        record(
            "S3-IDM-001",
            "重复深度导入返回确认而非静默覆盖",
            False,
            detail=f"repeat={repeat_resp.status_code} body={repeat_resp.text[:300]}",
        )
        return
    record("S3-IDM-001", "重复深度导入返回确认而非静默覆盖", True)


def test_s3_empty_project_returns_clear_error(f: Fixture) -> None:
    assert f.novel_id
    resp = f._req(
        "POST",
        "/api/imports/deep",
        json={"novel_id": f.novel_id, "start_chapter": 1, "end_chapter": 0},
    )
    passed = resp.status_code == 400 and "章节" in resp.text
    if not passed:
        record(
            "S3-VAL-001",
            "空项目深度导入返回明确业务错误",
            False,
            detail=f"status={resp.status_code} body={resp.text[:200]}",
        )
        return
    record("S3-VAL-001", "空项目深度导入返回明确业务错误", True)


def test_s4_stale_expected_version_returns_409(f: Fixture) -> None:
    assert f.novel_id
    create_v1 = f._req(
        "POST",
        "/api/writing/drafts",
        json={
            "novel_id": f.novel_id,
            "chapter_index": 1,
            "title": "第一版",
            "content": "v1",
        },
    )
    if create_v1.status_code != 201:
        record(
            "S4-CON-001",
            "创建第一个正文版本",
            False,
            detail=f"v1={create_v1.status_code} body={create_v1.text[:200]}",
        )
        return
    draft_v1_id = create_v1.json()["draft"]["id"]

    create_v2 = f._req(
        "POST",
        "/api/writing/drafts",
        json={
            "novel_id": f.novel_id,
            "chapter_index": 1,
            "title": "第二版",
            "content": "v2",
        },
    )
    if create_v2.status_code != 201:
        record(
            "S4-CON-001",
            "创建第二个正文版本",
            False,
            detail=f"v2={create_v2.status_code} body={create_v2.text[:200]}",
        )
        return

    stale_resp = f._req(
        "PUT",
        f"/api/writing/drafts/{draft_v1_id}?novel_id={f.novel_id}",
        json={"title": "stale save", "expected_version": 1},
    )
    passed = stale_resp.status_code == 409 and "刷新后重新编辑" in stale_resp.text
    if not passed:
        record(
            "S4-CON-001",
            "陈旧版本保存返回 409",
            False,
            detail=f"status={stale_resp.status_code} body={stale_resp.text[:200]}",
        )
        return
    record("S4-CON-001", "陈旧版本保存返回 409", True)


def main() -> int:
    print("=== Workflow path chaos baseline ===")
    print(f"Base URL: {BASE_URL}")
    fixture = Fixture()
    try:
        fixture.setup()
        tests = [
            test_s3_repeat_range_requires_confirmation,
            test_s3_empty_project_returns_clear_error,
            test_s4_stale_expected_version_returns_409,
        ]
        for test_fn in tests:
            try:
                test_fn(fixture)
            except Exception as exc:  # noqa: BLE001
                record(test_fn.__name__, test_fn.__name__, False, detail=str(exc))
                traceback.print_exc()
    finally:
        fixture.cleanup()

    total = len(results)
    failed = sum(1 for item in results if not item["passed"])
    print("\n=== Summary ===")
    print(f"Total: {total}, Failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
