"""理法之环 Wiki 导入 M1 失败用例（先写测试、后实现）。

覆盖 m1-contract.md 第 7 节四个失败场景：
1. 子目录误识别（7.1）：仅选择概念子目录时被现有格式识别当作 generic；
2. 跨资料集误报缺失（7.2）：本次未出现的既有来源被统一判 missing；
3. 根名变化重复（7.3）：资料集根目录名变化导致同一资料集被当成新身份；
4. 双边编辑冲突（7.4）：来源与站内双边编辑应进入冲突而不是覆盖/误报缺失。

用例按目标契约 world_worldbook_import.v2 的 API 表达（manifest 显式
``source_format``、``dataset_name``、``commit_mode``，见 m1-contract.md
第 1/2/3/5 条与第 8 节冻结字段总表）。当前实现尚未提供 v2 字段，用例预期在
manifest 构造处失败（pydantic 对未知字段报 extra_forbidden、schema_version
不接受 v2 字面量）——失败点即「契约未实现」本身，而非夹具或导入路径错误；
M2/M3 实现落地后本模块应整体转绿。

合成 Wiki 夹具均为安全相对 POSIX 路径 + 受限 frontmatter，沿
test_worldbook_import.py 的 service 直调风格，不触碰本机真实资料。
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.models import ConflictCheckQueueItem, WorldBiblePageDraft
from modules.world.schemas import (
    CreationSuggestionCreate,
    WorldBiblePageDraftUpdate,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)
from modules.world.worldbook_import_schemas import (
    WorldbookImportApplyRequest,
    WorldbookImportFile,
    WorldbookImportManifest,
    WorldbookImportPayload,
)


def _concept_pages(root: str) -> list[dict[str, str]]:
    """合成「理法之环」概念子目录两页：无 .obsidian/.wiki 控制目录标记。"""
    return [
        {
            "path": f"{root}/concepts/真名回响/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n---\n"
                "以理法编织万物的环，维系真名回响的秩序。"
            ),
        },
        {
            "path": f"{root}/concepts/真名回响/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环，记录潮汐节律。"
            ),
        },
    ]


def _artifact_pages(root: str) -> list[dict[str, str]]:
    """合成「星锻环」资料集两页：rel_path 与概念子目录互不重叠。"""
    return [
        {
            "path": f"{root}/artifacts/双月节点阵列.md",
            "content": (
                "---\ntitle: 双月节点阵列\npage_type: location\n---\n"
                "双月节点构成的定位阵列。"
            ),
        },
        {
            "path": f"{root}/artifacts/魔法传输链路.md",
            "content": (
                "---\ntitle: 魔法传输链路\npage_type: location\n---\n"
                "连接节点阵列的传输链路。"
            ),
        },
    ]


def _dataset_manifest(
    *,
    dataset_name: str,
    commit_mode: str,
    files: list[dict[str, str]],
    source_format: str = "obsidian",
    dataset_intent: str = "continue",
) -> WorldbookImportManifest:
    """按 m1-contract.md 第 1/2/3 条构造 v2 manifest（显式格式 + 资料集语义）。"""
    return WorldbookImportManifest(
        schema_version="world_worldbook_import.v2",
        source_format=source_format,
        dataset_name=dataset_name,
        dataset_intent=dataset_intent,
        commit_mode=commit_mode,
        files=files,
    )


def _apply_request(preview) -> WorldbookImportApplyRequest:
    return WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash)


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


@pytest.mark.asyncio
async def test_explicit_source_format_recovers_concept_pages_from_subdirectory(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """7.1 子目录误识别：manifest 显式 source_format 应恢复 page_type 归类。

    契约（m1-contract.md 第 1 条、7.1）：source_format 受 schema 限定
    （Literal["auto","obsidian","llmwiki","wiki_markdown","generic"]，默认
    auto）；显式值直接生效并在 payload 固化，apply 重放不得漂移。
    """
    service = WorldbookImportService()
    files = _concept_pages("wiki")

    # 现状对照（契约保留）：auto 路径下子目录包被判 generic，正文降为
    # source_material；该对照同时证明合成夹具本身可被现有管线接受。
    auto_preview = await service.preview(
        db_session, project_novel_id, WorldbookImportManifest(files=files)
    )
    assert auto_preview.source_format == "generic"
    assert {item.path: item.page_type for item in auto_preview.items} == {
        "wiki/concepts/真名回响/理法之环.md": "source_material",
        "wiki/concepts/真名回响/星锻环.md": "source_material",
    }

    # 契约行为：显式 source_format="obsidian" 生效，page_type 按声明归类。
    preview = await service.preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(
            schema_version="world_worldbook_import.v2",
            source_format="obsidian",
            files=files,
        ),
    )
    assert preview.source_format == "obsidian"
    assert len(preview.items) == 2
    assert {item.page_type for item in preview.items} == {"concept"}

    applied = await service.apply(
        db_session,
        project_novel_id,
        preview.suggestion_id,
        _apply_request(preview),
    )
    assert applied.status == "accepted"
    assert applied.manifest_hash == preview.manifest_hash

    drafts = {
        draft.title: draft for draft in await _drafts_of(db_session, project_novel_id)
    }
    assert set(drafts) == {"理法之环", "星锻环"}
    for draft in drafts.values():
        assert draft.page_type == "concept"
        imported = draft.page_meta_json["worldbook_import"]
        assert imported["source_format"] == "obsidian"
        assert imported["activation_eligible"] is True


@pytest.mark.asyncio
async def test_full_snapshot_scopes_missing_to_own_dataset(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """7.2 跨资料集误报缺失：full_snapshot 只在自身 dataset_key 范围内判缺失。

    契约（m1-contract.md 第 3 条、7.2）：missing 判定输入收窄为 dataset_key
    相等的既有条目；另一资料集成员互不进入判定、不产生缺失标记，apply 不
    触碰对方 meta。
    """
    service = WorldbookImportService()

    ring_manifest = _dataset_manifest(
        dataset_name="理法之环",
        commit_mode="full_snapshot",
        files=_concept_pages("理法之环"),
    )
    ring_preview = await service.preview(db_session, project_novel_id, ring_manifest)
    assert ring_preview.counts == {
        "create": 2,
        "update": 0,
        "preserve": 0,
        "conflict": 0,
        "missing": 0,
    }
    ring_applied = await service.apply(
        db_session,
        project_novel_id,
        ring_preview.suggestion_id,
        _apply_request(ring_preview),
    )
    assert ring_applied.status == "accepted"

    ring_drafts = {
        str(draft.id): draft for draft in await _drafts_of(db_session, project_novel_id)
    }
    assert len(ring_drafts) == 2
    texts_before = {key: draft.free_text for key, draft in ring_drafts.items()}
    meta_before = {
        key: dict(draft.page_meta_json["worldbook_import"])
        for key, draft in ring_drafts.items()
    }

    # 另一资料集以 full_snapshot 提交：不得把「理法之环」的既有来源判 missing。
    forge_manifest = _dataset_manifest(
        dataset_name="星锻环",
        commit_mode="full_snapshot",
        files=_artifact_pages("星锻环"),
    )
    forge_preview = await service.preview(db_session, project_novel_id, forge_manifest)
    assert forge_preview.counts["missing"] == 0
    assert forge_preview.counts["create"] == 2
    assert all(item.action == "create" for item in forge_preview.items)
    ring_keys = {item.source_key for item in ring_preview.items}
    assert ring_keys.isdisjoint(item.source_key for item in forge_preview.items)

    forge_applied = await service.apply(
        db_session,
        project_novel_id,
        forge_preview.suggestion_id,
        _apply_request(forge_preview),
    )
    assert forge_applied.status == "accepted"

    # 「理法之环」的工作稿内容与导入 meta 均不得被本次 apply 改写。
    for key, draft in ring_drafts.items():
        await db_session.refresh(draft)
        assert draft.free_text == texts_before[key]
        assert draft.page_meta_json["worldbook_import"] == meta_before[key]
        assert draft.page_meta_json["worldbook_import"]["source_missing"] is False
        assert "missing_manifest_hash" not in draft.page_meta_json["worldbook_import"]


@pytest.mark.asyncio
async def test_dataset_identity_survives_root_directory_rename(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """7.3 根名变化重复：dataset 身份与页级 key 不受所选根目录名影响。

    契约（m1-contract.md 第 2/5 条、7.3）：dataset_key 由作者声明的
    dataset_name 派生；页级 source_key = sha256(dataset_key + rel_path)，
    rel_path 剥离根目录名；manifest_hash 以 rel_path 为基准，根改名后指纹
    稳定，重导入走 preserve 而不是重复建稿。
    """
    service = WorldbookImportService()

    first = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode="full_snapshot",
            files=_concept_pages("理法之环"),
        ),
    )
    assert first.counts["create"] == 2
    first_applied = await service.apply(
        db_session,
        project_novel_id,
        first.suggestion_id,
        _apply_request(first),
    )
    assert first_applied.status == "accepted"

    # 同内容包换根目录名（理法之环/ → ring/）重导：身份不变，全部 preserve。
    second = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode="full_snapshot",
            files=_concept_pages("ring"),
        ),
    )
    assert second.manifest_hash == first.manifest_hash
    assert second.counts == {
        "create": 0,
        "update": 0,
        "preserve": 2,
        "conflict": 0,
        "missing": 0,
    }
    assert {item.path: item.source_key for item in second.items} == {
        item.path: item.source_key for item in first.items
    }

    second_applied = await service.apply(
        db_session,
        project_novel_id,
        second.suggestion_id,
        _apply_request(second),
    )
    assert second_applied.status == "accepted"

    drafts = await _drafts_of(db_session, project_novel_id)
    assert len(drafts) == 2
    assert {draft.title for draft in drafts} == {"理法之环", "星锻环"}


async def _bidirectional_conflict_round(
    db: AsyncSession,
    novel_id: str,
    commit_mode: str,
) -> None:
    """单轮双边冲突：导入 → 作者本地修改 → 来源变化重导 → 冲突进入队列。"""
    service = WorldbookImportService()
    first = await service.preview(
        db,
        novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode=commit_mode,
            files=_concept_pages("理法之环"),
        ),
    )
    first_applied = await service.apply(
        db, novel_id, first.suggestion_id, _apply_request(first)
    )
    assert first_applied.status == "accepted"

    drafts = {draft.title: draft for draft in await _drafts_of(db, novel_id)}
    await WorldBibleLifecycleService().update_draft(
        db,
        novel_id,
        str(drafts["理法之环"].id),
        WorldBiblePageDraftUpdate(free_text="作者本地修改"),
    )

    changed_files = _concept_pages("理法之环")
    changed_files[0]["content"] = changed_files[0]["content"].replace(
        "以理法编织万物的环，维系真名回响的秩序。",
        "以理法编织万物的环，第二版补充环律细节。",
    )
    second = await service.preview(
        db,
        novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode=commit_mode,
            files=changed_files,
        ),
    )
    assert second.counts["missing"] == 0
    items = {item.title: item for item in second.items}
    assert items["理法之环"].action == "conflict"
    assert items["星锻环"].action == "preserve"
    conflict_key = items["理法之环"].source_key

    applied = await service.apply(
        db, novel_id, second.suggestion_id, _apply_request(second)
    )
    assert applied.status == "accepted"
    # 冲突页与保留页都不应被写入：工作稿保留作者本地修改。
    assert applied.draft_ids == []
    await db.refresh(drafts["理法之环"])
    assert drafts["理法之环"].free_text == "作者本地修改"

    pending = list(
        (
            await db.execute(
                select(ConflictCheckQueueItem).where(
                    ConflictCheckQueueItem.novel_id == uuid.UUID(novel_id),
                    ConflictCheckQueueItem.conflict_type == "worldbook_import_conflict",
                    ConflictCheckQueueItem.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pending) == 1
    conflict = pending[0]
    assert conflict.severity == "high"
    assert conflict.resolution_json["author_action"] == "needs_decision"
    # 队列项必须挂在新页级 key（dataset_key + rel_path 派生）上。
    assert conflict.target["source_key"] == conflict_key

    # 再次以同包 apply：旧 pending 冲突置 stale，同 key 只留一条。
    third = await service.preview(
        db,
        novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode=commit_mode,
            files=changed_files,
        ),
    )
    applied_again = await service.apply(
        db, novel_id, third.suggestion_id, _apply_request(third)
    )
    assert applied_again.status == "accepted"
    pending_after = list(
        (
            await db.execute(
                select(ConflictCheckQueueItem).where(
                    ConflictCheckQueueItem.novel_id == uuid.UUID(novel_id),
                    ConflictCheckQueueItem.conflict_type == "worldbook_import_conflict",
                    ConflictCheckQueueItem.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pending_after) == 1
    assert pending_after[0].id != conflict.id
    await db.refresh(conflict)
    assert conflict.status == "stale"


@pytest.mark.asyncio
async def test_bidirectional_edit_lands_in_conflict_under_both_commit_modes(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
) -> None:
    """7.4 双边编辑冲突：full_snapshot 与 append 下冲突表达一致。

    契约（m1-contract.md 第 3 条、7.4）：该页 action=conflict、其余页正常；
    apply 后冲突队列新项 severity=high、needs_decision、target.source_key 为
    新页级 key，工作稿不被覆盖；重复 apply 时旧 pending 冲突置 stale。
    """
    full_snapshot_nid, append_nid = two_projects
    for novel_id, commit_mode in (
        (full_snapshot_nid, "full_snapshot"),
        (append_nid, "append"),
    ):
        await _bidirectional_conflict_round(db_session, novel_id, commit_mode)


@pytest.mark.asyncio
async def test_mixed_root_rel_path_collision_is_rejected(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """7.5 混合根名包撞 rel_path：现状对照可各自 create，dataset 提交拒绝。

    契约（m1-contract.md 第 2 条、7.5）：v1 旧算法 source_key 含完整提交路径，
    不同根名不撞 key（现状对照锚点）；dataset 提交剥根后 rel_path 归一化冲突，
    preview 与 apply 重放均以 ValidationError（HTTP 400 口径）拒绝且不产生工作稿。
    """
    service = WorldbookImportService()
    mixed_root_files = [
        {
            "path": "ring/concepts/理法之环.md",
            "content": "---\ntitle: 理法之环\n---\n版本甲。",
        },
        {
            "path": "vault/concepts/理法之环.md",
            "content": "---\ntitle: 理法之环\n---\n版本乙。",
        },
    ]

    # 现状对照：旧算法不撞 key，preview 可各自 create（回归锚点）。
    legacy_preview = await service.preview(
        db_session, project_novel_id, WorldbookImportManifest(files=mixed_root_files)
    )
    assert legacy_preview.counts["create"] == 2
    assert len({item.source_key for item in legacy_preview.items}) == 2

    # 契约行为：dataset 提交剥根后撞 rel_path，preview 拒绝。
    with pytest.raises(ValidationError, match="rel_path"):
        await service.preview(
            db_session,
            project_novel_id,
            _dataset_manifest(
                dataset_name="理法之环",
                commit_mode="full_snapshot",
                files=mixed_root_files,
            ),
        )

    # apply 重放同样拒绝：stored payload 一旦携带撞 rel_path 的文件条目，
    # 重放校验（与 preview 同函数）即拒绝，不落到任何工作稿写入。
    identity = WorldbookImportService._dataset_identity(
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode="full_snapshot",
            files=_concept_pages("理法之环"),
        )
    )
    payload = WorldbookImportPayload(
        schema_version="world_worldbook_import.v2",
        source_format="obsidian",
        manifest_hash="0" * 64,
        preview_hash="0" * 64,
        dataset_name="理法之环",
        dataset_key=identity.key,
        commit_mode="full_snapshot",
        files=[
            WorldbookImportFile(path="concepts/理法之环.md", content="版本甲。"),
            WorldbookImportFile(path="concepts/理法之环.md", content="版本乙。"),
        ],
    )
    suggestion = await service._suggestions.create(
        db_session,
        CreationSuggestionCreate(
            novel_id=project_novel_id,
            source_module="world",
            review_group="worldbook_import",
            target_type="worldbook_import",
            action_schema="world_worldbook_import.v2",
            payload_json=payload.model_dump(mode="json"),
            risk_level="high",
        ),
    )
    with pytest.raises(ValidationError):
        await service.apply(
            db_session,
            project_novel_id,
            str(suggestion.id),
            WorldbookImportApplyRequest(expected_preview_hash="0" * 64),
        )
    assert await _drafts_of(db_session, project_novel_id) == []


@pytest.mark.asyncio
async def test_adopt_legacy_source_binds_after_root_rename(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """7.7 根改名后显式接续 legacy 来源：等效 rel_path 匹配、补写绑定、不新建稿。

    契约（m1-contract.md 第 2 条、7.7）：legacy source_path 剥根得等效 rel_path
    逐条匹配；预览展示「legacy 路径 → 新包 rel_path」待绑定映射；apply 后匹配
    条目补写 dataset 字段、工作稿总数不变；单段 legacy source_path 整段参与比较。
    """
    service = WorldbookImportService()

    # 先以 v1 旧算法导入 2 页（legacy meta 无 dataset_key，source_path 含根名）。
    legacy = await service.preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(files=_concept_pages("理法之环")),
    )
    assert legacy.counts["create"] == 2
    await service.apply(
        db_session, project_novel_id, legacy.suggestion_id, _apply_request(legacy)
    )
    assert len(await _drafts_of(db_session, project_novel_id)) == 2

    # 根目录改名 ring/ 并显式接续旧来源。
    adopt = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode="full_snapshot",
            files=_concept_pages("ring"),
            dataset_intent="adopt_legacy",
        ),
    )
    assert adopt.dataset_intent == "adopt_legacy"
    assert adopt.counts == {
        "create": 0,
        "update": 0,
        "preserve": 2,
        "conflict": 0,
        "missing": 0,
    }
    bindings = {binding.rel_path: binding for binding in adopt.legacy_bindings}
    assert set(bindings) == {
        "concepts/真名回响/理法之环.md",
        "concepts/真名回响/星锻环.md",
    }
    assert {binding.legacy_source_path for binding in adopt.legacy_bindings} == {
        item.path for item in legacy.items
    }
    assert {binding.source_key for binding in adopt.legacy_bindings} == {
        item.source_key for item in legacy.items
    }

    applied = await service.apply(
        db_session, project_novel_id, adopt.suggestion_id, _apply_request(adopt)
    )
    assert applied.status == "accepted"
    drafts = await _drafts_of(db_session, project_novel_id)
    # 不新建工作稿，标题无重复。
    assert len(drafts) == 2
    assert {draft.title for draft in drafts} == {"理法之环", "星锻环"}
    for draft in drafts:
        imported = draft.page_meta_json["worldbook_import"]
        assert imported["dataset_key"] == adopt.dataset_key
        assert imported["dataset_name"] == "理法之环"
        assert imported["commit_mode"] == "full_snapshot"
        assert imported["rel_path"].startswith("concepts/真名回响/")
        # source_path 保留原始提交路径（含旧根名）。
        assert imported["source_path"].startswith("理法之环/concepts/真名回响/")
        assert imported["dataset_root_name"] == "ring"

    # 单段 legacy source_path（历史单文件提交、无根名）整段参与比较。
    single = await service.preview(
        db_session,
        project_novel_id,
        WorldbookImportManifest(
            files=[
                {
                    "path": "潮汐城.md",
                    "content": "---\ntitle: 潮汐城\n---\n潮汐城的旧稿。",
                }
            ]
        ),
    )
    await service.apply(
        db_session, project_novel_id, single.suggestion_id, _apply_request(single)
    )
    adopt_single = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="潮汐城志",
            commit_mode="full_snapshot",
            files=[
                {
                    "path": "潮汐城.md",
                    "content": "---\ntitle: 潮汐城\n---\n潮汐城的旧稿。",
                }
            ],
            dataset_intent="adopt_legacy",
        ),
    )
    assert adopt_single.counts["preserve"] == 1
    assert len(adopt_single.legacy_bindings) == 1
    assert adopt_single.legacy_bindings[0].legacy_source_path == "潮汐城.md"
    assert adopt_single.legacy_bindings[0].rel_path == "潮汐城.md"
    applied_single = await service.apply(
        db_session,
        project_novel_id,
        adopt_single.suggestion_id,
        _apply_request(adopt_single),
    )
    assert applied_single.status == "accepted"
    drafts = await _drafts_of(db_session, project_novel_id)
    assert len(drafts) == 3
    tide = next(draft for draft in drafts if draft.title == "潮汐城")
    imported = tide.page_meta_json["worldbook_import"]
    assert imported["dataset_key"] == adopt_single.dataset_key
    assert imported["rel_path"] == "潮汐城.md"
    assert imported["dataset_root_name"] == ""


@pytest.mark.asyncio
async def test_new_dataset_intent_rejects_existing_dataset_name(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """显式声明新资料集时，派生 key 已存在即拒绝（m1-contract 第 2 条）。"""
    service = WorldbookImportService()
    ring = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="理法之环",
            commit_mode="full_snapshot",
            files=_concept_pages("理法之环"),
        ),
    )
    await service.apply(
        db_session, project_novel_id, ring.suggestion_id, _apply_request(ring)
    )

    # 同名不同内容的新资料集声明同样拒绝：身份只由 dataset_name 派生。
    clash = _dataset_manifest(
        dataset_name="理法之环",
        commit_mode="full_snapshot",
        files=_artifact_pages("别的根"),
        dataset_intent="new",
    )
    with pytest.raises(ValidationError, match="already exists"):
        await service.preview(db_session, project_novel_id, clash)

    # 换名后同 intent 可用；dataset_intent 缺 dataset_name 在 manifest 层拒绝。
    renamed = _dataset_manifest(
        dataset_name="星环新集",
        commit_mode="full_snapshot",
        files=_artifact_pages("别的根"),
        dataset_intent="new",
    )
    ok = await service.preview(db_session, project_novel_id, renamed)
    assert ok.dataset_intent == "new"
    assert ok.counts["create"] == 2
    with pytest.raises(PydanticValidationError):
        WorldbookImportManifest(
            schema_version="world_worldbook_import.v2",
            dataset_intent="new",
            files=_concept_pages("x"),
        )


@pytest.mark.asyncio
async def test_declared_page_type_outside_category_rules_fails_cleanly(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """声明不满足分类键规则的 page_type（数字开头/单字符）时 apply 以业务
    ValidationError 失败，不再冒泡 pydantic 内部异常（评审问题 3）。"""
    service = WorldbookImportService()
    files = [
        {
            "path": "理法之环/bad.md",
            "content": "---\ntitle: 坏类型\npage_type: 123\n---\n正文",
        }
    ]
    preview = await service.preview(
        db_session,
        project_novel_id,
        _dataset_manifest(
            dataset_name="坏类型集",
            commit_mode="full_snapshot",
            files=files,
        ),
    )
    assert {item.page_type for item in preview.items} == {"123"}
    with pytest.raises(ValidationError, match="category"):
        await service.apply(
            db_session,
            project_novel_id,
            preview.suggestion_id,
            _apply_request(preview),
        )
    assert await _drafts_of(db_session, project_novel_id) == []
