import pytest

from modules.story.outline_state.review_attention import needs_scene_decision
from modules.story.outline_state.scene_resolution import (
    SceneBoundaryJudgment,
    materialize_anchors,
)


def test_scene_repair_anchors_are_unique_and_source_bound():
    evidence = [
        {
            "key": "chapter-1",
            "text": "开门。看见信。离开。",
            "source_ref": {
                "chapter_index": 1,
                "start_offset": 0,
                "draft_id": "d",
                "source_hash": "h",
            },
        }
    ]
    result = SceneBoundaryJudgment(
        scene_id="s",
        verdict="supported",
        confidence=0.95,
        explanation="完整行动",
        anchors=[
            {
                "evidence_key": "chapter-1",
                "start_anchor": "开门。",
                "end_anchor": "离开。",
            }
        ],
    )
    chunks = materialize_anchors(result, evidence)
    assert chunks[0]["start_pos"] == 0
    assert chunks[0]["end_pos"] == len(evidence[0]["text"])
    result.anchors[0].start_anchor = "不存在"
    with pytest.raises(ValueError):
        materialize_anchors(result, evidence)


def test_scene_attention_keeps_unknown_source_problems_but_not_optional_readings():
    assert needs_scene_decision(
        source="deep_import", status="draft", meta={"needs_review": True}
    )
    assert not needs_scene_decision(
        source="deep_import",
        status="draft",
        meta={"auto_ingested": True, "phase1b_source_fingerprint": "hash"},
    )
    assert not needs_scene_decision(
        source="deep_import",
        status="draft",
        meta={
            "review_issues_version": 1,
            "review_issues": [{"kind": "optional_interpretation", "required": False}],
        },
    )
    assert needs_scene_decision(
        source="deep_import",
        status="draft",
        meta={
            "review_issues_version": 1,
            "review_issues": [{"kind": "source_or_structure", "required": True}],
        },
    )


def test_source_boundary_success_does_not_certify_unproven_scene_constraints():
    from modules.story.outline_state.scene_resolution import review_issues

    frozen = {
        "fields": {
            "goal": "拿到信",
            "must_not_happen": "不可暴露身份",
            "emotional_beat": "紧张",
        }
    }
    judgment = SceneBoundaryJudgment(
        scene_id="s",
        verdict="supported",
        confidence=0.99,
        explanation="范围正确",
        field_evidence={"goal": ["他拿到信。"]},
    )
    issues = review_issues(frozen, judgment, [{"text": "他拿到信。"}])
    assert issues == [
        {"kind": "semantic_field", "field": "emotional_beat", "required": False},
        {"kind": "semantic_field", "field": "must_not_happen", "required": True},
    ]


async def test_missing_mapping_is_grouped_repaired_and_atomically_undone(
    db_session, test_project_id
):
    import hashlib
    import uuid
    from dataclasses import asdict

    from modules.story.outline_state.models import Scene
    from modules.story.outline_state.scene_resolution import (
        apply_group,
        group_scene_inputs,
        preview,
        rollback,
    )
    from modules.writing.facade import build_manuscript_range_ref
    from modules.writing.models import WritingDraft

    text = "甲开门。乙读信。"
    draft = WritingDraft(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status="published",
    )
    scenes = [
        Scene(
            novel_id=uuid.UUID(test_project_id),
            scene_index=index,
            title=label,
            goal=label,
            source="deep_import",
            status="draft",
            chapter_ids=["1"],
            scene_chunks=[],
            structure_meta={"needs_review": False},
        )
        for index, label in enumerate(("开门", "读信"))
    ]
    db_session.add_all([draft, *scenes])
    await db_session.flush()
    frozen = await preview(db_session, test_project_id, 1, 1)
    assert len(frozen) == 2 and all(item["missing_mapping"] for item in frozen)
    group = group_scene_inputs(frozen)[0]
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="working",
    )
    evidence = [{"key": "chapter-1", "text": text, "source_ref": asdict(ref)}]
    judgments = [
        SceneBoundaryJudgment(
            scene_id=str(scene.id),
            verdict="adjust",
            confidence=0.95,
            explanation="原文形成连续场景",
            anchors=[
                {"evidence_key": "chapter-1", "start_anchor": quote, "end_anchor": quote}
            ],
            field_evidence={"goal": [quote]},
        )
        for scene, quote in zip(scenes, ("甲开门。", "乙读信。"), strict=True)
    ]
    receipt = await apply_group(
        db_session,
        novel_id=test_project_id,
        frozen=group,
        judgments=judgments,
        evidence=evidence,
        workflow_id="repair-test",
    )
    assert receipt["outcome"] == "organized"
    assert [scene.scene_chunks[0]["start_pos"] for scene in scenes] == [0, 4]
    assert (
        await rollback(db_session, novel_id=test_project_id, receipt=receipt)
        == "rolled_back"
    )
    assert all(scene.scene_chunks == [] for scene in scenes)


async def test_scene_group_rejects_overlap_before_any_write(db_session, test_project_id):
    import hashlib
    import uuid
    from dataclasses import asdict

    from modules.story.outline_state.models import Scene
    from modules.story.outline_state.scene_resolution import (
        apply_group,
        group_scene_inputs,
        preview,
    )
    from modules.writing.facade import build_manuscript_range_ref
    from modules.writing.models import WritingDraft

    text = "甲开门。乙读信。"
    draft = WritingDraft(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status="published",
    )
    scenes = [
        Scene(
            novel_id=uuid.UUID(test_project_id),
            scene_index=i,
            title=str(i),
            source="deep_import",
            status="draft",
            chapter_ids=["1"],
            scene_chunks=[],
            structure_meta={},
        )
        for i in range(2)
    ]
    db_session.add_all([draft, *scenes])
    await db_session.flush()
    group = group_scene_inputs(await preview(db_session, test_project_id, 1, 1))[0]
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="working",
    )
    judgments = [
        SceneBoundaryJudgment(
            scene_id=str(scene.id),
            verdict="adjust",
            confidence=0.99,
            explanation="错误重复范围",
            anchors=[
                {
                    "evidence_key": "chapter-1",
                    "start_anchor": "甲开门。",
                    "end_anchor": "乙读信。",
                }
            ],
        )
        for scene in scenes
    ]
    with pytest.raises(ValueError, match="空洞、重叠"):
        await apply_group(
            db_session,
            novel_id=test_project_id,
            frozen=group,
            judgments=judgments,
            evidence=[{"key": "chapter-1", "text": text, "source_ref": asdict(ref)}],
            workflow_id="repair-test",
        )
    assert all(
        scene.scene_chunks == [] and scene.structure_meta == {} for scene in scenes
    )


async def test_protected_source_group_requires_concrete_confirmation_and_undo_is_atomic(
    db_session, test_project_id
):
    import hashlib
    import uuid
    from dataclasses import asdict

    from modules.story.outline_state.models import Scene
    from modules.story.outline_state.scene_resolution import (
        apply_group,
        group_scene_inputs,
        preview,
        rollback,
    )
    from modules.writing.facade import build_manuscript_range_ref
    from modules.writing.models import WritingDraft

    text = "甲开门。乙读信。"
    draft = WritingDraft(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        status="published",
    )
    scenes = [
        Scene(
            novel_id=uuid.UUID(test_project_id),
            scene_index=i,
            title=str(i),
            source="deep_import",
            status="canonical",
            chapter_ids=["1"],
            scene_chunks=[],
            structure_meta={},
        )
        for i in range(2)
    ]
    db_session.add_all([draft, *scenes])
    await db_session.flush()
    group = group_scene_inputs(await preview(db_session, test_project_id, 1, 1))[0]
    ref = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=str(draft.id),
        start_offset=0,
        end_offset=len(text),
        content_mode="working",
    )
    evidence = [{"key": "chapter-1", "text": text, "source_ref": asdict(ref)}]
    judgments = [
        SceneBoundaryJudgment(
            scene_id=str(scene.id),
            verdict="adjust",
            confidence=0.99,
            explanation="补定位",
            anchors=[
                {"evidence_key": "chapter-1", "start_anchor": quote, "end_anchor": quote}
            ],
        )
        for scene, quote in zip(scenes, ("甲开门。", "乙读信。"), strict=True)
    ]
    proposal = await apply_group(
        db_session,
        novel_id=test_project_id,
        frozen=group,
        judgments=judgments,
        evidence=evidence,
        workflow_id="repair",
    )
    assert (
        proposal["can_apply"] and proposal["preview"][0]["before_start"] == "未精确定位"
    )
    assert all(scene.scene_chunks == [] for scene in scenes)
    receipt = await apply_group(
        db_session,
        novel_id=test_project_id,
        frozen=group,
        judgments=judgments,
        evidence=evidence,
        workflow_id="repair",
        confirmed=True,
    )
    scenes[0].structure_meta = {**scenes[0].structure_meta, "user_edited": True}
    await db_session.flush()
    assert (
        await rollback(db_session, novel_id=test_project_id, receipt=receipt)
        == "conflict"
    )
    assert all(scene.scene_chunks for scene in scenes)


def test_uncertain_field_explanations_cannot_bypass_named_field_guard():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SceneBoundaryJudgment(
            scene_id="s",
            verdict="supported",
            confidence=0.99,
            explanation="保留不确定字段",
            uncertain_fields=["must_happen：缺少证据"],
        )
