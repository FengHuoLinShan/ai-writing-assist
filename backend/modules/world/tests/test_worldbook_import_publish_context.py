"""理法之环 Wiki 导入 M4：发布、作者上下文与角色视角边界。

覆盖 TASK.md 里程碑 M4 的可验证部分（对照 m1-contract.md 第 9 条 M4 验收）：

1. 导入只产生未发布工作稿；来源声明 ``canon_status: canonical`` 不自动发布、
   不自动激活（TASK.md 决策 5、验证矩阵 Evidence/Canon 行）。
2. 发布必须走既有 Canon Preview/Admit 与校验回执；``source_material`` 的
   ``activation_eligible=False``，且角色/读者视角不消费作者原始资料——
   activation 预览在 character/reader 模式排除全部目标，编译器只对作者
   模式加载世界书简介与工作稿。
3. Evidence confirmation 绑定作者 AI 实际消费的工作稿版本（选中资产、
   上下文指纹、排除项），来源更新经既有 ``update_draft →
   mark_asset_context_changed`` 失效链使旧确认/回执失效。

Evidence 一律经 ``modules.evidence.facade`` 接入；全部合成资料，
不触碰本机真实 Wiki。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.schemas import (
    ContextActivationProfileCreate,
    ContextActivationProfilePublishRequest,
)
from modules.evidence.compilation.services.compiled_context import (
    compiled_context_fingerprint,
)
from modules.evidence.facade import (
    compile_from_confirmation,
    confirm_context,
    create_activation_profile,
    preview_activation,
    publish_activation_profile,
    require_confirmation,
    require_fresh_confirmation,
)
from modules.world.facade import initialize_world_canon
from modules.world.models import WorldBiblePage, WorldBiblePageDraft
from modules.world.schemas import (
    WorldbookImportApplyRequest,
    WorldbookImportManifest,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)


def _ring_pages() -> list[dict[str, str]]:
    """合成两页：概念正文（来源声明 canonical）+ 作者原始 raw 资料。

    ``canon_status: canonical`` 只是外部 Wiki 的来源声明；契约明确它不代替
    站内采用，也不得触发自动发布或激活。
    """
    return [
        {
            "path": "ring/concepts/真名回响/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n"
                "canon_status: canonical\n---\n"
                "以理法编织万物的环，维系真名回响的秩序。"
            ),
        },
        {
            "path": "ring/raw/理法之环_原始笔记.txt",
            "content": "作者原始笔记：理法之环尚未整理的真相与伏笔。",
        },
    ]


def _dataset_manifest(files: list[dict[str, str]]) -> WorldbookImportManifest:
    return WorldbookImportManifest(
        schema_version="world_worldbook_import.v2",
        source_format="obsidian",
        dataset_name="理法之环",
        dataset_intent="continue",
        commit_mode="full_snapshot",
        files=files,
    )


async def _apply_pages(
    db: AsyncSession, novel_id: str, files: list[dict[str, str]]
) -> dict[str, WorldBiblePageDraft]:
    """预览并应用一次资料集导入，返回「标题 → 工作稿」映射。"""
    service = WorldbookImportService()
    preview = await service.preview(db, novel_id, _dataset_manifest(files))
    applied = await service.apply(
        db,
        novel_id,
        preview.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=preview.preview_hash),
    )
    assert applied.status == "accepted"
    drafts = (
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
    return {draft.title: draft for draft in drafts}


async def _project_pages(db: AsyncSession, novel_id: str) -> list[WorldBiblePage]:
    return list(
        (
            await db.execute(
                select(WorldBiblePage).where(
                    WorldBiblePage.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_canonical_source_import_stays_unpublished_and_inactive(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """来源声明 canonical 不自动发布：导入只落未发布工作稿与候选元数据。

    source_material 的 activation_eligible 必须为 False；canonical 声明只能
    作为来源元数据保留，不得改写权威状态，也不得创建正式页。
    """
    drafts = await _apply_pages(db_session, project_novel_id, _ring_pages())
    assert set(drafts) == {"理法之环", "理法之环_原始笔记"}
    # 默认未发布：apply 之后项目内没有任何正式页。
    assert await _project_pages(db_session, project_novel_id) == []

    concept = drafts["理法之环"]
    raw = drafts["理法之环_原始笔记"]
    concept_meta = concept.page_meta_json["worldbook_import"]
    raw_meta = raw.page_meta_json["worldbook_import"]
    # 权威仍为 candidate；激活资格只由 page_type 决定。
    assert concept_meta["source_authority_hint"] == "candidate"
    assert raw_meta["source_authority_hint"] == "candidate"
    assert concept_meta["activation_eligible"] is True
    assert raw_meta["activation_eligible"] is False
    # 来源 canonical 声明仅作为 frontmatter 元数据保留，不产生站内采用语义。
    assert concept_meta["frontmatter"]["canon_status"] == "canonical"
    assert raw_meta["frontmatter"] == {}


@pytest.mark.asyncio
async def test_imported_draft_publishes_only_through_canon_admit(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """发布走既有 Canon Preview/Admit + 校验回执；导入自身不产生正式页。"""
    drafts = await _apply_pages(db_session, project_novel_id, _ring_pages())
    service = WorldbookImportService()
    ring_preview = await service.preview(
        db_session, project_novel_id, _dataset_manifest(_ring_pages())
    )
    ring_items = {
        item.title: item for item in ring_preview.items if item.action == "preserve"
    }

    await initialize_world_canon(db_session, project_novel_id)
    published = await WorldBibleLifecycleService().admit_draft(
        db_session,
        project_novel_id,
        str(drafts["理法之环"].id),
        authorizer_id=BOOTSTRAP_ACCOUNT_ID,
    )
    assert published.status == "canonical"
    assert published.version_number == 1
    # 发布必须携带既有校验回执（targeted scope）。
    assert published.validation_receipt is not None
    assert published.validation_receipt.scope == "targeted"
    # 导入元数据随发布进入正式页，作者仍可追溯到来源版本。
    assert (
        published.page_meta_json["worldbook_import"]["source_key"]
        == ring_items["理法之环"].source_key
    )
    # 只有作者显式签发的那一页成为正式页；raw 资料保持未发布工作稿。
    pages = await _project_pages(db_session, project_novel_id)
    assert [page.title for page in pages] == ["理法之环"]
    remaining = await db_session.execute(
        select(WorldBiblePageDraft).where(
            WorldBiblePageDraft.novel_id == uuid.UUID(project_novel_id)
        )
    )
    assert {draft.title for draft in remaining.scalars().all()} == {"理法之环_原始笔记"}


@pytest.mark.asyncio
async def test_published_import_material_excluded_from_character_and_reader_views(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """作者资料不进入角色/读者视角：activation 与编译器都按 reveal 门禁排除。"""
    from modules.evidence.compilation.services.context_compiler import ContextCompiler
    from modules.evidence.compilation.services.review_projection import (
        selected_asset_ids_from_compiled,
    )

    drafts = await _apply_pages(
        db_session,
        project_novel_id,
        [
            {
                "path": "ring/raw/理法之环_原始笔记.txt",
                "content": "作者原始笔记：理法之环尚未整理的真相与伏笔。",
            }
        ],
    )
    draft = drafts["理法之环_原始笔记"]
    await initialize_world_canon(db_session, project_novel_id)
    page = await WorldBibleLifecycleService().admit_draft(
        db_session,
        project_novel_id,
        str(draft.id),
        authorizer_id=BOOTSTRAP_ACCOUNT_ID,
    )

    profile = await create_activation_profile(
        db_session,
        ContextActivationProfileCreate(
            novel_id=project_novel_id,
            profile_key="writing.ring",
            name="理法之环资料",
            applicable_actions_json=["writing.scene.generate"],
            rules_json=[
                {
                    "rule_id": "ring_material",
                    "name": "理法之环原始资料",
                    "enabled": True,
                    "scope": {
                        "actions": ["writing.scene.generate"],
                        # scope 声明含 character/reader：证明即使规则声明覆盖
                        # 这些模式，activation 仍按视角门禁排除作者资料。
                        "modes": [
                            "author_safe",
                            "author_full",
                            "character",
                            "reader",
                        ],
                        "match_sources": ["task_text"],
                    },
                    "match": {
                        "positive_terms": ["理法之环"],
                        "negative_terms": [],
                        "positive_logic": "any",
                        "negative_logic": "any",
                        "mode": "normalized_substring",
                    },
                    "select": {
                        "target_refs": [
                            {
                                "target_type": "world_bible_page",
                                "target_id": page.id,
                                "target_path": "",
                            }
                        ],
                        "expand_page_links": False,
                        "relation_types": [],
                        "max_depth": 0,
                    },
                    "rank": {"priority": 700, "top_k": 12, "token_cap": 1200},
                }
            ],
        ),
    )
    await publish_activation_profile(
        db_session,
        project_novel_id,
        profile.id,
        ContextActivationProfilePublishRequest(base_version_number=1),
    )

    def _preview(reveal_mode: str):
        return preview_activation(
            db_session,
            novel_id=project_novel_id,
            action="writing.scene.generate",
            profile_id=profile.id,
            reveal_mode=reveal_mode,
            task_text="描写理法之环的环律细节",
        )

    # 作者模式：正典页可被规则命中。
    author = await _preview("author_safe")
    assert [item["target"]["target_id"] for item in author["items"]] == [page.id]
    # 角色视角：资料整体排除，不因导入新增作者隐藏真相。
    character = await _preview("character")
    assert character["items"] == []
    assert character["excluded_items"]
    assert {item["excluded_reason"] for item in character["excluded_items"]} == {
        "character_knowledge_hidden"
    }
    reader = await _preview("reader")
    assert reader["items"] == []
    assert {item["excluded_reason"] for item in reader["excluded_items"]} == {
        "reader_cutoff"
    }

    # 编译器：工作稿与世界书简介仅在作者模式加载；character 视角既不产生
    # 世界书节，也不把工作稿计入确认资产。
    options = CompileOptions(
        novel_id=project_novel_id,
        task="以角色视角描写环城场景",
        scope="project",
        consumer_action="writing.generate",
        reveal_mode="character",
        include_world_synopsis=True,
        selected_world_bible_draft_ids=[str(draft.id)],
        budget_tokens=4000,
    )
    compiled = await ContextCompiler().compile_with_tiers(
        db_session,
        options,
        budget_tokens=4000,
    )
    assert not any(section.key.startswith("world_bible") for section in compiled.sections)
    assert any(warning.startswith("excluded_visibility") for warning in compiled.warnings)
    assert "world_bible_draft" not in selected_asset_ids_from_compiled(
        compiled, novel_id=project_novel_id
    )


@pytest.mark.asyncio
async def test_confirmation_binds_draft_version_and_source_update_stales_it(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    """Evidence 确认消费的工作稿版本可核查；来源更新使旧确认按既有机制失效。"""
    service = WorldbookImportService()
    files = [
        {
            "path": "ring/concepts/真名回响/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n---\n"
                "以理法编织万物的环，维系真名回响的秩序。"
            ),
        }
    ]
    drafts = await _apply_pages(db_session, project_novel_id, files)
    draft = drafts["理法之环"]
    source_hash = draft.page_meta_json["worldbook_import"]["source_hash"]

    confirmation = await confirm_context(
        db_session,
        novel_id=project_novel_id,
        action="writing.generate",
        task="以理法之环设定生成场景草稿",
        scope="chapter",
        chapter_index=1,
        selected_world_bible_draft_ids=[str(draft.id)],
    )
    # 确认记录绑定实际消费的资产与排除项，指纹可复核。
    assert confirmation.selected_asset_ids["world_bible_draft"] == [str(draft.id)]
    assert confirmation.context_fingerprint
    assert confirmation.compile_options["selected_world_bible_draft_ids"] == [
        str(draft.id)
    ]
    assert confirmation.selection_state["status"] == "ready"
    assert confirmation.selection_state["counts"]["excluded"] >= 0
    working_section = next(
        section
        for section in (confirmation.sections or [])
        if section["key"] == "world_bible_working_pages"
    )
    # 版本绑定：确认内容携带当时消费的来源 hash。
    assert source_hash in working_section["content"]
    working_items = working_section.get("items") or []
    selection_ref = next(
        item["selection_ref"]
        for item in working_items
        if (item.get("selection_ref") or {}).get("target_ref", {}).get("target_id")
        == str(draft.id)
    )
    # 逐项排除也记录在确认的选择状态里，可核查"作者排除了什么"。
    excluded_confirmation = await confirm_context(
        db_session,
        novel_id=project_novel_id,
        action="writing.generate",
        task="排除工作稿的生成",
        scope="chapter",
        chapter_index=1,
        selected_world_bible_draft_ids=[str(draft.id)],
        excluded_refs=[dict(selection_ref)],
    )
    assert excluded_confirmation.selection_state["counts"]["excluded"] == 1
    excluded_entries = excluded_confirmation.selection_state["excluded_items"]
    assert excluded_entries
    assert str(draft.id) in str(excluded_entries[0])

    # 未变化时重放同一确认指纹成立。
    replayed = await compile_from_confirmation(
        db_session,
        novel_id=project_novel_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert compiled_context_fingerprint(replayed) == confirmation.context_fingerprint

    # 来源变化重导：来源变化且本地仍等于 baseline → 安全更新工作稿。
    changed = [dict(files[0])]
    changed[0]["content"] = changed[0]["content"].replace(
        "维系真名回响的秩序。", "维系真名回响的秩序；第二版补充环律细节。"
    )
    second = await service.preview(
        db_session, project_novel_id, _dataset_manifest(changed)
    )
    assert second.counts["update"] == 1
    applied = await service.apply(
        db_session,
        project_novel_id,
        second.suggestion_id,
        WorldbookImportApplyRequest(expected_preview_hash=second.preview_hash),
    )
    assert applied.status == "accepted"
    await db_session.refresh(draft)
    updated_hash = draft.page_meta_json["worldbook_import"]["source_hash"]
    assert updated_hash != source_hash

    # 既有失效链：update_draft → mark_asset_context_changed → 确认失效。
    stored = await require_confirmation(
        db_session,
        novel_id=project_novel_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert stored.result_status == "stale_context"
    assert "world_bible_draft_updated" in stored.stale_reasons
    with pytest.raises(ValueError, match="参考资料已更新"):
        await require_fresh_confirmation(
            db_session,
            novel_id=project_novel_id,
            action="writing.generate",
            confirmation_id=confirmation.id,
        )
    # 指纹重放失败关闭：消费版本已变化，不得继续用旧上下文。
    with pytest.raises(ConflictError, match="参考资料已变化") as exc_info:
        await compile_from_confirmation(
            db_session,
            novel_id=project_novel_id,
            action="writing.generate",
            confirmation_id=confirmation.id,
        )
    assert exc_info.value.code == "context_changed"
