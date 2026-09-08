"""Real World/Writing/Scene seams; only the optional LLM response is stubbed."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from core.errors import ConflictError
from modules.evidence.compilation.contracts import CompileOptions
from modules.evidence.compilation.focused_contracts import (
    FocusedEvidenceLimits,
    FocusedEvidenceRequest,
    FocusedEvidenceRoot,
)
from modules.evidence.compilation.services.focused_evidence import (
    FocusedEvidenceService,
    NeighborNominations,
)
from modules.story.outline_state.models import Scene, SceneSpan
from modules.world.models import Character, CharacterKnowledge, CoreEntity, EntityRelation
from modules.writing.facade import create_published_draft_only


async def entity(db, novel, name, **extra):
    row = CoreEntity(
        novel_id=uuid.UUID(novel),
        entity_type="location",
        name=name,
        status="canonical",
        reveal_level="revealed",
        **extra,
    )
    db.add(row)
    await db.flush()
    return row


def request(novel, root, **extra):
    return FocusedEvidenceRequest(
        novel_id=novel,
        roots=[
            FocusedEvidenceRoot(
                key="root",
                target_ref={"target_type": "entity", "target_id": str(root.id)},
            )
        ],
        sources=["world", "manuscript"],
        max_depth=0,
        limits=FocusedEvidenceLimits(chapters_per_batch=1, semantic_top_k=0),
        **extra,
    )


async def silence_llm(*args, **kwargs):
    return NeighborNominations()


@pytest.mark.asyncio
async def test_scene_hides_current_profile_future_alias_and_untimed_neighbors(
    db_session, test_project_id, monkeypatch
):
    root = await entity(
        db_session,
        test_project_id,
        "根城",
        summary="第九章根城沉没",
        public_info="后来成为王都",
        hidden_truth="身份秘密",
        content_json={"aliases": [{"alias": "未来密名", "status": "active"}]},
    )
    future = await entity(db_session, test_project_id, "未来邻居")
    current = "根城今日平静。"
    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content=current + "未来密名隶属未来邻居。"
    )
    scene = Scene(
        novel_id=uuid.UUID(test_project_id),
        scene_index=1,
        status="canonical",
        title="当前",
        chapter_ids=[1],
    )
    db_session.add(scene)
    await db_session.flush()
    db_session.add(
        SceneSpan(
            novel_id=uuid.UUID(test_project_id),
            scene_id=scene.id,
            chapter_index=1,
            part_no=1,
            content_mode="canonical",
            source_draft_id=uuid.UUID(draft.id),
            source_content_hash=draft.content_hash,
            start_offset=0,
            end_offset=len(current),
            mapping_status="exact",
        )
    )
    db_session.add(
        EntityRelation(
            novel_id=uuid.UUID(test_project_id),
            source_id=root.id,
            target_id=future.id,
            status="canonical",
            relation_kind="spatial",
            relation_type="隶属",
        )
    )
    await db_session.flush()
    options = CompileOptions(
        novel_id=test_project_id,
        task="查阅",
        scope="scene",
        scene_id=str(scene.id),
        chapter_index=1,
    )
    query = request(test_project_id, root, compile_options=options)
    query.max_depth = 1
    monkeypatch.setattr(
        "modules.evidence.compilation.services.focused_evidence.run_managed_structured",
        silence_llm,
    )
    result = await FocusedEvidenceService().retrieve(
        db_session, query, llm_client=SimpleNamespace(model_name="fake")
    )
    visible = json.dumps(
        result.model_dump(mode="json", exclude={"continuation"}), ensure_ascii=False
    )
    visible += json.dumps(result.compiled_context, ensure_ascii=False)
    for hidden in ("第九章", "后来成为王都", "身份秘密", "未来密名", "未来邻居"):
        assert hidden not in visible
    assert result.targets[0].terms == ["根城"]
    assert any("时点" in warning for warning in result.warnings)
    assert {target.name for target in result.targets} == {"根城"}


@pytest.mark.asyncio
async def test_character_uses_frozen_knowledge_not_current_profile_or_hidden_alias_link(
    db_session, test_project_id
):
    root = await entity(
        db_session,
        test_project_id,
        "根城",
        summary="后章根城毁灭",
        public_info="后章王都",
        content_json={"aliases": [{"alias": "夜城", "status": "active"}]},
    )
    pov = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="character",
        name="旅人",
        status="canonical",
    )
    db_session.add(pov)
    await db_session.flush()
    db_session.add(
        Character(
            novel_id=pov.novel_id, entity_id=pov.id, name=pov.name, status="canonical"
        )
    )
    await db_session.flush()
    db_session.add(
        CharacterKnowledge(
            novel_id=pov.novel_id,
            character_id=pov.id,
            target_type="location",
            target_id=root.id,
            knowledge_level="full",
            known_content="根城有北门",
            source_chapter_index=1,
            status="canonical",
        )
    )
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城有北门。"
    )
    await create_published_draft_only(
        db_session, test_project_id, 2, content="夜城出现在传闻中。"
    )
    options = CompileOptions(
        novel_id=test_project_id,
        task="查阅",
        scope="chapter",
        reveal_mode="character",
        viewpoint_character_id=str(pov.id),
        visible_until_chapter=2,
    )
    query = request(test_project_id, root, compile_options=options)
    result = await FocusedEvidenceService().retrieve(db_session, query)
    text = "\n".join(item.text for item in result.evidence)
    assert "根城有北门" in text and "后章" not in text
    alias = FocusedEvidenceRequest(
        novel_id=test_project_id,
        roots=[FocusedEvidenceRoot(name="夜城")],
        compile_options=options,
        max_depth=0,
        sources=["world", "manuscript"],
        limits=FocusedEvidenceLimits(semantic_top_k=0),
    )
    result = await FocusedEvidenceService().retrieve(db_session, alias)
    assert result.targets[0].target_ref is None and result.targets[0].name == "夜城"
    assert "根城" not in json.dumps(
        result.model_dump(mode="json", exclude={"continuation"}), ensure_ascii=False
    )


@pytest.mark.asyncio
async def test_strict_continuation_rejects_current_world_profile_change(
    db_session, test_project_id
):
    root = await entity(db_session, test_project_id, "根城", summary="旧档案")
    for chapter in (1, 2):
        await create_published_draft_only(
            db_session, test_project_id, chapter, content="根城出场。"
        )
    service = FocusedEvidenceService()
    query = request(test_project_id, root)
    first = await service.retrieve(db_session, query)
    assert first.continuation
    root.summary = "改动档案"
    await db_session.flush()
    query.continuation = first.continuation
    with pytest.raises(ConflictError, match="source changed"):
        await service.retrieve(db_session, query)


@pytest.mark.asyncio
async def test_import_owned_fill_and_alias_add_keep_frozen_terms_but_removal_fails(
    db_session, test_project_id
):
    root = await entity(
        db_session,
        test_project_id,
        "根城",
        content_json={"aliases": [{"alias": "旧称", "status": "active"}]},
    )
    for chapter in (1, 2, 3):
        await create_published_draft_only(
            db_session, test_project_id, chapter, content="根城旧称出场。新增称号。"
        )
    options = CompileOptions(
        novel_id=test_project_id,
        task="补全",
        scope="full",
        consumer_action="imports.targeted_completion",
    )
    query = request(
        test_project_id,
        root,
        compile_options=options,
        continuation_target_policy="identity",
    )
    service = FocusedEvidenceService()
    first = await service.retrieve(db_session, query)
    root.summary = "授权填空"
    root.content_json = {
        "aliases": [
            {"alias": "旧称", "status": "active"},
            {"alias": "新增称号", "status": "active"},
        ]
    }
    await db_session.flush()
    query.continuation = first.continuation
    second = await service.retrieve(db_session, query)
    assert second.world_fingerprint == first.world_fingerprint
    assert (
        second.targets[0].terms == first.targets[0].terms
        and "新增称号" not in second.targets[0].terms
    )
    root.content_json = {"aliases": []}
    await db_session.flush()
    query.continuation = second.continuation
    with pytest.raises(ConflictError, match="search terms changed"):
        await service.retrieve(db_session, query)


@pytest.mark.asyncio
async def test_alias_owner_change_fails_and_namespace_exclusion_is_normalized(
    db_session, test_project_id
):
    root = await entity(
        db_session,
        test_project_id,
        "根城",
        content_json={"aliases": [{"alias": "旧称", "status": "active"}]},
    )
    for chapter in (1, 2):
        await create_published_draft_only(
            db_session, test_project_id, chapter, content="根城旧称出场。"
        )
    options = CompileOptions(
        novel_id=test_project_id,
        task="补全",
        scope="full",
        consumer_action="imports.targeted_completion",
    )
    service = FocusedEvidenceService()
    query = request(
        test_project_id,
        root,
        compile_options=options,
        continuation_target_policy="identity",
    )
    first = await service.retrieve(db_session, query)
    await entity(
        db_session,
        test_project_id,
        "另一城",
        content_json={"aliases": [{"alias": "旧称", "status": "active"}]},
    )
    query.continuation = first.continuation
    with pytest.raises(ConflictError, match="ownership changed"):
        await service.retrieve(db_session, query)
    query = request(test_project_id, root)
    query.compile_options.excluded_refs = [
        {
            "kind": "target",
            "target_ref": {
                "target_type": "world_entity",
                "target_id": root.id.hex.upper(),
            },
        }
    ]
    result = await service.retrieve(db_session, query)
    assert result.targets == [] and result.evidence == []


@pytest.mark.asyncio
async def test_full_adjacency_snapshot_detects_insert_between_graph_pages(
    db_session, test_project_id
):
    root = await entity(db_session, test_project_id, "根城")
    children = [
        await entity(db_session, test_project_id, name)
        for name in ("甲城", "乙城", "丙城")
    ]
    for child in children[:2]:
        db_session.add(
            EntityRelation(
                novel_id=root.novel_id,
                source_id=root.id,
                target_id=child.id,
                status="canonical",
                relation_kind="spatial",
                relation_type="邻接",
            )
        )
    await db_session.flush()
    query = request(test_project_id, root)
    query.sources = ["world"]
    query.max_depth = 1
    query.limits.neighbors_per_batch = 1
    service = FocusedEvidenceService()
    first = await service.retrieve(db_session, query)
    assert first.continuation and first.continuation.phase == "graph"
    db_session.add(
        EntityRelation(
            novel_id=root.novel_id,
            source_id=root.id,
            target_id=children[2].id,
            status="canonical",
            relation_kind="spatial",
            relation_type="邻接",
        )
    )
    await db_session.flush()
    query.continuation = first.continuation
    with pytest.raises(ConflictError, match="adjacency changed"):
        await service.retrieve(db_session, query)


@pytest.mark.asyncio
async def test_scene_http_cannot_claim_later_chapter_when_legacy_chunks_are_empty(
    async_client, db_session
):
    created = await async_client.post("/api/projects", json={"title": "范围验证"})
    novel = created.json()["id"]
    scene = Scene(
        novel_id=uuid.UUID(novel),
        scene_index=1,
        title="第一章场景",
        status="canonical",
        chapter_ids=[1],
        scene_chunks=[],
    )
    db_session.add(scene)
    await db_session.flush()
    response = await async_client.post(
        "/api/evidence/compilation/focused-search",
        json={
            "novel_id": novel,
            "roots": [{"name": "根城"}],
            "question": "补查",
            "consumer": "writing",
            "scene_id": str(scene.id),
            "chapter_index": 99,
            "max_depth": 0,
        },
    )
    assert response.status_code in {400, 422}, response.text


@pytest.mark.asyncio
async def test_ambiguous_alias_cannot_prove_the_wrong_root_across_source_ranges(
    db_session, test_project_id, monkeypatch
):
    alpha = await entity(db_session, test_project_id, "甲城")
    gamma = await entity(
        db_session,
        test_project_id,
        "丙城",
        content_json={"aliases": [{"alias": "甲城", "status": "active"}]},
    )
    await create_published_draft_only(
        db_session, test_project_id, 1, content="甲城邻接乙城。"
    )
    await create_published_draft_only(
        db_session, test_project_id, 2, content="丙城位于高原。甲城邻接乙城。"
    )

    async def wrong_root(client, call, schema, **kwargs):
        payload = json.loads(call.messages[1].content)
        return NeighborNominations(
            neighbors=[
                {
                    "root_key": "gamma",
                    "evidence_key": item["key"],
                    "name": "乙城",
                    "relation": "邻接",
                    "quote": "甲城邻接乙城",
                }
                for item in payload["evidence"]
            ]
        )

    monkeypatch.setattr(
        "modules.evidence.compilation.services.focused_evidence.run_managed_structured",
        wrong_root,
    )
    query = request(test_project_id, alpha)
    query.max_depth = 1
    query.limits.chapters_per_batch = 10
    query.roots.append(
        FocusedEvidenceRoot(
            key="gamma", target_ref={"target_type": "entity", "target_id": str(gamma.id)}
        )
    )
    service = FocusedEvidenceService()
    result = await service.retrieve(
        db_session, query, llm_client=SimpleNamespace(model_name="fake")
    )
    assert all(target.depth == 0 for target in result.targets)
    assert "甲城" not in next(t for t in result.targets if t.key == "gamma").proof_terms


@pytest.mark.asyncio
async def test_field_selection_does_not_expand_into_whole_current_profile(
    db_session, test_project_id
):
    root = await entity(
        db_session,
        test_project_id,
        "根城",
        public_info="允许的公开资料",
        summary="未选中的摘要",
        hidden_truth="未选中的秘密",
    )
    ref = {
        "target_type": "core_entity",
        "target_id": str(root.id),
        "target_path": "public_info",
    }
    options = CompileOptions(
        novel_id=test_project_id, task="查阅", scope="full", reveal_mode="author_full"
    )
    query = FocusedEvidenceRequest(
        novel_id=test_project_id,
        roots=[FocusedEvidenceRoot(target_ref=ref)],
        compile_options=options,
        allowed_refs=[{"kind": "target", "target_ref": ref}],
        max_depth=0,
        sources=["world"],
        limits=FocusedEvidenceLimits(semantic_top_k=0),
    )
    result = await FocusedEvidenceService().retrieve(db_session, query)
    text = "\n".join(item.text for item in result.evidence)
    assert "允许的公开资料" in text
    assert "未选中的摘要" not in text and "未选中的秘密" not in text
    assert result.targets[0].target_ref["target_path"] == "public_info"


@pytest.mark.asyncio
async def test_no_model_finishes_literal_and_database_reads_and_later_resumes_nomination(
    db_session, test_project_id, monkeypatch
):
    root = await entity(db_session, test_project_id, "根城")
    known = await entity(db_session, test_project_id, "旧邻居")
    db_session.add(
        EntityRelation(
            novel_id=root.novel_id,
            source_id=root.id,
            target_id=known.id,
            relation_kind="spatial",
            relation_type="邻接",
            status="canonical",
        )
    )
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城隶属北郡。"
    )
    await create_published_draft_only(
        db_session, test_project_id, 2, content="旧邻居有桥。北郡有塔。"
    )
    query = request(test_project_id, root)
    query.max_depth = 1
    service = FocusedEvidenceService()
    pages = []
    for _ in range(8):
        page = await service.retrieve(db_session, query, nomination_enabled=False)
        pages.append(page)
        if page.continuation and page.continuation.phase == "done":
            break
        query.continuation = page.continuation
    assert page.continuation and page.continuation.pending_nomination
    assert not page.coverage.complete and page.coverage.nomination_failed
    assert {
        item.source_ref.chapter_index
        for result in pages
        for item in result.evidence
        if item.source_ref
    } == {1, 2}
    assert {target.name for target in page.targets} == {"根城", "旧邻居"}

    async def nominate(client, call, schema, **kwargs):
        payload = json.loads(call.messages[1].content)
        hit = next(item for item in payload["evidence"] if "根城隶属北郡" in item["text"])
        return NeighborNominations(
            neighbors=[
                {
                    "root_key": "root",
                    "evidence_key": hit["key"],
                    "name": "北郡",
                    "relation": "隶属",
                    "quote": "根城隶属北郡",
                }
            ]
        )

    monkeypatch.setattr(
        "modules.evidence.compilation.services.focused_evidence.run_managed_structured",
        nominate,
    )
    query.continuation = page.continuation
    resumed = []
    for _ in range(5):
        result = await service.retrieve(
            db_session, query, llm_client=SimpleNamespace(model_name="fake")
        )
        resumed.extend(item for item in result.evidence if item.source_ref)
        if result.continuation is None:
            break
        query.continuation = result.continuation
    assert result.coverage.complete
    assert {item.source_ref.chapter_index for item in resumed} == {1, 2}
    beta = next(target for target in result.targets if target.name == "北郡")
    assert all(beta.key in item.target_keys for item in resumed)


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_failure", [False, True])
async def test_snapshot_failure_preserves_task_evidence_without_provider_fallback(
    db_session, test_project_id, monkeypatch, restore_failure
):
    from infrastructure.tasks.facade import run_task_inline
    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.compilation.focused_tasks import (
        FOCUSED_TASK,
        FocusedSearchSubmit,
        submit_focused_search,
    )
    from modules.project.contracts import ProjectLLMConfigurationError

    root = await entity(db_session, test_project_id, "根城")
    await create_published_draft_only(
        db_session, test_project_id, 1, content="根城隶属北郡。"
    )

    async def build(*args, **kwargs):
        if restore_failure:
            return {"test": "frozen provider"}
        raise ProjectLLMConfigurationError("connection missing")

    async def restore(*args, **kwargs):
        raise ProjectLLMConfigurationError("frozen provider unavailable")

    def forbidden(*args, **kwargs):
        raise AssertionError("must not create a fallback provider client")

    monkeypatch.setattr(
        "modules.evidence.compilation.focused_tasks.build_project_llm_execution_snapshot",
        build,
    )
    monkeypatch.setattr(
        "modules.evidence.compilation.focused_tasks.restore_project_llm_execution_settings",
        restore,
    )
    monkeypatch.setattr(
        "modules.evidence.compilation.focused_tasks.create_project_snapshot_llm_client",
        forbidden,
    )
    monkeypatch.setattr("modules.project.facade.open_project_llm_client", forbidden)
    submitted = await submit_focused_search(
        db_session,
        FocusedSearchSubmit(
            novel_id=test_project_id,
            roots=[FocusedEvidenceRoot(name=root.name)],
            question="查阅",
            max_depth=1,
            sources=["world", "manuscript"],
        ),
    )
    payload = await run_task_inline(
        db_session, task_id=submitted["task_id"], expected_task_type=FOCUSED_TASK
    )
    result = payload["_focused_result"]
    assert result["evidence"] and result["coverage"]["nomination_failed"]
    assert result["continuation"] and "根城隶属北郡" not in json.dumps(
        result["evidence"], ensure_ascii=False
    )
    task = await db_session.get(AsyncTask, uuid.UUID(submitted["task_id"]))
    await db_session.refresh(task)
    assert task.status == "done"
    assert payload["_llm_execution_snapshot"] == (
        {"test": "frozen provider"} if restore_failure else None
    )


async def known_character(db, novel, target, known):
    pov = CoreEntity(
        novel_id=uuid.UUID(novel),
        entity_type="character",
        name="旅人",
        status="canonical",
    )
    db.add(pov)
    await db.flush()
    db.add(
        Character(
            novel_id=pov.novel_id, entity_id=pov.id, name=pov.name, status="canonical"
        )
    )
    await db.flush()
    row = CharacterKnowledge(
        novel_id=pov.novel_id,
        character_id=pov.id,
        target_type="location",
        target_id=target.id,
        knowledge_level="full",
        known_content=known,
        source_chapter_index=1,
        status="canonical",
    )
    db.add(row)
    await db.flush()
    return pov, row


@pytest.mark.asyncio
@pytest.mark.parametrize("secret_chapter", [1, 2])
async def test_character_never_reads_unlearned_narrator_secret_even_for_known_object(
    db_session, test_project_id, secret_chapter
):
    from dataclasses import replace

    root = await entity(db_session, test_project_id, "根城")
    known = "根城有北门。"
    secret = "密室囚禁邪神，旅人对此一无所知。"
    for chapter in range(1, secret_chapter + 1):
        await create_published_draft_only(
            db_session,
            test_project_id,
            chapter,
            content=known + (secret if chapter == secret_chapter else ""),
        )
    pov, _ = await known_character(db_session, test_project_id, root, known)
    options = CompileOptions(
        novel_id=test_project_id,
        task="查阅",
        scope="chapter",
        reveal_mode="character",
        viewpoint_character_id=str(pov.id),
        visible_until_chapter=2,
        visible_until_offset=10000,
    )
    query = request(test_project_id, root, compile_options=options)
    query.limits.chapters_per_batch = 10
    result = await FocusedEvidenceService().retrieve(db_session, query)
    assert any(known in item.text for item in result.evidence)
    assert not any(item.source_ref for item in result.evidence)
    assert secret not in json.dumps(result.compiled_context, ensure_ascii=False)
    assert result.coverage.character_ranges_omitted > 0
    assert result.coverage.knowledge_boundary_audit == "not_performed"
    assert any("角色获知" in warning for warning in result.warnings)
    for reveal in ("reader", "author_full"):
        full = request(
            test_project_id,
            root,
            compile_options=replace(
                options, reveal_mode=reveal, viewpoint_character_id=None
            ),
        )
        full.limits.chapters_per_batch = 10
        readable = await FocusedEvidenceService().retrieve(db_session, full)
        assert any(secret in item.text for item in readable.evidence if item.source_ref)


@pytest.mark.asyncio
async def test_only_exact_linked_full_knowledge_range_is_character_readable(
    db_session, test_project_id
):
    from dataclasses import asdict

    from modules.evidence.facade import record_evidence_link
    from modules.writing.facade import build_manuscript_range_ref

    root = await entity(db_session, test_project_id, "根城")
    known = "根城有北门。"
    hidden = "密室囚禁邪神。"
    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content=known + hidden
    )
    pov, knowledge = await known_character(db_session, test_project_id, root, known)
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=draft.id,
        start_offset=0,
        end_offset=len(known),
        content_mode="canonical",
    )
    await record_evidence_link(
        db_session,
        novel_id=test_project_id,
        target_ref={
            "target_type": "character_knowledge",
            "target_id": str(knowledge.id),
            "target_path": "known_content",
        },
        source_ref=ref,
        claim_path="known_content",
    )
    options = CompileOptions(
        novel_id=test_project_id,
        task="查阅",
        scope="chapter",
        reveal_mode="character",
        viewpoint_character_id=str(pov.id),
        visible_until_chapter=3,
        pinned_refs=[{"kind": "source_range", "source_ref": asdict(ref)}],
    )
    query = request(test_project_id, root, compile_options=options)
    result = await FocusedEvidenceService().retrieve(db_session, query)
    originals = [item for item in result.evidence if item.source_ref]
    assert len(originals) == 1 and originals[0].text == known
    assert result.coverage.character_ranges_verified == 1
    assert result.coverage.character_ranges_omitted == 1
    assert not result.blockers and hidden not in json.dumps(
        result.compiled_context, ensure_ascii=False
    )
    knowledge.known_content = "只知道根城存在"
    await db_session.flush()
    stale = await FocusedEvidenceService().retrieve(db_session, query)
    assert not any(item.source_ref for item in stale.evidence)
    assert stale.blockers and stale.compiled_context["blockers"]
