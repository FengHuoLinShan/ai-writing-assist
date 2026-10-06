"""收敛阶段：源窗口组装、map/reduce 工作流与收敛响应。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.stable_hash import stable_hash
from modules.world.llm_schemas import GeneratedWorldGenerationConvergenceOutput
from modules.world.schemas import (
    WorldBibleSourceRef,
    WorldCoreHandoff,
    WorldGenerationConvergenceCoverage,
    WorldGenerationConvergenceDecisionCard,
    WorldGenerationConvergenceDecisionItem,
    WorldGenerationConvergenceDetailSummary,
    WorldGenerationConvergenceManifestItem,
    WorldGenerationConvergenceRequest,
    WorldGenerationConvergenceResponse,
    WorldGenerationRequestBase,
    WorldGenerationSourceSnapshot,
)
from modules.world.services.worldbuilding.generation_center.shared import (
    _CONVERGENCE_CALL_INPUT_CHARS,
    _CONVERGENCE_MAX_SOURCES,
    _CONVERGENCE_SOURCE_BLOCK_CHARS,
    _CONVERGENCE_SYSTEM_PROMPT,
    _EXTERNAL_PACKET_CONTRACT,
    _WORLD_CORE_CONVERGENCE_CONTRACT,
    WORLD_GENERATION_TIMEOUT_SECONDS,
)
from modules.world.services.worldbuilding.knowledge_governance import (
    serialize_governed_output,
)
from shared.target_ref import TargetRef


class _ConvergenceStageMixin:
    async def converge(
        self,
        db: AsyncSession,
        data: WorldGenerationConvergenceRequest,
    ) -> WorldGenerationConvergenceResponse:
        """Converge the explicit source window without materializing a suggestion."""
        if (
            not any(item.role == "user" for item in data.messages)
            and not (data.pasted_context or "").strip()
        ):
            raise ValidationError("Convergence requires author conversation content")
        execution_snapshot, model = await self._freeze_execution_snapshot(
            db,
            data.novel_id,
        )
        prepared = await self._prepare(
            db,
            data,
            operation="world.generation.convergence",
            model=model,
        )
        generated: GeneratedWorldGenerationConvergenceOutput | None = None
        issues: list[str] = []
        covered: set[str] = set()
        provider = ""
        knowledge_review: dict[str, Any] | None = None
        try:
            sources = self._convergence_sources(data, prepared)
            manifest_hash = self._convergence_manifest_hash(sources)
            async with self._open_client(
                db,
                data.novel_id,
                execution_snapshot=execution_snapshot,
                high_quality=data.quality_mode == "pro",
            ) as client:
                provider = str(client.provider)
                async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
                    try:
                        generated, issues, covered = await self._run_convergence_workflow(
                            client,
                            data,
                            sources,
                            model=model,
                        )
                    except LLMInvalidResponseError:
                        issues = ["模型未能返回可校验的收束结构，请缩小材料范围后重试。"]
                if generated is not None:
                    _governed_text, knowledge_review = await self._govern_text(
                        client,
                        capability="world.generation.convergence",
                        novel_id=data.novel_id,
                        prepared=prepared,
                        text=serialize_governed_output(generated),
                        task_instruction="把作者选定的来源收束为决策卡，不新增无来源事实",
                    )
                    if knowledge_review.get("status") != "passed":
                        generated = None
                        issues = [
                            "收束结果未通过知识审查，已整体扣留；请调整来源范围后重试。"
                        ]
                        covered = set()
            await self._revalidate_source(db, data, prepared)
        except Exception as exc:
            await self._finish_context_snapshot(
                db,
                data.novel_id,
                prepared["background"],
                error=exc,
            )
            raise
        await self._finish_context_snapshot(
            db,
            data.novel_id,
            prepared["background"],
            result_refs=[{"type": "world_generation_convergence", "id": manifest_hash}],
        )
        return self._convergence_response(
            data,
            prepared,
            sources,
            manifest_hash=manifest_hash,
            generated=generated,
            issues=issues,
            covered=covered,
            model=model,
            provider=provider,
            knowledge_review=knowledge_review,
        )


    @classmethod
    def _asset_ref_hash(cls, ref: dict[str, Any]) -> str:
        source_type, source_id = cls._normalized_identity(
            str(
                ref.get("type") or ref.get("target_type") or ref.get("source_type") or ""
            ),
            str(ref.get("id") or ref.get("target_id") or ref.get("source_id") or ""),
        )
        return TargetRef(
            target_type=source_type,
            target_id=source_id,
            target_path=str(ref.get("target_path") or ""),
            relation=str(ref.get("relation") or "informs"),
        ).target_hash()

    def _convergence_sources(
        self,
        data: WorldGenerationRequestBase,
        prepared: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []

        def append_source(
            *,
            kind: str,
            label: str,
            content: str,
            source_ref: WorldBibleSourceRef,
            identity: str,
        ) -> None:
            text = content.strip()
            if not text:
                return
            source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            chunks = [
                text[index : index + _CONVERGENCE_SOURCE_BLOCK_CHARS]
                for index in range(0, len(text), _CONVERGENCE_SOURCE_BLOCK_CHARS)
            ]
            for index, chunk in enumerate(chunks, start=1):
                block_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                suffix = f" · 第 {index}/{len(chunks)} 段" if len(chunks) > 1 else ""
                item = WorldGenerationConvergenceManifestItem(
                    key=f"{kind}:{identity}:{index}",
                    kind=kind,
                    label=f"{label}{suffix}",
                    content_hash=block_hash,
                    source_ref=source_ref.model_copy(
                        update={
                            "source_hash": source_ref.source_hash or source_hash,
                            "block_hash": block_hash,
                        }
                    ),
                )
                sources.append({"manifest": item, "content": chunk})

        conversation_hash = self._conversation_hash(data)
        for index, message in enumerate(
            prepared.get("conversation_messages", data.messages), start=1
        ):
            role = "你" if message.role == "user" else "AI"
            content_hash = hashlib.sha256(message.content.encode("utf-8")).hexdigest()
            append_source(
                kind="conversation",
                label=f"对话第 {index} 条 · {role}",
                content=message.content,
                source_ref=WorldBibleSourceRef(
                    source_type=(
                        "author_message"
                        if message.role == "user"
                        else "assistant_message"
                    ),
                    source_hash=content_hash,
                    title=f"对话第 {index} 条 · {role}",
                ),
                identity=f"{conversation_hash[:16]}:{index}",
            )
        if data.pasted_context:
            pasted_hash = hashlib.sha256(data.pasted_context.encode("utf-8")).hexdigest()
            append_source(
                kind="pasted_context",
                label="作者粘贴的参考材料",
                content=data.pasted_context,
                source_ref=WorldBibleSourceRef(
                    source_type="author_pasted_context",
                    source_hash=pasted_hash,
                    title="作者粘贴的参考材料",
                ),
                identity=pasted_hash[:16],
            )
        source_page = self._source_page_for_prompt(prepared)
        snapshot: WorldGenerationSourceSnapshot = prepared["source_snapshot"]
        if source_page is not None:
            page_content = json.dumps(
                source_page,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            append_source(
                kind="source_page",
                label=snapshot.title or "当前世界书来源页",
                content=page_content,
                source_ref=WorldBibleSourceRef(
                    source_type=(
                        "world_bible_page_draft"
                        if snapshot.draft_id
                        else "world_bible_page"
                    ),
                    source_id=snapshot.draft_id or snapshot.page_id,
                    source_version=snapshot.page_version,
                    source_hash=snapshot.content_hash,
                    page_id=snapshot.page_id,
                    title=snapshot.title,
                ),
                identity=(snapshot.content_hash or str(snapshot.page_id))[:16],
            )
        for chapter in prepared["chapters"]:
            excerpt = str(chapter["excerpt"])
            source_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            append_source(
                kind="chapter",
                label=f"第 {chapter['chapter_index']} 章 · {chapter['title']}",
                content=excerpt,
                source_ref=WorldBibleSourceRef(
                    source_type="writing_chapter",
                    chapter_index=chapter["chapter_index"],
                    title=chapter["title"],
                    source_hash=source_hash,
                ),
                identity=f"{chapter['chapter_index']}:{source_hash[:16]}",
            )
        for index, asset in enumerate(prepared["assets"]["by_key"].values(), start=1):
            source_hash = str(asset["source_hash"])
            append_source(
                kind="asset",
                label=str(asset["title"]),
                content=str(asset["content"]),
                source_ref=WorldBibleSourceRef(
                    source_type=str(asset["type"]),
                    source_id=str(asset["ref"]["id"]),
                    title=str(asset["title"]),
                    source_hash=source_hash,
                ),
                identity=f"{source_hash[:16]}:{index}",
            )
        background = str(prepared["background"].get("rendered_context") or "")
        if background:
            usage = prepared["background"].get("context_usage") or {}
            background_hash = hashlib.sha256(background.encode("utf-8")).hexdigest()
            append_source(
                kind="project_background",
                label="项目背景（相关性选取，不代表全部）",
                content=background,
                source_ref=WorldBibleSourceRef(
                    source_type=(
                        "world_bible_synopsis"
                        if usage.get("revision_id")
                        else "project_background"
                    ),
                    source_id=usage.get("revision_id"),
                    source_hash=usage.get("source_hash") or background_hash,
                    block_hash=usage.get("block_hash"),
                    title="项目背景（相关性选取）",
                ),
                identity=background_hash[:16],
            )
        if len(sources) > _CONVERGENCE_MAX_SOURCES:
            raise ValidationError(
                "The selected convergence range has too many source blocks; "
                "reduce the range and try again"
            )
        return sources

    @staticmethod
    def _convergence_manifest_hash(sources: list[dict[str, Any]]) -> str:
        return stable_hash(
            [source["manifest"].model_dump(mode="json") for source in sources],
            stringify_unknown=False,
        )


    async def _run_convergence_workflow(
        self,
        client: LLMClient,
        data: WorldGenerationConvergenceRequest,
        sources: list[dict[str, Any]],
        *,
        model: str,
    ) -> tuple[
        GeneratedWorldGenerationConvergenceOutput | None,
        list[str],
        set[str],
    ]:
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for source in sources:
            size = len(source["content"]) + len(source["manifest"].label) + 300
            if current and current_chars + size > _CONVERGENCE_CALL_INPUT_CHARS:
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(source)
            current_chars += size
        if current:
            chunks.append(current)

        mapped: list[tuple[GeneratedWorldGenerationConvergenceOutput, list[str]]] = []
        for index, chunk in enumerate(chunks, start=1):
            expected = [source["manifest"].key for source in chunk]
            request = self._convergence_map_request(
                data,
                chunk,
                chunk_index=index,
                chunk_count=len(chunks),
                model=model,
            )
            generated, issues, covered = await self._run_convergence_pass(
                client,
                request,
                expected,
                step_name="world.generation.convergence.map",
                quality_mode=data.quality_mode,
                require_external_disposition=data.external_packet is not None,
            )
            if issues or generated is None:
                return generated, issues, covered
            mapped.append((generated, expected))

        while len(mapped) > 1:
            reduced: list[
                tuple[GeneratedWorldGenerationConvergenceOutput, list[str]]
            ] = []
            for index in range(0, len(mapped), 2):
                pair = mapped[index : index + 2]
                if len(pair) == 1:
                    reduced.append(pair[0])
                    continue
                expected = [key for _output, keys in pair for key in keys]
                request = self._convergence_reduce_request(
                    pair,
                    model=model,
                    external_packet=data.external_packet is not None,
                    world_core=data.workflow_preset == "world_core",
                )
                generated, issues, covered = await self._run_convergence_pass(
                    client,
                    request,
                    expected,
                    step_name="world.generation.convergence.reduce",
                    quality_mode=data.quality_mode,
                    require_external_disposition=data.external_packet is not None,
                )
                if issues or generated is None:
                    return generated, issues, covered
                reduced.append((generated, expected))
            mapped = reduced
        if not mapped:
            return None, ["本次范围没有可供收束的来源。"], set()
        output, expected = mapped[0]
        return output, [], set(expected)

    def _convergence_map_request(
        self,
        data: WorldGenerationConvergenceRequest,
        sources: list[dict[str, Any]],
        *,
        chunk_index: int,
        chunk_count: int,
        model: str,
    ) -> LLMCallRequest:
        manifest = [
            {
                **source["manifest"].model_dump(mode="json", exclude={"source_ref"}),
                "content": source["content"],
            }
            for source in sources
        ]
        return LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        f"{_CONVERGENCE_SYSTEM_PROMPT}\n\n{self._target_brief(data)}"
                        + (
                            f"\n\n{_WORLD_CORE_CONVERGENCE_CONTRACT}"
                            if data.workflow_preset == "world_core"
                            else ""
                        )
                        + (
                            f"\n\n{_EXTERNAL_PACKET_CONTRACT}"
                            if data.external_packet is not None
                            else ""
                        )
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f'<SOURCE_MANIFEST chunk="{chunk_index}/{chunk_count}">\n'
                        + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
                        + "\n</SOURCE_MANIFEST>\n"
                        "整理这一固定块；不得遗漏或改写 source_key。若这是多块输入，"
                        "只整理本块，不猜测其他块。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=self._output_contract_message(
                        GeneratedWorldGenerationConvergenceOutput
                    ),
                ),
            ],
            temperature=0.0,
        )

    def _convergence_reduce_request(
        self,
        pair: list[tuple[GeneratedWorldGenerationConvergenceOutput, list[str]]],
        *,
        model: str,
        external_packet: bool,
        world_core: bool,
    ) -> LLMCallRequest:
        inputs = [
            {
                "source_keys": keys,
                "convergence": output.model_dump(mode="json"),
            }
            for output, keys in pair
        ]
        return LLMCallRequest(
            model=model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        _CONVERGENCE_SYSTEM_PROMPT
                        + (
                            f"\n\n{_WORLD_CORE_CONVERGENCE_CONTRACT}"
                            if world_core
                            else ""
                        )
                        + (f"\n\n{_EXTERNAL_PACKET_CONTRACT}" if external_packet else "")
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        "<MAP_RESULTS>\n"
                        + json.dumps(inputs, ensure_ascii=False, separators=(",", ":"))
                        + "\n</MAP_RESULTS>\n"
                        "只合并已有卡片和条目，去重后压到最多 7 张卡；不得新增来源中"
                        "没有出现的候选。保留所有原始 source_key 的可追溯归属。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=self._output_contract_message(
                        GeneratedWorldGenerationConvergenceOutput
                    ),
                ),
            ],
            temperature=0.0,
        )

    async def _run_convergence_pass(
        self,
        client: LLMClient,
        request: LLMCallRequest,
        expected_keys: list[str],
        *,
        step_name: str,
        quality_mode: str,
        require_external_disposition: bool = False,
    ) -> tuple[
        GeneratedWorldGenerationConvergenceOutput | None,
        list[str],
        set[str],
    ]:
        last: GeneratedWorldGenerationConvergenceOutput | None = None
        issues: list[str] = []
        covered: set[str] = set()
        for attempt in range(2):
            last = await self._run_structured_with_quality_review(
                client,
                request,
                GeneratedWorldGenerationConvergenceOutput,
                step_name=step_name,
                quality_mode=quality_mode,
            )
            issues, covered = self._convergence_coverage_issues(
                last,
                expected_keys,
                require_external_disposition=require_external_disposition,
            )
            if not issues:
                return last, [], covered
            if attempt == 0:
                request.messages.append(
                    LLMMessage(
                        role="user",
                        content=(
                            "上一轮没有满足确定性覆盖合同，请只修正 source_key 归属和"
                            "计数关系，不新增内容。问题："
                            + json.dumps(issues, ensure_ascii=False)
                        ),
                    )
                )
        return last, issues, covered

    @staticmethod
    def _convergence_coverage_issues(
        generated: GeneratedWorldGenerationConvergenceOutput,
        expected_keys: list[str],
        *,
        require_external_disposition: bool = False,
    ) -> tuple[list[str], set[str]]:
        expected = set(expected_keys)
        card_lists = [card.source_keys for card in generated.decision_cards]
        card_keys = [key for keys in card_lists for key in keys]
        retained = list(generated.retained_source_keys)
        seen = set(card_keys) | set(retained)
        covered = expected & seen
        issues: list[str] = []
        missing = [key for key in expected_keys if key not in seen]
        unknown = sorted(seen - expected)
        if missing:
            issues.append(f"缺少 source_key：{missing}")
        if unknown:
            issues.append(f"出现未知 source_key：{unknown}")
        if len(retained) != len(set(retained)):
            issues.append("retained_source_keys 包含重复项")
        if any(len(keys) != len(set(keys)) for keys in card_lists):
            issues.append("同一卡片重复引用了 source_key")
        overlap = sorted(set(card_keys) & set(retained))
        if overlap:
            issues.append(f"卡片与保留细账重复归属：{overlap}")
        counts = Counter(key for keys in card_lists for key in set(keys))
        duplicated = {key for key, count in counts.items() if count > 1}
        shared = set(generated.shared_source_keys)
        if duplicated != shared:
            issues.append(
                "shared_source_keys 与跨卡重复引用不一致："
                f"应为 {sorted(duplicated)}，实际为 {sorted(shared)}"
            )
        if generated.detail_count_after_deduplication > (
            generated.detail_count_before_grouping
        ):
            issues.append("去重后细节数不能大于归组前细节数")
        if generated.retained_detail_count > (generated.detail_count_after_deduplication):
            issues.append("留在来源的细节数不能大于去重后细节数")
        if require_external_disposition and any(
            item.external_disposition is None
            for card in generated.decision_cards
            for item in card.items
        ):
            issues.append("外部回包条目缺少五类分流结果")
        return issues, covered

    def _convergence_response(
        self,
        data: WorldGenerationConvergenceRequest,
        prepared: dict[str, Any],
        sources: list[dict[str, Any]],
        *,
        manifest_hash: str,
        generated: GeneratedWorldGenerationConvergenceOutput | None,
        issues: list[str],
        covered: set[str],
        model: str,
        provider: str,
        knowledge_review: dict[str, Any] | None = None,
    ) -> WorldGenerationConvergenceResponse:
        manifest = [source["manifest"] for source in sources]
        source_keys = {item.key for item in manifest}
        complete = generated is not None and not issues and covered == source_keys
        cards: list[WorldGenerationConvergenceDecisionCard] = []
        if generated is not None:
            for card_index, card in enumerate(generated.decision_cards, start=1):
                known_keys = list(
                    dict.fromkeys(key for key in card.source_keys if key in source_keys)
                )
                if not known_keys:
                    continue
                cards.append(
                    WorldGenerationConvergenceDecisionCard(
                        card_id=f"C{card_index}",
                        title=card.title,
                        common_ground=card.common_ground,
                        items=[
                            WorldGenerationConvergenceDecisionItem(
                                item_id=f"C{card_index}I{item_index}",
                                text=item.text,
                                suggested_disposition=item.suggested_disposition,
                                world_core_rule_key=item.world_core_rule_key,
                                external_disposition=item.external_disposition,
                            )
                            for item_index, item in enumerate(card.items, start=1)
                        ],
                        dependencies=card.dependencies,
                        affected_targets=card.affected_targets,
                        source_keys=known_keys,
                        why_now=card.why_now,
                    )
                )
        missing = [item.key for item in manifest if item.key not in covered]
        scope_parts = [f"最近 {len(data.messages)} 条对话"]
        if any(item.kind == "pasted_context" for item in manifest):
            scope_parts.append("作者粘贴材料")
        if prepared["source_snapshot"].kind == "world_bible_page":
            scope_parts.append("当前来源页")
        if prepared["chapters"]:
            scope_parts.append(f"{len(prepared['chapters'])} 章正文摘录")
        if prepared["assets"]["items"]:
            scope_parts.append(f"{len(prepared['assets']['items'])} 项已选或页面引用材料")
        if any(item.kind == "project_background" for item in manifest):
            scope_parts.append("相关项目背景")
        before_grouping = generated.detail_count_before_grouping if generated else 0
        after_deduplication = (
            generated.detail_count_after_deduplication if generated else 0
        )
        retained_in_sources = generated.retained_detail_count if generated else 0
        next_boundary = (
            generated.next_boundary
            if generated
            else "当前结果未通过覆盖校验，请调整范围后重新收束。"
        )
        return WorldGenerationConvergenceResponse(
            coverage=WorldGenerationConvergenceCoverage(
                scope_label="、".join(scope_parts),
                source_count=len(manifest),
                covered_source_keys=[
                    item.key for item in manifest if item.key in covered
                ],
                missing_source_keys=missing,
                stale_source_keys=[],
                excluded_message_count=data.excluded_message_count,
                manifest_hash=manifest_hash,
                complete=complete,
                issues=issues[:20],
            ),
            manifest=manifest,
            detail_summary=WorldGenerationConvergenceDetailSummary(
                before_grouping=before_grouping,
                after_deduplication=after_deduplication,
                retained_in_sources=retained_in_sources,
            ),
            decision_cards=cards,
            next_boundary=next_boundary,
            model=model,
            provider=provider,
            context_usage=self._context_usage(prepared["background"]),
            source_snapshot=prepared["source_snapshot"],
            external_packet=data.external_packet,
            world_core=self._world_core_handoff(
                data,
                manifest,
                generated,
                coverage_complete=complete,
            ),
            knowledge_review=knowledge_review,
        )

    @staticmethod
    def _world_core_handoff(
        data: WorldGenerationConvergenceRequest,
        manifest: list[WorldGenerationConvergenceManifestItem],
        generated: GeneratedWorldGenerationConvergenceOutput | None,
        *,
        coverage_complete: bool,
    ) -> WorldCoreHandoff | None:
        if data.workflow_preset != "world_core":
            return None
        seed_keys = [
            item.key
            for item in manifest
            if item.source_ref.source_type in {"author_message", "author_pasted_context"}
        ]
        core = generated.world_core if generated else None
        actual = [item.source_key for item in core.author_seeds] if core else []
        atoms = core.rule_atoms if core else []
        issues: list[str] = []
        if not coverage_complete:
            issues.append("收束来源覆盖未通过")
        if sorted(actual) != sorted(seed_keys) or len(actual) != len(set(actual)):
            issues.append("作者 seed 必须恰好覆盖冻结 manifest")
        if not 3 <= len(atoms) <= 7:
            issues.append("World Core 需要 3–7 条规则")
        if len({atom.rule_key for atom in atoms}) != len(atoms):
            issues.append("World Core rule_key 必须唯一")
        manifest_keys = {item.key for item in manifest}
        if any(set(atom.source_keys) - manifest_keys for atom in atoms):
            issues.append("World Core 规则包含未知 source_key")
        bindings = (
            [
                item.world_core_rule_key
                for card in generated.decision_cards
                for item in card.items
                if item.world_core_rule_key
            ]
            if generated
            else []
        )
        rule_keys = {atom.rule_key for atom in atoms}
        if (
            set(bindings) - rule_keys
            or len(bindings) != len(set(bindings))
            or set(bindings) != rule_keys
        ):
            issues.append("每条 World Core 规则必须恰好绑定一个决定项")
        for atom in atoms:
            for field in ("can", "cannot", "cost", "failure", "maintenance"):
                if (
                    getattr(atom, field).strip().upper() == "N/A"
                    and not atom.na_reasons.get(field, "").strip()
                ):
                    issues.append(f"规则 {field} 为 N/A 时必须说明理由")
        if core and core.blocking_contradictions:
            issues.append("存在阻断矛盾")
        if not core or not core.vertical_slice:
            issues.append("需要完整的日常与故障纵切")
        elif core.vertical_slice.rule_key not in {atom.rule_key for atom in atoms}:
            issues.append("纵切必须引用现有 rule_key")
        return WorldCoreHandoff(
            ready_for_handoff=not issues,
            issues=issues[:20],
            author_seed_source_keys=seed_keys,
            rule_count=len(atoms),
            snapshot=core,
        )
