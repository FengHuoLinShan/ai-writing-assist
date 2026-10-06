"""语义检视阶段：单页检视与 findings 归一。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.world.llm_schemas import GeneratedWorldSemanticInspectionOutput
from modules.world.schemas import (
    WorldGenerationSemanticInspectionFinding,
    WorldGenerationSemanticInspectionReceipt,
    WorldGenerationSemanticInspectionRequest,
    WorldGenerationSemanticInspectionResponse,
    WorldGenerationSourceSnapshot,
)
from modules.world.services.worldbuilding.generation_center.shared import (
    _CONVERGENCE_CALL_INPUT_CHARS,
    _SEMANTIC_INSPECTION_SYSTEM_PROMPT,
    WORLD_GENERATION_TIMEOUT_SECONDS,
)
from modules.world.services.worldbuilding.knowledge_governance import (
    serialize_governed_output,
)
from modules.world.services.worldbuilding.structured_reference_retry import (
    run_structured_with_known_keys,
)


class _InspectionStageMixin:
    async def inspect_current_page(
        self,
        db: AsyncSession,
        data: WorldGenerationSemanticInspectionRequest,
    ) -> WorldGenerationSemanticInspectionResponse:
        """Inspect one frozen current page and replace its pending diagnostics."""
        execution_snapshot, model = await self._freeze_execution_snapshot(
            db,
            data.novel_id,
        )
        prepared = await self._prepare(
            db,
            data,
            operation="world.generation.semantic_inspection",
            model=model,
        )
        provider = ""
        knowledge_review: dict[str, Any] | None = None
        try:
            sources = [
                source
                for source in self._convergence_sources(data, prepared)
                if source["manifest"].kind == "source_page"
            ]
            if not sources:
                raise ValidationError(
                    "Semantic inspection requires a readable page source"
                )
            if sum(len(source["content"]) for source in sources) > (
                _CONVERGENCE_CALL_INPUT_CHARS
            ):
                raise ValidationError(
                    "This page is too large for one semantic inspection; split it first"
                )
            async with self._open_client(
                db,
                data.novel_id,
                execution_snapshot=execution_snapshot,
                high_quality=data.quality_mode == "pro",
            ) as client:
                provider = str(client.provider)
                async with asyncio.timeout(WORLD_GENERATION_TIMEOUT_SECONDS):
                    generated = await self._run_semantic_inspection_pass(
                        client,
                        data,
                        sources,
                        model=model,
                    )
                _text, knowledge_review = await self._govern_text(
                    client,
                    capability="world.generation.semantic_inspection",
                    novel_id=data.novel_id,
                    prepared=prepared,
                    text=serialize_governed_output(generated),
                    task_instruction="检查当前世界书页的语义问题；每条发现必须有页面原文佐证",
                )
                if knowledge_review.get("status") != "passed":
                    raise ValidationError(
                        "语义检修结果未通过知识审查（发现缺乏来源支持或含未检查项），"
                        "本次不落任何诊断；请调整检查范围后重试。"
                    )
            await self._revalidate_source(db, data, prepared)
            findings = self._semantic_inspection_findings(sources, generated)
            snapshot: WorldGenerationSourceSnapshot = prepared["source_snapshot"]
            if not snapshot.content_hash or not snapshot.page_version:
                raise ValidationError("Semantic inspection source has no stable version")
            receipt = WorldGenerationSemanticInspectionReceipt(
                scope_label=f"当前世界书页《{snapshot.title or '未命名页面'}》",
                source_version=snapshot.page_version,
                target_hash=snapshot.content_hash,
                checks_run=[
                    "权威顺序",
                    "开放问题是否被写死",
                    "授权来源是否含混",
                    "旧投影或旧状态表述",
                ],
                not_run=[
                    "其他世界书页面",
                    "故事总览与章节正文",
                    "地图、人物与 Scene",
                    "发布结构门禁",
                ],
                omissions=["语义发现仅供作者决定或改进，不能证明页面完整无误。"],
                completed_at=datetime.now(UTC),
            )
            queue_items = await self._conflicts.replace_semantic_inspection(
                db,
                data.novel_id,
                target={
                    "kind": "world_bible_page",
                    "page_id": snapshot.page_id,
                    "title": snapshot.title,
                    "page_version": snapshot.page_version,
                },
                target_hash=snapshot.content_hash,
                findings=findings,
                receipt=receipt,
            )
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
            result_refs=[
                {
                    "type": "world_semantic_inspection",
                    "id": receipt.target_hash,
                }
            ],
        )
        return WorldGenerationSemanticInspectionResponse(
            findings=findings,
            queue_item_ids=[item.id for item in queue_items],
            receipt=receipt,
            model=model,
            provider=provider,
            context_usage=self._context_usage(prepared["background"]),
            source_snapshot=prepared["source_snapshot"],
            knowledge_review=knowledge_review,
        )

    def _semantic_inspection_request(
        self,
        data: WorldGenerationSemanticInspectionRequest,
        sources: list[dict[str, Any]],
        *,
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
                LLMMessage(role="system", content=_SEMANTIC_INSPECTION_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=(
                        "<SOURCE_MANIFEST>\n"
                        + json.dumps(
                            manifest,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n</SOURCE_MANIFEST>\n只检修这一页当前版本。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=self._output_contract_message(
                        GeneratedWorldSemanticInspectionOutput
                    ),
                ),
            ],
            temperature=0.0,
        )

    async def _run_semantic_inspection_pass(
        self,
        client: LLMClient,
        data: WorldGenerationSemanticInspectionRequest,
        sources: list[dict[str, Any]],
        *,
        model: str,
    ) -> GeneratedWorldSemanticInspectionOutput:
        request = self._semantic_inspection_request(data, sources, model=model)
        return await run_structured_with_known_keys(
            client,
            request,
            generate=lambda: self._run_structured_with_quality_review(
                client,
                request,
                GeneratedWorldSemanticInspectionOutput,
                step_name="world.generation.semantic_inspection",
                quality_mode=data.quality_mode,
            ),
            known_keys={source["manifest"].key for source in sources},
            keys_of=lambda generated: (
                key for finding in generated.findings for key in finding.source_keys
            ),
            repair_note=(
                "上一轮引用了不存在的 source_key。只修正证据引用；"
                "不得新增发现。未知 key："
            ),
            error_message="World semantic inspection returned unknown source keys",
        )

    @staticmethod
    def _semantic_inspection_findings(
        sources: list[dict[str, Any]],
        generated: GeneratedWorldSemanticInspectionOutput,
    ) -> list[WorldGenerationSemanticInspectionFinding]:
        by_key = {source["manifest"].key: source["manifest"] for source in sources}
        findings: list[WorldGenerationSemanticInspectionFinding] = []
        seen: set[tuple[str, str]] = set()
        for generated_finding in generated.findings:
            identity = (
                " ".join(generated_finding.summary.split()).casefold(),
                " ".join(generated_finding.location.split()).casefold(),
            )
            if identity in seen:
                continue
            seen.add(identity)
            keys = list(dict.fromkeys(generated_finding.source_keys))
            findings.append(
                WorldGenerationSemanticInspectionFinding(
                    item_id=f"S{len(findings) + 1}",
                    author_action=generated_finding.author_action,
                    finding_type=generated_finding.finding_type,
                    summary=generated_finding.summary,
                    evidence=generated_finding.evidence,
                    location=generated_finding.location,
                    next_step=generated_finding.next_step,
                    source_keys=keys,
                    evidence_refs=[by_key[key] for key in keys],
                )
            )
        return findings
