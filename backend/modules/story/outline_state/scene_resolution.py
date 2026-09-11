"""Source-bound review of existing Scene boundaries, preserving Scene identities."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from modules.story.outline_state.models import Scene
from modules.story.outline_state.repositories import SceneRepository
from modules.story.outline_state.schemas import SceneUpdate
from shared.utils import parse_uuid


class SceneBoundaryAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str
    start_anchor: str = Field(min_length=1, max_length=400)
    end_anchor: str = Field(min_length=1, max_length=400)


class SceneBoundaryJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    verdict: Literal["supported", "adjust", "split_or_merge", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    anchors: list[SceneBoundaryAnchor] = Field(default_factory=list, max_length=30)
    explanation: str = Field(min_length=1, max_length=1500)
    uncertain_fields: list[
        Literal[
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
        ]
    ] = Field(default_factory=list, max_length=16)
    field_evidence: dict[
        Literal[
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
        ],
        list[str],
    ] = Field(default_factory=dict)


class SceneBoundaryReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[SceneBoundaryJudgment] = Field(max_length=32)


def fingerprint(scene):
    data = {
        key: deepcopy(getattr(scene, key))
        for key in (
            "status",
            "scene_index",
            "source",
            "scene_chunks",
            "chapter_ids",
            "structure_meta",
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
        )
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


async def preview(db, novel_id, chapter_from, chapter_to):
    rows = (
        await db.scalars(
            select(Scene)
            .where(
                Scene.novel_id == parse_uuid(novel_id),
                Scene.status.in_(("draft", "candidate", "canonical")),
            )
            .order_by(Scene.scene_index)
        )
    ).all()
    spans_by_scene = defaultdict(list)
    for span in await SceneRepository().get_scene_spans_for_scenes(
        db, parse_uuid(novel_id), [row.id for row in rows]
    ):
        spans_by_scene[span.scene_id].append(span)
    result = []
    for row in rows:
        chapters = [int(value) for value in row.chapter_ids or [] if str(value).isdigit()]
        if not chapters or min(chapters) < chapter_from or max(chapters) > chapter_to:
            continue
        spans = spans_by_scene[row.id]
        missing_mapping = not spans or any(
            span.mapping_status not in {"exact", "reanchored"}
            or not span.source_content_hash
            for span in spans
        )
        result.append(
            {
                "scene_id": str(row.id),
                "scene_index": row.scene_index,
                "needs_resolution": bool((row.structure_meta or {}).get("needs_review"))
                or missing_mapping,
                "missing_mapping": missing_mapping,
                "fingerprint": fingerprint(row),
                "chapters": chapters,
                "title": row.title,
                "fields": {
                    key: getattr(row, key)
                    for key in (
                        "goal",
                        "core_conflict",
                        "emotional_beat",
                        "must_happen",
                        "must_not_happen",
                    )
                },
                "chunks": deepcopy(row.scene_chunks or []),
                "meta": deepcopy(row.structure_meta or {}),
                "protected": row.source != "deep_import"
                or row.status == "canonical"
                or bool((row.structure_meta or {}).get("user_edited")),
            }
        )
    groups = group_scene_inputs(result)
    return [
        member
        for group in groups
        if any(member["needs_resolution"] for member in group["members"])
        for member in group["members"]
    ]


def group_scene_inputs(rows):
    groups = []
    for row in sorted(rows, key=lambda item: (min(item["chapters"]), item["scene_id"])):
        touching = [
            group
            for group in groups
            if set(group["chapters"]).intersection(row["chapters"])
        ]
        members = [row]
        for group in touching:
            members.extend(group["members"])
            groups.remove(group)
        members.sort(key=lambda item: (item.get("scene_index", 0), item["scene_id"]))
        key = hashlib.sha256(
            json.dumps(
                [(item["scene_id"], item["fingerprint"]) for item in members]
            ).encode()
        ).hexdigest()
        groups.append(
            {
                "group_key": key,
                "scene_id": members[0]["scene_id"],
                "fingerprint": key,
                "members": members,
                "chapters": sorted(
                    {chapter for item in members for chapter in item["chapters"]}
                ),
                "title": "、".join(item.get("title") or "场景" for item in members),
            }
        )
    return groups


def materialize_anchors(judgment, evidence):
    by_key = {item["key"]: item for item in evidence}
    chunks = []
    for anchor in judgment.anchors:
        source = by_key.get(anchor.evidence_key)
        if (
            source is None
            or source["text"].count(anchor.start_anchor) != 1
            or source["text"].count(anchor.end_anchor) != 1
        ):
            raise ValueError("场景修复锚点无法唯一定位")
        start = source["text"].index(anchor.start_anchor)
        end = source["text"].index(anchor.end_anchor) + len(anchor.end_anchor)
        if start >= end:
            raise ValueError("场景修复范围顺序错误")
        ref = source["source_ref"]
        chunks.append(
            {
                "chapter_index": ref["chapter_index"],
                "start_pos": ref["start_offset"] + start,
                "end_pos": ref["start_offset"] + end,
                "source_draft_id": ref["draft_id"],
                "source_content_hash": ref["source_hash"],
            }
        )
    if not chunks:
        raise ValueError("场景修复没有正文锚点")
    return chunks


async def apply_review(db, *, novel_id, frozen, judgment, evidence, workflow_id):
    group = group_scene_inputs([frozen])[0]
    return await apply_group(
        db,
        novel_id=novel_id,
        frozen=group,
        judgments=[judgment],
        evidence=evidence,
        workflow_id=workflow_id,
    )


async def apply_group(
    db, *, novel_id, frozen, judgments, evidence, workflow_id, confirmed=False
):
    from modules.project.facade import require_active_project_exclusive
    from modules.writing.facade import list_latest_drafts_for_chapters

    await require_active_project_exclusive(db, novel_id)
    members = frozen["members"]
    expected = {item["scene_id"]: item for item in members}
    if len(judgments) != len(expected) or {item.scene_id for item in judgments} != set(
        expected
    ):
        raise ValueError("场景提案不属于原冻结分组")
    active = (
        await db.scalars(
            select(Scene)
            .where(
                Scene.novel_id == parse_uuid(novel_id),
                Scene.status.in_(("draft", "candidate", "canonical")),
            )
            .order_by(Scene.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    rows = {str(row.id): row for row in active}
    if any(
        key not in rows or fingerprint(rows[key]) != item["fingerprint"]
        for key, item in expected.items()
    ):
        raise ValueError("场景已变化，原分组不可继续采用")
    drafts = await list_latest_drafts_for_chapters(db, novel_id, frozen["chapters"])
    manifest = {str(draft.id): draft.content_hash for draft in drafts}
    if any(
        manifest.get(item["source_ref"]["draft_id"]) != item["source_ref"]["source_hash"]
        for item in evidence
    ):
        raise ValueError("模型核对后正文已变化")
    base = {
        "group_key": frozen["group_key"],
        "fingerprint": frozen["fingerprint"],
        "scene_id": frozen["scene_id"],
        "scene_ids": list(expected),
    }
    if any(
        item.verdict in {"split_or_merge", "uncertain"} or not item.anchors
        for item in judgments
    ):
        if confirmed:
            raise ValueError("需在场景工作台处理拆分、融合或尚未确定的边界")
        return {
            **base,
            "outcome": "decision",
            "can_apply": False,
            "explanation": "；".join(item.explanation for item in judgments),
        }
    replacements = {
        item.scene_id: materialize_anchors(item, evidence) for item in judgments
    }

    def ranges(chunks):
        return [
            (
                int(item.get("chapter_index", item.get("chapter_id", 0))),
                int(item.get("start_pos") or 0),
                int(item.get("end_pos") or 0),
            )
            for item in chunks
        ]

    needs_confirmation = any(
        item["protected"]
        or (
            not item.get("missing_mapping")
            and ranges(rows[item["scene_id"]].scene_chunks or [])
            != ranges(replacements[item["scene_id"]])
        )
        for item in members
    ) or any(item.confidence < 0.90 for item in judgments)
    for draft in drafts:
        spans = []
        for row in active:
            chunks = replacements.get(str(row.id), row.scene_chunks or [])
            matching = [
                chunk
                for chunk in chunks
                if str(chunk.get("chapter_index", chunk.get("chapter_id", "")))
                == str(draft.chapter_index)
            ]
            if (
                str(draft.chapter_index)
                in [str(value) for value in row.chapter_ids or []]
                and not matching
            ):
                raise ValueError("本章还有未定位场景，需放入同一组核对")
            spans.extend((chunk, str(row.id) in replacements) for chunk in matching)
        spans.sort(key=lambda entry: int(entry[0].get("start_pos") or 0))
        cursor = 0
        for chunk, writable in spans:
            start, end = int(chunk.get("start_pos") or 0), int(chunk.get("end_pos") or 0)
            if (
                start < cursor
                or end <= start
                or end > len(draft.content)
                or draft.content[cursor:start].strip()
            ):
                raise ValueError("修复会造成正文空洞、重叠或越界")
            if writable:
                chunk["start_pos"] = cursor
            cursor = end
        if draft.content[cursor:].strip() or not spans:
            raise ValueError("章节仍有未归属正文")
        if spans[-1][1]:
            spans[-1][0]["end_pos"] = len(draft.content)
    if needs_confirmation and not confirmed:
        return {
            **base,
            "outcome": "decision",
            "can_apply": True,
            "proposed_chunks": replacements,
            "preview": boundary_preview(members, replacements, evidence),
            "explanation": "本组包含受保护场景或引用范围调整，请核对后成组确认。",
        }
    receipts = []
    judgments_by_id = {item.scene_id: item for item in judgments}
    for item in members:
        row = rows[item["scene_id"]]
        judgment = judgments_by_id[item["scene_id"]]
        before = {
            "structure_meta": deepcopy(row.structure_meta or {}),
            "scene_chunks": deepcopy(row.scene_chunks or []),
        }
        issues = review_issues(item, judgment, evidence)
        statuses = dict(before["structure_meta"].get("semantic_field_statuses", {}))
        uncertain = {issue["field"] for issue in issues}
        statuses.update(
            {
                key: "uncertain" if key in uncertain else "present"
                for key, value in item["fields"].items()
                if value
            }
        )
        meta = {
            **before["structure_meta"],
            "review_issues_version": 1,
            "review_issues": issues,
            "needs_review": any(issue["required"] for issue in issues),
            "resolution_workflow_id": workflow_id,
            "boundary_review": {
                "version": 2,
                "source_manifest": manifest,
                "explanation": judgment.explanation,
                "author_confirmed": confirmed,
            },
            "phase1a_fallback": False,
            "semantic_uncertain_fields": [issue["field"] for issue in issues],
            "semantic_field_statuses": statuses,
        }
        await SceneRepository().update(
            db,
            row.id,
            SceneUpdate(structure_meta=meta, scene_chunks=replacements[item["scene_id"]]),
        )
        receipts.append(
            {
                "scene_id": str(row.id),
                "before": before,
                "after": {
                    "structure_meta": deepcopy(row.structure_meta),
                    "scene_chunks": deepcopy(row.scene_chunks),
                },
            }
        )
    return {
        **base,
        "outcome": "decision"
        if any(receipt["after"]["structure_meta"]["needs_review"] for receipt in receipts)
        else "organized",
        "can_apply": False,
        "members": receipts,
        "explanation": "场景来源已成组核对，仍缺证的语义字段保留待决定。",
    }


async def rollback(db, *, novel_id, receipt):
    members = receipt.get("members") or ([receipt] if receipt.get("after") else [])
    if not members:
        return "unchanged"
    rows = []
    for item in members:
        row = await db.scalar(
            select(Scene)
            .where(
                Scene.id == parse_uuid(item["scene_id"]),
                Scene.novel_id == parse_uuid(novel_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or any(
            getattr(row, key) != value for key, value in item["after"].items()
        ):
            return "conflict"
        rows.append((row, item))
    for row, item in reversed(rows):
        await SceneRepository().update(db, row.id, SceneUpdate(**item["before"]))
    return "rolled_back"


def review_issues(frozen, judgment, evidence):
    from modules.story.outline_state.review_attention import OPTIONAL_FIELDS

    uncertain = set(judgment.uncertain_fields) | set(
        frozen.get("meta", {}).get("semantic_uncertain_fields", [])
    )
    for key, value in frozen["fields"].items():
        if not value:
            continue
        quotes = judgment.field_evidence.get(key, [])
        if not quotes or any(
            sum(source["text"].count(quote) for source in evidence) != 1
            for quote in quotes
        ):
            uncertain.add(key)
        elif key not in judgment.uncertain_fields:
            uncertain.discard(key)
    return [
        {"kind": "semantic_field", "field": key, "required": key not in OPTIONAL_FIELDS}
        for key in sorted(uncertain)
    ]


def boundary_preview(members, replacements, evidence):
    texts = {item["source_ref"]["chapter_index"]: item["text"] for item in evidence}

    def excerpt(chunks, end=False):
        if not chunks:
            return "未精确定位"
        chunk = chunks[-1] if end else chunks[0]
        chapter = int(chunk.get("chapter_index", chunk.get("chapter_id", 0)))
        offset = chunk.get("end_pos" if end else "start_pos")
        if offset is None or chapter not in texts:
            return "未精确定位"
        offset = int(offset)
        return (
            texts[chapter][max(0, offset - 80) : offset]
            if end
            else texts[chapter][offset : offset + 80]
        )

    return [
        {
            "scene_id": item["scene_id"],
            "title": item.get("title") or "场景",
            "chapters": item["chapters"],
            "before_start": excerpt(item["chunks"]),
            "before_end": excerpt(item["chunks"], True),
            "after_start": excerpt(replacements[item["scene_id"]]),
            "after_end": excerpt(replacements[item["scene_id"]], True),
        }
        for item in members
    ]
