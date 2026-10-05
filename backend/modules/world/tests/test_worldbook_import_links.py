"""理法之环 Wiki 导入的引用扫描与物化用例（m1-contract 第 4 条）。

覆盖：四态矩阵（批内 resolved、已发布页 resolved、批内同名 ambiguous、
unresolved、unselected）；link_summary 纳入 preview_hash；create/update 物化
（local: 约定与已发布页真实 TargetRef、relation 固定 informs、target_hash
按指纹规则）；每页 100 上限截断与 reason 明示；baseline 含 refs 口径下的
三方比较（仅来源变化 update、双边变化 conflict）；全程不产生 EntityRelation。

扫描与判定的确定性纯函数直接以类方法单测；端到端沿
test_worldbook_dataset_import.py 的 service 直调风格，不触碰本机真实资料。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import EntityRelation, WorldBiblePage, WorldBiblePageDraft
from modules.world.schemas import (
    WorldBiblePageDraftUpdate,
    WorldbookImportApplyRequest,
    WorldbookImportItem,
    WorldbookImportManifest,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)
from shared.target_ref import TargetRef


def _linked_dataset_pages() -> list[dict[str, str]]:
    """合成资料集两页：理法之环正文与 frontmatter 各含指向星锻环的引用。

    提交路径带所选根目录名（理法之环/），剥根后 rel_path 保留 concepts 层级，
    供路径形态引用与 local: 约定断言使用。
    """
    return [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related:\n  - "[[星锻环|星环]]"\n---\n'
                "以理法编织万物，见 [[星锻环#潮汐节律]] 与纯名称的未知页 [[未知之环]]。"
            ),
        },
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
    ]


def _dataset_manifest(
    *,
    files: list[dict[str, str]],
    dataset_name: str = "理法之环",
    commit_mode: str = "full_snapshot",
) -> WorldbookImportManifest:
    return WorldbookImportManifest(
        schema_version="world_worldbook_import.v2",
        source_format="obsidian",
        dataset_name=dataset_name,
        commit_mode=commit_mode,
        files=files,
    )


def _apply_request(preview) -> WorldbookImportApplyRequest:
    return WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash)


async def _published_page(
    db: AsyncSession, novel_id: str, *, page_key: str, title: str
) -> WorldBiblePage:
    page = WorldBiblePage(
        novel_id=uuid.UUID(novel_id),
        page_type="location",
        page_key=page_key,
        title=title,
        status="canonical",
        linked_asset_refs_json=[],
    )
    db.add(page)
    await db.flush()
    return page


async def _drafts_of(db: AsyncSession, novel_id: str) -> list[WorldBiblePageDraft]:
    return list(
        (
            await db.execute(
                select(WorldBiblePageDraft).where(
                    WorldBiblePageDraft.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )


def test_parse_link_occurrences_keeps_alias_and_anchor() -> None:
    """纯函数单测：别名与 #anchor 不参与匹配但保留在解析结果里。"""
    mapped = {
        "content": "正文 [[星锻环|星环]] 与 [[concepts/星锻环.md#潮汐节律]] 与 [[]]。",
        "frontmatter": {
            "related": ['[[星锻环|显示文本]]', "纯名称", "[[北境商路]]", 42],
        },
    }
    occurrences = WorldbookImportService._parse_link_occurrences(mapped)
    by_origin_target = {(occ.origin, occ.target): occ for occ in occurrences}
    # 别名/锚保留；空目标与数字列表项不产出。
    assert set(by_origin_target) == {
        ("free_text", "星锻环"),
        ("free_text", "concepts/星锻环.md"),
        ("frontmatter", "星锻环"),
        ("frontmatter", "纯名称"),
        ("frontmatter", "北境商路"),
    }
    alias_occ = by_origin_target[("free_text", "星锻环")]
    assert alias_occ.alias == "星环" and alias_occ.anchor == "" and not alias_occ.is_path
    path_occ = by_origin_target[("free_text", "concepts/星锻环.md")]
    assert path_occ.anchor == "潮汐节律" and path_occ.is_path
    assert by_origin_target[("frontmatter", "纯名称")].alias == ""
    assert by_origin_target[("frontmatter", "星锻环")].alias == "显示文本"


@pytest.mark.asyncio
async def test_four_state_matrix_counts(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """四态矩阵：批内 resolved、已发布页 resolved、批内同名 ambiguous、unresolved。

    理法之环页正文覆盖：[[星锻环#潮汐节律]]（批内唯一标题，锚不参与）→
    resolved；[[北境商路]]（项目内 canonical 已发布页）→ resolved；
    [[双环]]（本批两个同名 item）→ ambiguous；[[未知之环]] → unresolved。
    frontmatter related（[[星锻环|星环]]）与正文双链走同一规则。
    """
    await _published_page(
        db_session, project_novel_id, page_key="location:north-road", title="北境商路"
    )
    files = [
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
        {
            "path": "concepts/双环甲.md",
            "content": "---\ntitle: 双环\n---\n同名甲。",
        },
        {
            "path": "concepts/双环乙.md",
            "content": "---\ntitle: 双环\n---\n同名乙。",
        },
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related: "[[北境商路]]"\n---\n'
                "见 [[星锻环#潮汐节律]]、[[双环]] 与 [[未知之环]]。"
            ),
        },
    ]
    preview = await WorldbookImportService().preview(
        db_session, project_novel_id, _dataset_manifest(files=files)
    )
    items = {item.title: item for item in preview.items}
    summary = items["理法之环"].link_summary
    # resolved 含 frontmatter related 的北境商路与正文批内星锻环。
    assert summary == {"resolved": 2, "ambiguous": 1, "unresolved": 1, "unselected": 0}
    # 批内同名两页自身不带引用，计数全 0。
    assert items["双环"].link_summary == {
        "resolved": 0,
        "ambiguous": 0,
        "unresolved": 0,
        "unselected": 0,
    }
    # 同一 preview_hash 可复现（items 全量 dump 含 link_summary，重放一致）。
    again = await WorldbookImportService().preview(
        db_session, project_novel_id, _dataset_manifest(files=files)
    )
    assert again.preview_hash == preview.preview_hash


@pytest.mark.asyncio
async def test_path_link_to_unselected_dataset_member(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """unselected：路径命中同 dataset 既有成员但不在本批，不建任何 ref。"""
    service = WorldbookImportService()
    first = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=_linked_dataset_pages())
    )
    first_ring = next(item for item in first.items if item.title == "理法之环")
    assert first_ring.link_summary["resolved"] >= 1
    applied = await service.apply(
        db_session, project_novel_id, first.suggestion_id, _apply_request(first)
    )
    assert applied.status == "accepted"

    # 第二包（同 dataset、append）只含理法之环，正文以路径引用星锻环文件；
    # 星锻环是 dataset 既有成员但不在本批 → unselected。
    follow_up = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n---\n"
                "路径引用 [[concepts/星锻环.md#潮汐节律]]。"
            ),
        }
    ]
    second = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(files=follow_up, commit_mode="append"),
    )
    items = {item.title: item for item in second.items}
    assert items["理法之环"].action == "update"
    assert items["理法之环"].link_summary == {
        "resolved": 0,
        "ambiguous": 0,
        "unresolved": 0,
        "unselected": 1,
    }
    applied_second = await service.apply(
        db_session, project_novel_id, second.suggestion_id, _apply_request(second)
    )
    assert applied_second.status == "accepted"
    draft = next(
        draft for draft in await _drafts_of(db_session, project_novel_id)
        if draft.title == "理法之环"
    )
    await db_session.refresh(draft)
    # unselected 不建 ref；正文保留 [[…]] 原文不改写。
    assert draft.linked_asset_refs_json == []
    assert "[[concepts/星锻环.md#潮汐节律]]" in draft.free_text


@pytest.mark.asyncio
async def test_preview_hash_is_sensitive_to_link_summary(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """preview_hash 对引用变化敏感：link_summary 在 items 全量 dump 的指纹输入内。"""
    service = WorldbookImportService()
    # 层 1（指纹输入）：items dump 中仅 link_summary 不同即得不同 hash。
    base_item = WorldbookImportItem(
        source_key="0" * 64,
        path="a.md",
        title="a",
        source_hash="1" * 64,
        action="create",
    )
    linked_item = base_item.model_copy(
        update={
            "link_summary": {
                "resolved": 1,
                "ambiguous": 0,
                "unresolved": 0,
                "unselected": 0,
            }
        }
    )
    assert service._hash(base_item.model_dump(mode="json")) != service._hash(
        linked_item.model_dump(mode="json")
    )
    # 层 2（端到端）：仅正文引用目标不同的两包，link_summary 与 preview_hash 均不同。
    resolved_files = _linked_dataset_pages()
    unresolved_files = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related:\n  - "[[星锻环|星环]]"\n---\n'
                "以理法编织万物，见 [[不存在之页#潮汐节律]] 与 [[同样不存在之页]]。"
            ),
        },
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
    ]
    first = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=resolved_files)
    )
    second = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=unresolved_files)
    )
    assert first.preview_hash != second.preview_hash
    first_summary = next(
        item for item in first.items if item.title == "理法之环"
    ).link_summary
    second_summary = next(
        item for item in second.items if item.title == "理法之环"
    ).link_summary
    assert first_summary["resolved"] > second_summary["resolved"]
    assert second_summary["unresolved"] > first_summary["unresolved"]


@pytest.mark.asyncio
async def test_materialize_local_ref_shape_and_lifecycle_validation(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """批内 resolved 物化为 local: 约定，形状与采用包先例一致并通过 lifecycle 校验。"""
    service = WorldbookImportService()
    preview = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=_linked_dataset_pages())
    )
    item = next(item for item in preview.items if item.title == "理法之环")
    assert item.link_summary == {
        "resolved": 2,
        "ambiguous": 0,
        "unresolved": 1,
        "unselected": 0,
    }
    applied = await service.apply(
        db_session, project_novel_id, preview.suggestion_id, _apply_request(preview)
    )
    assert applied.status == "accepted"
    draft = next(
        draft for draft in await _drafts_of(db_session, project_novel_id)
        if draft.title == "理法之环"
    )
    refs = draft.linked_asset_refs_json
    # 去重后 1 条：正文与 frontmatter related 各引用一次星锻环。
    assert len(refs) == 1
    ref = refs[0]
    dataset_key = draft.page_meta_json["worldbook_import"]["dataset_key"]
    assert ref == {
        "target_type": "world_bible_page",
        "target_id": f"local:{dataset_key}:concepts/星锻环.md",
        "relation": "informs",
        "target_hash": WorldBibleLifecycleService._asset_ref_hash(ref),
    }
    # 未解析目标不建 ref，原文保留。
    assert "未知之环" in draft.free_text and "[[未知之环]]" in draft.free_text
    # ref 通过不带 local 豁免之外的真实校验路径：按 TargetRef 契约指纹复核。
    fingerprint = TargetRef(
        target_type="world_bible_page",
        target_id=ref["target_id"],
        relation="informs",
    ).target_hash()
    assert ref["target_hash"] == fingerprint
    # baseline 按物化后含 refs 的字段组计算：与 _editable_content_hash 相等。
    imported = draft.page_meta_json["worldbook_import"]
    assert imported["baseline_content_hash"] == (
        WorldbookImportService._editable_content_hash(draft)
    )


@pytest.mark.asyncio
async def test_materialize_published_page_target_ref(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """已发布 WorldBiblePage 目标写真实 TargetRef（relation=informs + 指纹）。"""
    page = await _published_page(
        db_session, project_novel_id, page_key="location:north-road", title="北境商路"
    )
    files = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": "---\ntitle: 理法之环\n---\n商路见 [[北境商路]]。",
        }
    ]
    service = WorldbookImportService()
    preview = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=files)
    )
    item = preview.items[0]
    assert item.link_summary["resolved"] == 1
    applied = await service.apply(
        db_session, project_novel_id, preview.suggestion_id, _apply_request(preview)
    )
    assert applied.status == "accepted"
    draft = (await _drafts_of(db_session, project_novel_id))[0]
    refs = draft.linked_asset_refs_json
    assert len(refs) == 1
    ref = refs[0]
    assert ref["target_type"] == "world_bible_page"
    assert ref["target_id"] == str(page.id)
    assert ref["relation"] == "informs"
    assert ref["target_hash"] == WorldBibleLifecycleService._asset_ref_hash(ref)
    # 真实 id ref 不依赖 local 豁免即可通过 lifecycle 校验（物化已在 apply 内走过）。
    await WorldBibleLifecycleService()._validate_asset_refs(
        db_session, uuid.UUID(project_novel_id), refs
    )
    # 全程无 EntityRelation 产生。
    total = await db_session.scalar(select(func.count()).select_from(EntityRelation))
    assert total == 0


@pytest.mark.asyncio
async def test_update_keeps_refs_without_conflict_and_bidirectional_conflicts(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """baseline 含 refs 口径：仅来源变化 update（正文/frontmatter 各一）、双边 conflict。

    冻结决定 a（m1-contract 第 4 条）：baseline 按「物化后含 refs」的字段组
    写入，来源重导时 refs 不把 update 误判成 conflict。
    """
    service = WorldbookImportService()
    first = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=_linked_dataset_pages())
    )
    await service.apply(
        db_session, project_novel_id, first.suggestion_id, _apply_request(first)
    )
    draft = next(
        draft for draft in await _drafts_of(db_session, project_novel_id)
        if draft.title == "理法之环"
    )
    refs_after_apply = list(draft.linked_asset_refs_json)
    assert refs_after_apply

    # 仅改正文重导：来源 hash 变、站内未动（含 refs）→ update，不误判 conflict。
    changed_text = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related:\n  - "[[星锻环|星环]]"\n---\n'
                "以理法编织万物，第二版补充环律细节，见 [[星锻环#潮汐节律]]。"
            ),
        },
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
    ]
    second = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=changed_text)
    )
    items = {item.title: item for item in second.items}
    assert items["理法之环"].action == "update"
    assert items["星锻环"].action == "preserve"
    await service.apply(
        db_session, project_novel_id, second.suggestion_id, _apply_request(second)
    )
    await db_session.refresh(draft)
    assert draft.linked_asset_refs_json == refs_after_apply

    # 仅改来源 frontmatter（related 增项）重导：同样 update。
    changed_frontmatter = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related:\n  - "[[星锻环|星环]]"\n  - 潮汐城\n---\n'
                "以理法编织万物，第二版补充环律细节，见 [[星锻环#潮汐节律]]。"
            ),
        },
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
    ]
    third = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=changed_frontmatter)
    )
    items = {item.title: item for item in third.items}
    assert items["理法之环"].action == "update"
    await service.apply(
        db_session, project_novel_id, third.suggestion_id, _apply_request(third)
    )

    # 双边改：作者本地改 free_text + 来源再变 → conflict，不覆盖工作稿。
    await WorldBibleLifecycleService().update_draft(
        db_session,
        project_novel_id,
        str(draft.id),
        WorldBiblePageDraftUpdate(free_text="作者本地修改"),
    )
    fourth_files = [
        {
            "path": "理法之环/concepts/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                'related:\n  - "[[星锻环|星环]]"\n---\n'
                "以理法编织万物，第三版重写环律，见 [[星锻环#潮汐节律]]。"
            ),
        },
        {
            "path": "理法之环/concepts/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环。"
            ),
        },
    ]
    fourth = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=fourth_files)
    )
    items = {item.title: item for item in fourth.items}
    assert items["理法之环"].action == "conflict"
    applied_fourth = await service.apply(
        db_session, project_novel_id, fourth.suggestion_id, _apply_request(fourth)
    )
    assert applied_fourth.status == "accepted"
    assert applied_fourth.draft_ids == []
    await db_session.refresh(draft)
    assert draft.free_text == "作者本地修改"

    # 全程无 EntityRelation 产生。
    total = await db_session.scalar(select(func.count()).select_from(EntityRelation))
    assert total == 0


@pytest.mark.asyncio
async def test_refs_over_limit_truncated_with_reason(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """每页 refs ≤100：超限截断物化前 100 条并在 item.reason 明示。"""
    service = WorldbookImportService()
    files = [
        {
            "path": f"理法之环/notes/目标{index:03d}.md",
            "content": f"---\ntitle: 目标{index:03d}\n---\n目标页 {index}。",
        }
        for index in range(101)
    ]
    files.append(
        {
            "path": "理法之环/notes/汇总.md",
            "content": "---\ntitle: 汇总\n---\n"
            + " ".join(f"[[目标{index:03d}]]" for index in range(101)),
        }
    )
    preview = await service.preview(
        db_session, project_novel_id, _dataset_manifest(files=files)
    )
    summary_item = next(item for item in preview.items if item.title == "汇总")
    assert summary_item.link_summary == {
        "resolved": 101,
        "ambiguous": 0,
        "unresolved": 0,
        "unselected": 0,
    }
    assert "仅物化前 100 条" in summary_item.reason
    applied = await service.apply(
        db_session, project_novel_id, preview.suggestion_id, _apply_request(preview)
    )
    assert applied.status == "accepted"
    draft = next(
        draft for draft in await _drafts_of(db_session, project_novel_id)
        if draft.title == "汇总"
    )
    refs = draft.linked_asset_refs_json
    assert len(refs) == 100
    assert all(ref["relation"] == "informs" for ref in refs)
    assert all(
        ref["target_id"].endswith(f"notes/目标{index:03d}.md")
        for index, ref in enumerate(refs)
    )
    # baseline 与每页上限校验一致：100 条 ref 可整体通过 lifecycle 校验。
    await WorldBibleLifecycleService()._validate_asset_refs(
        db_session,
        uuid.UUID(project_novel_id),
        refs,
        allow_local_refs=True,
    )
