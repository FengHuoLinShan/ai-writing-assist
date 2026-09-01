"""Version-pinned source context for one RP generation attempt."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.contracts import (
    InteractionStoryContextContract,
    VisibilityContextContract,
)
from modules.evidence.compilation.novel_evidence import NovelEvidenceService
from modules.evidence.compilation.services.snapshot_service import (
    ContextSnapshotService,
)
from modules.evidence.indexing.facade import retrieve

REFERENCE_BUDGET_TOKENS = 16_000


class InteractionStoryContextService:
    def __init__(self) -> None:
        self._evidence = NovelEvidenceService()
        self._snapshots = ContextSnapshotService()

    async def compile(
        self,
        db: AsyncSession,
        *,
        source_novel_id: str,
        consumer_novel_id: str,
        source_revision_id: str,
        source_manifest: list[dict],
        anchor: dict,
        player_identity: dict,
        reference_manifest: list[dict],
        ambiguities: list[dict],
        resolutions: dict[str, str],
        reference_policy: dict,
        query: str,
        task_id: str | None,
        model: str,
    ) -> InteractionStoryContextContract:
        from modules.project.facade import (
            get_any_project_context,
            require_active_project,
            require_interaction_project,
        )

        await require_active_project(db, source_novel_id)
        await require_interaction_project(db, consumer_novel_id)
        source_project = await get_any_project_context(db, source_novel_id)
        consumer_project = await get_any_project_context(db, consumer_novel_id)
        if (
            source_project is None
            or consumer_project is None
            or source_project.project_kind != "author"
            or consumer_project.project_kind != "interaction"
            or source_project.owner_id != consumer_project.owner_id
        ):
            raise NotFoundError("作品资料不存在")
        cutoff_chapter = int(anchor.get("chapter_index") or 0)
        cutoff_offset = int(anchor.get("end_offset") or 0)
        if cutoff_chapter < 1 or cutoff_offset < 1:
            return InteractionStoryContextContract(
                rendered_context="",
                fingerprint="",
                blockers=["剧情进度已失效，请重新选择"],
            )
        exact_manifest = {
            str(item.get("draft_id")): str(item.get("source_hash"))
            for item in source_manifest
            if int(item.get("chapter_index") or 0) <= cutoff_chapter
            and item.get("draft_id")
            and len(str(item.get("source_hash") or "")) == 64
        }
        if not exact_manifest:
            return InteractionStoryContextContract(
                rendered_context="",
                fingerprint="",
                blockers=["作品正文版本已失效，请恢复来源作品"],
            )

        cutoff_source = next(
            (
                item
                for item in source_manifest
                if int(item.get("chapter_index") or 0) == cutoff_chapter
            ),
            {},
        )
        chapter_end = int(cutoff_source.get("char_count") or 0)
        at_chapter_end = chapter_end > 0 and cutoff_offset >= chapter_end
        visible_references = []
        for item in reference_manifest:
            first_chapter = int(
                (
                    item.get("source_chapter_index")
                    if item.get("entity_type") == "relation"
                    else item.get("first_chapter_index")
                )
                or 0
            )
            visible = 0 < first_chapter < cutoff_chapter
            if first_chapter == cutoff_chapter:
                visible = (
                    at_chapter_end
                    if item.get("entity_type") == "relation"
                    else 0 < int(item.get("first_end_offset") or 0) <= cutoff_offset
                )
            if visible:
                visible_references.append(item)
        references = {
            item["reference_key"]: item
            for item in visible_references
            if item.get("reference_key")
        }
        object_by_target = {
            str(item.get("target_id")): item
            for item in visible_references
            if item.get("entity_type") != "relation" and item.get("target_id")
        }
        ignored = set(reference_policy.get("excluded") or [])
        pinned = list(dict.fromkeys(reference_policy.get("pinned") or []))
        ignored_targets = {
            str(references[key].get("target_id"))
            for key in ignored
            if key in references and references[key].get("target_id")
        }
        required_keys = [*pinned]
        if player_identity.get("reference_key"):
            required_keys.append(str(player_identity["reference_key"]))
        if any(key not in references for key in required_keys):
            return await self._snapshot_result(
                db,
                source_novel_id=source_novel_id,
                consumer_novel_id=consumer_novel_id,
                source_revision_id=source_revision_id,
                anchor=anchor,
                task_id=task_id,
                model=model,
                rendered="",
                included_refs=[],
                warnings=[],
                blockers=["固定或玩家资料超出当前剧情进度，请重新选择"],
            )
        reasons: dict[str, str] = {}
        ordered_keys: list[str] = []

        def activate(key: str | None, reason: str) -> None:
            if not key or key in ignored or key not in references or key in reasons:
                return
            reasons[key] = reason
            ordered_keys.append(key)

        if player_identity.get("kind") == "source_character":
            activate(player_identity.get("reference_key"), "玩家身份")
        for key in pinned:
            activate(key, "已固定")

        normalized_query = _normalize(query)
        resolved_terms = {
            _normalize(str(item.get("term") or item.get("label") or "")): resolutions.get(
                str(item.get("ambiguity_key") or "")
            )
            for item in ambiguities
        }
        for item in visible_references:
            if item.get("entity_type") == "relation":
                continue
            terms = [item.get("label"), *(item.get("aliases") or [])]
            matched = next(
                (
                    _normalize(str(term))
                    for term in terms
                    if term and _normalize(str(term)) in normalized_query
                ),
                None,
            )
            if not matched:
                continue
            resolved = resolved_terms.get(matched)
            if resolved and resolved != item.get("reference_key"):
                continue
            activate(item.get("reference_key"), "本轮提到")

        viewpoint_id = (
            str(player_identity.get("target_id"))
            if player_identity.get("kind") == "source_character"
            else None
        )
        retrieval_focus = [
            str(references[key].get("label") or "")
            for key in [player_identity.get("reference_key"), *pinned]
            if key in references
        ]
        retrieval_query = " ".join(
            value for value in [query.strip(), *retrieval_focus] if value
        )
        retrieval = await retrieve(
            db,
            source_novel_id,
            retrieval_query or "当前剧情",
            visible_until_chapter=cutoff_chapter,
            content_mode="canonical",
            mode="context",
            top_k=12,
            reference_chapter_index=cutoff_chapter,
            retrieval_purpose="interaction_story",
            rerank=False,
            source_manifest=exact_manifest,
            character_ids=[viewpoint_id] if viewpoint_id else None,
        )
        visibility = VisibilityContextContract(
            mode="character" if viewpoint_id else "reader",
            cutoff_chapter=cutoff_chapter,
            # The frozen exact offset remains valid even after a newer deep
            # import replaces the source project's current Scene read model.
            cutoff_scene_id=None,
            cutoff_offset=cutoff_offset,
            character_id=viewpoint_id,
        )
        hydrated = await self._evidence.rehydrate_manuscript_candidates(
            db,
            novel_id=source_novel_id,
            content_mode="canonical",
            visibility=visibility,
            chunks=retrieval.chunks,
            source_manifest=exact_manifest,
        )
        excerpts: list[dict] = []
        validated_targets: set[str] = set()
        for chunk in retrieval.chunks:
            chunk_targets = {
                str(value) for value in [*chunk.character_ids, *chunk.entity_ids]
            }
            if chunk_targets & ignored_targets:
                continue
            read = hydrated.reads_by_chunk_id.get(str(chunk.id))
            if read is None:
                continue
            excerpts.append(read)
            for target_id in [*chunk.character_ids, *chunk.entity_ids]:
                validated_targets.add(str(target_id))
                item = object_by_target.get(str(target_id))
                activate(item.get("reference_key") if item else None, "原文片段关联")

        unverified_required = [
            key
            for key in required_keys
            if references[key].get("entity_type") == "relation"
            or str(references[key].get("target_id") or "") not in validated_targets
        ]
        if unverified_required:
            return await self._snapshot_result(
                db,
                source_novel_id=source_novel_id,
                consumer_novel_id=consumer_novel_id,
                source_revision_id=source_revision_id,
                anchor=anchor,
                task_id=task_id,
                model=model,
                rendered="",
                included_refs=[],
                warnings=list(dict.fromkeys([*retrieval.warnings, *hydrated.warnings])),
                blockers=["固定或玩家资料缺少截止点前的可验证原文，请减少或重选"],
            )

        active_targets = {
            str(references[key].get("target_id"))
            for key in ordered_keys
            if references[key].get("entity_type") != "relation"
        }
        for relation in visible_references:
            if relation.get("entity_type") != "relation":
                continue
            if int(relation.get("source_chapter_index") or 0) > cutoff_chapter:
                continue
            endpoints = {
                str(relation.get("source_target_id") or ""),
                str(relation.get("target_target_id") or ""),
            }
            if endpoints & ignored_targets:
                continue
            if not endpoints & active_targets:
                continue
            activate(relation.get("reference_key"), "相关关系")
            for target_id in endpoints - active_targets:
                item = object_by_target.get(target_id)
                activate(item.get("reference_key") if item else None, "相关关系")
            if len(ordered_keys) >= 32:
                break

        mandatory = set(pinned)
        if player_identity.get("reference_key"):
            mandatory.add(str(player_identity["reference_key"]))
        blocks = [
            self._identity_block(anchor, player_identity),
            *(
                self._reference_block(references[key], reasons[key])
                for key in ordered_keys
                if key in mandatory
            ),
        ]
        included_keys = [key for key in ordered_keys if key in mandatory]
        if player_identity.get("reference_key") in references:
            knowledge = self._knowledge_block(
                references[str(player_identity["reference_key"])],
                cutoff_chapter,
            )
            if knowledge:
                blocks.append(knowledge)
        if estimate_token_count("\n\n".join(blocks)) > REFERENCE_BUDGET_TOKENS:
            blockers = ["已固定的作品资料超出可用篇幅，请减少固定项"]
            return await self._snapshot_result(
                db,
                source_novel_id=source_novel_id,
                consumer_novel_id=consumer_novel_id,
                source_revision_id=source_revision_id,
                anchor=anchor,
                task_id=task_id,
                model=model,
                rendered="",
                included_refs=[],
                warnings=list(dict.fromkeys([*retrieval.warnings, *hydrated.warnings])),
                blockers=blockers,
            )

        for key in ordered_keys:
            if key in mandatory:
                continue
            candidate = self._reference_block(references[key], reasons[key])
            if (
                estimate_token_count("\n\n".join([*blocks, candidate]))
                > REFERENCE_BUDGET_TOKENS
            ):
                continue
            blocks.append(candidate)
            included_keys.append(key)
        for read in excerpts:
            candidate = self._excerpt_block(read)
            if (
                estimate_token_count("\n\n".join([*blocks, candidate]))
                > REFERENCE_BUDGET_TOKENS
            ):
                break
            blocks.append(candidate)

        rendered = (
            "<SOURCE_REFERENCE_DATA>\n"
            + "\n\n".join(blocks)
            + "\n</SOURCE_REFERENCE_DATA>"
        )
        included_refs = [
            {
                "reference_key": key,
                "label": str(references[key].get("label") or "作品资料"),
                "reason": reasons[key],
            }
            for key in included_keys
        ]
        included_reads = [
            read for read in excerpts if str(read.get("text") or "") in rendered
        ]
        included_refs.extend(
            {
                "reference_key": _hash(read.get("source_ref") or {}),
                "label": str(read.get("title") or "原文片段"),
                "reason": "原文片段关联",
            }
            for read in included_reads
        )
        return await self._snapshot_result(
            db,
            source_novel_id=source_novel_id,
            consumer_novel_id=consumer_novel_id,
            source_revision_id=source_revision_id,
            anchor=anchor,
            task_id=task_id,
            model=model,
            rendered=rendered,
            included_refs=included_refs,
            source_refs=[dict(read["source_ref"]) for read in included_reads],
            warnings=list(dict.fromkeys([*retrieval.warnings, *hydrated.warnings])),
            blockers=[],
        )

    async def _snapshot_result(
        self,
        db: AsyncSession,
        *,
        source_novel_id: str,
        consumer_novel_id: str,
        source_revision_id: str,
        anchor: dict,
        task_id: str | None,
        model: str,
        rendered: str,
        included_refs: list[dict[str, str]],
        warnings: list[str],
        blockers: list[str],
        source_refs: list[dict] | None = None,
    ) -> InteractionStoryContextContract:
        source_refs = source_refs or []
        fingerprint = _hash(
            {
                "source_revision_id": source_revision_id,
                "anchor_key": anchor.get("anchor_key"),
                "rendered": rendered,
                "included_refs": included_refs,
                "source_refs": source_refs,
            }
        )
        tokens = estimate_token_count(rendered)
        snapshot = await self._snapshots.create_context_snapshot(
            db,
            novel_id=source_novel_id,
            consumer_novel_id=consumer_novel_id,
            task_id=task_id,
            phase="interaction_story",
            operation="compile_source_context",
            chapter_index=int(anchor.get("chapter_index") or 0),
            context_mode="canonical",
            include_pending_objects=False,
            prompt_name="interaction-story-v3",
            model=model,
            compile_options={
                "consumer_action": "interaction.story",
                "source_revision_id": source_revision_id,
                "anchor_key": anchor.get("anchor_key"),
                "budget_tokens": REFERENCE_BUDGET_TOKENS,
            },
            included_asset_ids={
                "references": [item["reference_key"] for item in included_refs]
            },
            excluded_asset_ids={},
            context_summary={
                "fingerprint": fingerprint,
                "included_count": len(included_refs),
                "source_ref_count": len(source_refs),
                "warning_count": len(warnings),
                "blocker_count": len(blockers),
            },
            section_metadata={"activation_reasons": _reason_counts(included_refs)},
            token_metadata={"estimated_tokens": tokens, "budget_tokens": 16_000},
            rendered_context=rendered,
            retain_rendered_context=False,
        )
        if blockers:
            await self._snapshots.mark_context_snapshot_failed(
                db,
                novel_id=source_novel_id,
                snapshot_id=snapshot.id,
                error_kind="source_context_blocked",
                error_message=blockers[0],
            )
        else:
            await self._snapshots.mark_context_snapshot_succeeded(
                db,
                novel_id=source_novel_id,
                snapshot_id=snapshot.id,
                result_refs=[
                    *included_refs,
                    *({"source_ref": item} for item in source_refs),
                ],
            )
        return InteractionStoryContextContract(
            rendered_context=rendered,
            fingerprint=fingerprint,
            included_refs=included_refs,
            source_refs=source_refs,
            warnings=warnings,
            blockers=blockers,
            snapshot_id=snapshot.id,
            token_count=tokens,
        )

    @staticmethod
    def _identity_block(anchor: dict, player_identity: dict) -> str:
        player = (
            player_identity.get("label") or player_identity.get("name") or "未命名玩家"
        )
        description = str(player_identity.get("description") or "").strip()
        return "\n".join(
            filter(
                None,
                [
                    "## 不可越过的剧情边界",
                    f"- 剧情进度：{anchor.get('chapter_title')} · {anchor.get('label')}",
                    f"- 玩家身份：{player}",
                    f"- 原创身份说明：{description}" if description else "",
                    "- 只能使用该进度之前的事实和角色知识。",
                ],
            )
        )

    @staticmethod
    def _reference_block(item: dict, reason: str) -> str:
        return "\n".join(
            [
                f"## {item.get('label')} （{item.get('entity_type')}）",
                f"- 激活原因：{reason}",
            ]
        )

    @staticmethod
    def _excerpt_block(read: dict) -> str:
        source = read.get("source_ref") or {}
        return "\n".join(
            [
                f"## 原文证据：{read.get('title') or '未命名章节'}",
                f"- 位置：第 {source.get('chapter_index')} 章",
                str(read.get("text") or ""),
            ]
        )

    @staticmethod
    def _knowledge_block(item: dict, cutoff_chapter: int) -> str:
        lines = ["## 玩家角色在当前进度实际知道的事"]
        for entry in item.get("knowledge") or []:
            learned = entry.get("source_chapter_index")
            if not entry.get("is_public_baseline") and (
                not isinstance(learned, int) or learned >= cutoff_chapter
            ):
                continue
            target = entry.get("target_name") or entry.get("target_type") or "某对象"
            level = entry.get("knowledge_level")
            if level == "unknown":
                lines.append(f"- 对「{target}」并不知情。")
            elif level in {"false_belief", "misunderstood"}:
                if entry.get("misconception"):
                    lines.append(f"- 对「{target}」的误解：{entry['misconception']}")
            elif entry.get("known_content"):
                qualifier = "传闻或局部认知" if level in {"rumor", "partial"} else "已知"
                lines.append(f"- {qualifier}「{target}」：{entry['known_content']}")
        return "\n".join(lines) if len(lines) > 1 else ""


def _normalize(value: str) -> str:
    return "".join(str(value or "").lower().split())


def _hash(value) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reason_counts(items: Iterable[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        reason = item.get("reason") or "其他"
        counts[reason] = counts.get(reason, 0) + 1
    return counts
