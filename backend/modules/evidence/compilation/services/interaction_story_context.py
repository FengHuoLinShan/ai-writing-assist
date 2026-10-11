"""Version-pinned source context for one RP generation attempt."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.contracts import (
    INTERACTION_SOURCE_CONTEXT_MAX_TOKENS,
    InteractionStoryContextContract,
    VisibilityContextContract,
)
from modules.evidence.compilation.novel_evidence import NovelEvidenceService
from modules.evidence.compilation.services.interaction_source_cache import (
    CacheFetch,
    InteractionSourceCacheStore,
    build_material_key,
    current_method_versions,
)
from modules.evidence.compilation.services.interaction_source_material import (
    InteractionSourceMaterial,
    compile_source_material,
    identity_block,
    knowledge_block,
    reference_block,
    stable_hash,
)
from modules.evidence.compilation.services.snapshot_service import (
    ContextSnapshotService,
)
from modules.evidence.indexing.facade import retrieve
from modules.evidence.indexing.lexical_plan import (
    LEXICAL_PLANNER_VERSION,
    build_lexical_query_plan,
)
from modules.evidence.source_ref_contracts import SourceRangeRefContract


class InteractionStoryContextService:
    def __init__(self) -> None:
        self._evidence = NovelEvidenceService()
        self._snapshots = ContextSnapshotService()
        self._source_cache = InteractionSourceCacheStore()

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
        budget_tokens: int = INTERACTION_SOURCE_CONTEXT_MAX_TOKENS,
        public_demo_source: bool = False,
        public_demo_source_fingerprint: str | None = None,
        prompt_name: str = "interaction-story",
    ) -> InteractionStoryContextContract:
        from modules.project.facade import (
            get_any_project_context,
            require_active_project,
            require_interaction_project,
        )

        if public_demo_source:
            from core.container import get
            from core.service_keys import (
                INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT,
            )

            await get(INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT)(
                db,
                source_novel_id=source_novel_id,
                source_revision_id=source_revision_id,
                source_fingerprint=str(public_demo_source_fingerprint or ""),
                source_manifest=source_manifest,
            )
        else:
            await require_active_project(db, source_novel_id)
        await require_interaction_project(db, consumer_novel_id)
        budget_tokens = min(
            INTERACTION_SOURCE_CONTEXT_MAX_TOKENS,
            max(0, int(budget_tokens)),
        )
        source_project = await get_any_project_context(db, source_novel_id)
        consumer_project = await get_any_project_context(db, consumer_novel_id)
        if (
            source_project is None
            or consumer_project is None
            or source_project.project_kind != "author"
            or consumer_project.project_kind != "interaction"
            or (
                not public_demo_source
                and source_project.owner_id != consumer_project.owner_id
            )
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
                prompt_name=prompt_name,
                rendered="",
                included_refs=[],
                warnings=[],
                blockers=["固定或玩家资料超出当前剧情进度，请重新选择"],
                budget_tokens=budget_tokens,
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
        # S1 词法规划（M3 切片 2）：语义输入仍是完整拼接查询（喂 embedding），
        # 词法词项按整条请求有界生成；冻结且可见的激活对象名称/别名优先。
        frozen_terms = [
            str(term)
            for key in ordered_keys
            for term in [
                references[key].get("label"),
                *(references[key].get("aliases") or []),
            ]
            if str(term or "").strip()
        ]
        lexical_plan = build_lexical_query_plan(
            retrieval_query or "当前剧情",
            frozen_terms=frozen_terms,
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
        # 精确材料缓存（M3 切片 3，ADR-0018 修订例外）：key 覆盖全部材料输入；
        # 命中仍重过上方门禁并重验必需证明原文，snapshot/审查资格不缓存。
        cache_versions = current_method_versions(LEXICAL_PLANNER_VERSION)
        material_key, material_key_hash = build_material_key(
            source_novel_id=source_novel_id,
            consumer_novel_id=consumer_novel_id,
            owner_id=str(source_project.owner_id),
            source_revision_id=source_revision_id,
            anchor=anchor,
            exact_manifest=exact_manifest,
            visible_references_digest=stable_hash(visible_references),
            reference_policy=reference_policy,
            ambiguities_digest=stable_hash(ambiguities),
            resolutions=resolutions,
            player_identity_digest=stable_hash(player_identity),
            semantic_input=lexical_plan.semantic_input,
            lexical_terms=list(lexical_plan.lexical_terms),
            method_versions=cache_versions,
        )
        cache_fetch = (
            await self._source_cache.fetch(
                db,
                novel_id=uuid.UUID(str(consumer_novel_id)),
                material_key_hash=material_key_hash,
                method_versions=cache_versions,
            )
            if not public_demo_source
            else CacheFetch(hit=None, miss_reason="public_demo_disabled")
        )
        cache_hit = cache_fetch.hit
        if cache_hit is not None and not await self._verify_cached_proofs(
            db,
            source_novel_id=source_novel_id,
            material=cache_hit.material,
            visibility=visibility,
        ):
            await self._source_cache.purge_for_source(db, uuid.UUID(source_novel_id))
            cache_hit = None
        if cache_hit is not None:
            material = cache_hit.material
            if (
                cache_hit.compiled is not None
                and cache_hit.compiled_budget_tokens == budget_tokens
            ):
                packet = cache_hit.compiled
            else:
                packet = compile_source_material(material, budget_tokens=budget_tokens)
                # 阻断结果不落编译缓存：compiled 复用恒为无阻断产物，
                # 避免把“预算不足”复用成成功包。
                if not packet.blockers:
                    await self._source_cache.touch_compiled(
                        db,
                        novel_id=uuid.UUID(str(consumer_novel_id)),
                        material_key_hash=material_key_hash,
                        compiled=packet,
                        budget_tokens=budget_tokens,
                    )
            return await self._snapshot_result(
                db,
                source_novel_id=source_novel_id,
                consumer_novel_id=consumer_novel_id,
                source_revision_id=source_revision_id,
                anchor=anchor,
                task_id=task_id,
                model=model,
                prompt_name=prompt_name,
                rendered=packet.rendered,
                included_refs=list(packet.included_refs),
                source_refs=list(packet.source_refs),
                warnings=list(material.warnings),
                blockers=list(packet.blockers),
                budget_tokens=budget_tokens,
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
            lexical_terms=list(lexical_plan.lexical_terms) or None,
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
        proof_by_target: dict[str, dict] = {}
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
                proof_by_target.setdefault(str(target_id), read)
                item = object_by_target.get(str(target_id))
                activate(item.get("reference_key") if item else None, "原文片段关联")

        # Manual identity evidence is frozen with the source revision. Re-read
        # that exact range; never use today's mutable object summary as proof.
        for key in ordered_keys:
            item = references[key]
            target = str(item.get("target_id") or "")
            if target in validated_targets or item.get("entity_type") == "relation":
                continue
            for raw in item.get("identity_source_refs") or []:
                if exact_manifest.get(raw.get("draft_id")) != raw.get("source_hash"):
                    continue
                # Character mode may only reuse ranges already admitted by the
                # character-filtered retrieval; a Scene alone proves no knowledge.
                if viewpoint_id and not any(
                    read["source_ref"]["draft_id"] == raw.get("draft_id")
                    and read["source_ref"]["start_offset"] <= raw.get("start_offset", -1)
                    and read["source_ref"]["end_offset"] >= raw.get("end_offset", 0)
                    for read in excerpts
                ):
                    continue
                try:
                    read = await self._evidence.read(
                        db,
                        novel_id=source_novel_id,
                        source_ref=SourceRangeRefContract(**raw),
                        visibility=visibility,
                        before=0,
                        after=0,
                    )
                except (NotFoundError, ValidationError, ValueError, TypeError):
                    continue
                if any(
                    str(ref.get("target_id")) in ignored_targets
                    for ref in read.get("object_refs") or []
                ):
                    continue
                excerpts.append(read)
                validated_targets.add(target)
                proof_by_target[target] = read
                break

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
                prompt_name=prompt_name,
                rendered="",
                included_refs=[],
                warnings=list(dict.fromkeys([*retrieval.warnings, *hydrated.warnings])),
                blockers=["固定或玩家资料缺少截止点前的可验证原文，请减少或重选"],
                budget_tokens=budget_tokens,
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
        player_reference_key = player_identity.get("reference_key")
        knowledge = (
            knowledge_block(references[str(player_reference_key)], cutoff_chapter)
            if player_reference_key in references
            else ""
        )
        mandatory_reads: list[dict] = []
        for key in ordered_keys:
            if key not in mandatory:
                continue
            proof = proof_by_target[str(references[key]["target_id"])]
            if proof not in mandatory_reads:
                mandatory_reads.append(proof)
        material = InteractionSourceMaterial(
            identity_block=identity_block(anchor, player_identity),
            reference_order=tuple(ordered_keys),
            mandatory_keys=frozenset(mandatory),
            reference_blocks={
                key: reference_block(references[key], reasons[key])
                for key in ordered_keys
            },
            reference_reasons={key: reasons[key] for key in ordered_keys},
            reference_labels={
                key: str(references[key].get("label") or "作品资料")
                for key in ordered_keys
            },
            knowledge_block=knowledge,
            mandatory_reads=tuple(mandatory_reads),
            excerpt_reads=tuple(excerpts),
            warnings=tuple(dict.fromkeys([*retrieval.warnings, *hydrated.warnings])),
        )
        packet = compile_source_material(material, budget_tokens=budget_tokens)
        if not packet.blockers and not public_demo_source:
            await self._source_cache.store(
                db,
                novel_id=uuid.UUID(str(consumer_novel_id)),
                source_novel_id=uuid.UUID(str(source_novel_id)),
                owner_id=uuid.UUID(str(source_project.owner_id)),
                material_key=material_key,
                material_key_hash=material_key_hash,
                material=material,
                method_versions=cache_versions,
                compiled=packet,
                budget_tokens=budget_tokens,
            )
        return await self._snapshot_result(
            db,
            source_novel_id=source_novel_id,
            consumer_novel_id=consumer_novel_id,
            source_revision_id=source_revision_id,
            anchor=anchor,
            task_id=task_id,
            model=model,
            prompt_name=prompt_name,
            rendered=packet.rendered,
            included_refs=list(packet.included_refs),
            source_refs=list(packet.source_refs),
            warnings=list(material.warnings),
            blockers=list(packet.blockers),
            budget_tokens=budget_tokens,
        )

    async def _verify_cached_proofs(
        self,
        db: AsyncSession,
        *,
        source_novel_id: str,
        material: InteractionSourceMaterial,
        visibility: VisibilityContextContract,
    ) -> bool:
        """命中后重验全部材料范围：按冻结 source_ref 重读原文并比对一致。

        读取失败或正文漂移一律视为未命中（走原路径），不把缓存内容当事实。
        """

        for read in (*material.mandatory_reads, *material.excerpt_reads):
            ref = dict(read.get("source_ref") or {})
            # 按冻结 ref 的完整契约字段重建（version/mode/hash 均为必需），
            # 多余键忽略；缺必需键会在下方构造时抛错并按未命中处理。
            fields = {
                key: value for key, value in ref.items() if key in _SOURCE_REF_FIELDS
            }
            if not fields.get("draft_id"):
                return False
            try:
                fresh = await self._evidence.read(
                    db,
                    novel_id=source_novel_id,
                    source_ref=SourceRangeRefContract(**fields),
                    visibility=visibility,
                    before=0,
                    after=0,
                )
            except (NotFoundError, ValidationError, ValueError, TypeError):
                return False
            if str(fresh.get("text") or "") != str(read.get("text") or ""):
                return False
        return True

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
        budget_tokens: int = INTERACTION_SOURCE_CONTEXT_MAX_TOKENS,
        prompt_name: str = "interaction-story",
    ) -> InteractionStoryContextContract:
        source_refs = source_refs or []
        fingerprint = stable_hash(
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
            novel_id=consumer_novel_id,
            consumer_novel_id=consumer_novel_id,
            task_id=task_id,
            phase="interaction_story",
            operation="compile_source_context",
            chapter_index=int(anchor.get("chapter_index") or 0),
            context_mode="canonical",
            include_pending_objects=False,
            prompt_name=prompt_name,
            model=model,
            compile_options={
                "consumer_action": "interaction.story",
                "source_revision_id": source_revision_id,
                "anchor_key": anchor.get("anchor_key"),
                "budget_tokens": budget_tokens,
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
            token_metadata={
                "estimated_tokens": tokens,
                "budget_tokens": budget_tokens,
            },
            rendered_context=rendered,
            retain_rendered_context=False,
        )
        if blockers:
            await self._snapshots.mark_context_snapshot_failed(
                db,
                novel_id=consumer_novel_id,
                snapshot_id=snapshot.id,
                error_kind="source_context_blocked",
                error_message=blockers[0],
            )
        else:
            await self._snapshots.mark_context_snapshot_succeeded(
                db,
                novel_id=consumer_novel_id,
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


def _normalize(value: str) -> str:
    return "".join(str(value or "").lower().split())


_SOURCE_REF_FIELDS = frozenset(SourceRangeRefContract.__dataclass_fields__)


def _reason_counts(items: Iterable[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        reason = item.get("reason") or "其他"
        counts[reason] = counts.get(reason, 0) + 1
    return counts
