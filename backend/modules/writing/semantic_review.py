"""Independent prose review and finding-bound revision workflows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.agent_step_harness import (
    build_managed_llm_provenance,
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftResponse,
    WritingSemanticReviewChunkOutput,
)
from modules.writing.text_sanitizer import sanitize_writing_text

SEMANTIC_REVIEW_TIMEOUT_SECONDS = 1800
_MAX_REVIEW_CHUNKS = 24
_CHUNK_CHARACTER_BUDGET = 80_000


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contract_dict(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[union-attr]
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return deepcopy(value)
    raise ValidationError("Scene execution contract has an unsupported shape")


async def _scene_bundle(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str | None,
) -> dict[str, Any] | None:
    if not scene_id:
        return None
    from modules.story.facade import get_scene_execution_bundle

    return _contract_dict(
        await get_scene_execution_bundle(db, novel_id, scene_id),
    )


def _bundle_hash(bundle: dict[str, Any] | None) -> str | None:
    if not bundle:
        return None
    return str(
        bundle.get("bundle_hash") or bundle.get("contract_hash") or _stable_hash(bundle)
    )


async def validate_candidate_upstream(
    db: AsyncSession,
    draft: object,
    *,
    require_review: bool = True,
) -> None:
    """Fail closed when a generated candidate no longer matches its sources."""
    provenance = dict(getattr(draft, "provenance_json", None) or {})
    if provenance.get("source") not in {"writing_generate", "writing_targeted_revision"}:
        return

    confirmation_id = provenance.get("context_confirmation_id")
    if confirmation_id:
        from modules.evidence.facade import require_fresh_confirmation

        try:
            await require_fresh_confirmation(
                db,
                novel_id=str(getattr(draft, "novel_id")),
                action="writing.generate",
                confirmation_id=str(confirmation_id),
            )
        except (LookupError, ValueError) as exc:
            raise ConflictError("AI 参考资料已变化，请重新生成或审查正文建议。") from exc

    stored_bundle_hash = provenance.get("scene_execution_bundle_hash")
    if stored_bundle_hash:
        current = await _scene_bundle(
            db,
            novel_id=str(getattr(draft, "novel_id")),
            scene_id=str(provenance.get("scene_id") or "") or None,
        )
        if _bundle_hash(current) != stored_bundle_hash:
            raise ConflictError("故事总纲或场景合同已变化，请重新生成或审查正文建议。")

    if not require_review or not provenance.get("review_required"):
        return
    review = provenance.get("independent_review")
    if not isinstance(review, dict):
        raise ConflictError("请先完成独立语义审查，再采用正文建议。")
    if review.get("draft_hash") != getattr(draft, "content_hash", None):
        raise ConflictError("正文在审查后已变化，请重新审查。")
    if review.get("verdict") != "pass" or int(review.get("blocking_count") or 0):
        raise ConflictError("独立语义审查仍有阻断项，请先返修。")


class WritingSemanticWorkflowService:
    def __init__(
        self,
        repo: WritingDraftRepository | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._repo = repo or WritingDraftRepository()
        self._llm = llm_client

    @asynccontextmanager
    async def _open_client(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        snapshot: dict[str, Any],
    ) -> AsyncIterator[LLMClient]:
        if self._llm is not None:
            yield self._llm
            return
        from modules.project.facade import (
            create_project_snapshot_llm_client,
            restore_project_llm_execution_settings,
        )

        settings = await restore_project_llm_execution_settings(db, novel_id, snapshot)
        client = create_project_snapshot_llm_client(
            settings,
            timeout_override=SEMANTIC_REVIEW_TIMEOUT_SECONDS,
            novel_id=novel_id,
        )
        try:
            yield client
        finally:
            await client.close()

    @staticmethod
    async def _checkpoint(db: AsyncSession) -> None:
        await db.commit()
        if db.in_transaction():
            raise RuntimeError(
                "writing semantic workflow requires a transaction-free checkpoint"
            )
        db.expire_all()

    async def _freeze_draft(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        draft_id: str,
        role: str,
    ) -> dict[str, Any]:
        draft = await self._repo.get(db, uuid.UUID(draft_id))
        if draft is None or str(draft.novel_id) != novel_id:
            raise NotFoundError(f"Draft {draft_id} not found")
        if draft.status == "deprecated":
            raise ValidationError("已归档正文不能作为新审查对象")
        provenance = dict(draft.provenance_json or {})
        bundle = await _scene_bundle(
            db,
            novel_id=novel_id,
            scene_id=str(provenance.get("scene_id") or "") or None,
        )
        return {
            "draft_id": str(draft.id),
            "chapter_index": int(draft.chapter_index),
            "title": draft.title,
            "content": draft.content or "",
            "content_hash": draft.content_hash,
            "status": draft.status,
            "role": role,
            "source_task_id": provenance.get("source_task_id"),
            "scene_id": provenance.get("scene_id"),
            "scene_execution_bundle": bundle,
            "scene_execution_bundle_hash": _bundle_hash(bundle),
            "upstream_manifest": deepcopy(provenance.get("upstream_manifest") or []),
        }

    async def _freeze_review_set(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        draft_ids: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        targets = [
            await self._freeze_draft(
                db,
                novel_id=novel_id,
                draft_id=draft_id,
                role="target",
            )
            for draft_id in draft_ids
        ]
        known = set(draft_ids)
        adjacent: list[dict[str, Any]] = []
        nid = uuid.UUID(novel_id)
        for chapter in sorted(
            {
                item["chapter_index"] + offset
                for item in targets
                for offset in (-1, 1)
                if item["chapter_index"] + offset >= 1
            }
        ):
            draft = await self._repo.get_latest_by_chapter(db, nid, chapter)
            if draft is None or str(draft.id) in known:
                continue
            adjacent.append(
                await self._freeze_draft(
                    db,
                    novel_id=novel_id,
                    draft_id=str(draft.id),
                    role="adjacent_regression_context",
                )
            )
            known.add(str(draft.id))
        return targets, adjacent

    @staticmethod
    def _chunks(targets: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_size = 0
        for item in targets:
            size = len(item["content"])
            if current and current_size + size > _CHUNK_CHARACTER_BUDGET:
                chunks.append(current)
                current = []
                current_size = 0
            current.append(item)
            current_size += size
        if current:
            chunks.append(current)
        if len(chunks) > _MAX_REVIEW_CHUNKS:
            raise ValidationError("本次全书审查超过 24 个可验证分片，请按卷分批审查。")
        return chunks

    @staticmethod
    def _review_request(
        *,
        model: str,
        scope: str,
        chunk: list[dict[str, Any]],
        adjacent: list[dict[str, Any]],
    ) -> LLMCallRequest:
        payload = {
            "scope": scope,
            "targets": chunk,
            "adjacent_regression_context": adjacent,
        }
        return LLMCallRequest(
            model=model,
            temperature=0.1,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是与正文生成器分离的长篇小说语义审稿人。"
                        "独立检查 POV/知识边界、Scene 合同漏项、因果、连续性、"
                        "人物声音、节奏和文学可读性。机械检查通过不代表文学通过。"
                        "只报告能给出正文位置的问题；contract_refs 引用已给定的合同字段。"
                        "相邻章只用于回归对照，问题位置必须落在 targets。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                ),
            ],
        )

    async def review_for_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        novel_id: str,
        draft_ids: list[str],
        scope: str,
        llm_execution_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        from infrastructure.tasks.facade import require_task_checkpoint_session
        from modules.project.facade import require_active_project

        require_task_checkpoint_session(db)
        await require_active_project(db, novel_id)
        targets, adjacent = await self._freeze_review_set(
            db,
            novel_id=novel_id,
            draft_ids=draft_ids,
        )
        chunks = self._chunks(targets)
        profile = llm_execution_snapshot.get("profile")
        model = str(profile.get("model") or "") if isinstance(profile, dict) else ""
        if not model:
            raise ValidationError("semantic review requires a frozen project LLM model")
        frozen_hash = _stable_hash(
            [
                {
                    "draft_id": item["draft_id"],
                    "content_hash": item["content_hash"],
                    "scene_execution_bundle_hash": item["scene_execution_bundle_hash"],
                    "role": item["role"],
                }
                for item in [*targets, *adjacent]
            ]
        )

        outputs: list[WritingSemanticReviewChunkOutput] = []
        managed_steps: list[dict[str, Any]] = []
        try:
            async with self._open_client(
                db,
                novel_id=novel_id,
                snapshot=llm_execution_snapshot,
            ) as client:
                await self._checkpoint(db)
                for index, chunk in enumerate(chunks, 1):
                    request = self._review_request(
                        model=model,
                        scope=scope,
                        chunk=chunk,
                        adjacent=adjacent,
                    )
                    step_name = f"writing.semantic_review.chunk_{index}"
                    output = await run_managed_structured(
                        client,
                        request,
                        WritingSemanticReviewChunkOutput,
                        step_name=step_name,
                        timeout=SEMANTIC_REVIEW_TIMEOUT_SECONDS,
                    )
                    outputs.append(output)
                    managed_steps.append(
                        build_managed_llm_provenance(
                            client,
                            step_name=step_name,
                            request=request,
                            novel_id=novel_id,
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe = redact_diagnostic(f"{type(exc).__name__}: {exc}", limit=500)
            raise RuntimeError(safe) from None

        await require_active_project(db, novel_id)
        current_targets, current_adjacent = await self._freeze_review_set(
            db,
            novel_id=novel_id,
            draft_ids=draft_ids,
        )
        current_hash = _stable_hash(
            [
                {
                    "draft_id": item["draft_id"],
                    "content_hash": item["content_hash"],
                    "scene_execution_bundle_hash": item["scene_execution_bundle_hash"],
                    "role": item["role"],
                }
                for item in [*current_targets, *current_adjacent]
            ]
        )
        if current_hash != frozen_hash:
            raise ConflictError("审查期间正文或上游合同已变化，已丢弃过时结果。")

        target_by_id = {item["draft_id"]: item for item in targets}
        findings: list[dict[str, Any]] = []
        not_checked: list[str] = []
        for output in outputs:
            not_checked.extend(output.not_checked)
            for finding in output.findings:
                data = finding.model_dump(mode="json")
                draft_id = data["location"]["draft_id"]
                target = target_by_id.get(draft_id)
                if target is None:
                    not_checked.append("审查返回了非目标正文的位置，已丢弃")
                    continue
                if int(data["location"]["chapter_index"]) != target["chapter_index"]:
                    not_checked.append("审查返回了错误章号，已丢弃")
                    continue
                excerpt = data["location"]["excerpt"]
                offset = target["content"].find(excerpt)
                if offset >= 0:
                    data["location"]["start_hint"] = offset
                    data["location"]["end_hint"] = offset + len(excerpt)
                finding_id = "finding_" + _stable_hash(data)[:20]
                findings.append({"finding_id": finding_id, **data})
        findings = list({item["finding_id"]: item for item in findings}.values())
        blocking_count = sum(
            item["severity"] in {"blocker", "major"} for item in findings
        )
        verdict = "pass" if blocking_count == 0 else "needs_revision"
        reviewed_at = datetime.now(UTC).isoformat()

        for target in current_targets:
            draft = await self._repo.get_for_update(db, uuid.UUID(target["draft_id"]))
            if draft is None or draft.content_hash != target["content_hash"]:
                raise ConflictError("正文在审查落库前已变化。")
            draft_findings = [
                item
                for item in findings
                if item["location"]["draft_id"] == target["draft_id"]
            ]
            draft_blocking = sum(
                item["severity"] in {"blocker", "major"} for item in draft_findings
            )
            draft.provenance_json = {
                **(draft.provenance_json or {}),
                "independent_review": {
                    "schema": "writing_semantic_review.v1",
                    "review_task_id": task_id,
                    "draft_hash": draft.content_hash,
                    "scene_execution_bundle_hash": target["scene_execution_bundle_hash"],
                    "reviewed_at": reviewed_at,
                    "scope": scope,
                    "verdict": "pass" if draft_blocking == 0 else "needs_revision",
                    "blocking_count": draft_blocking,
                    "finding_ids": [item["finding_id"] for item in draft_findings],
                    "reviewer_separate_from_generator": True,
                },
            }
            db.add(draft)

        await db.flush()
        return {
            "schema": "writing_semantic_review.v1",
            "review_task_id": task_id,
            "scope": scope,
            "verdict": verdict,
            "blocking_count": blocking_count,
            "coverage": {
                "target_draft_ids": draft_ids,
                "target_chapters": [item["chapter_index"] for item in targets],
                "adjacent_regression_draft_ids": [item["draft_id"] for item in adjacent],
                "frozen_manifest_hash": frozen_hash,
                "chunk_count": len(chunks),
            },
            "frozen_manifest": [
                {
                    key: item[key]
                    for key in (
                        "draft_id",
                        "chapter_index",
                        "content_hash",
                        "scene_id",
                        "scene_execution_bundle_hash",
                        "role",
                    )
                }
                for item in [*targets, *adjacent]
            ],
            "findings": findings,
            "not_checked": list(dict.fromkeys(not_checked)),
            "managed_llm_steps": managed_steps,
            "mechanical_checks_can_sign_literary_pass": False,
            "reviewer_separate_from_generator": True,
        }

    async def revise_for_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        novel_id: str,
        draft_id: str,
        review_task_id: str,
        finding_ids: list[str],
        instruction: str | None,
        llm_execution_snapshot: dict[str, Any],
    ) -> WritingDraftResponse:
        from infrastructure.tasks.facade import (
            get_completed_task_payload,
            require_task_checkpoint_session,
        )
        from modules.project.facade import require_active_project

        require_task_checkpoint_session(db)
        await require_active_project(db, novel_id)
        review = await get_completed_task_payload(
            db,
            task_id=review_task_id,
            task_type="writing_semantic_review",
            novel_id=novel_id,
        )
        if review is None:
            raise NotFoundError("独立语义审查任务不存在或未完成")
        selected = [
            item
            for item in review.result.get("findings") or []
            if isinstance(item, dict) and item.get("finding_id") in finding_ids
        ]
        if {item.get("finding_id") for item in selected} != set(finding_ids):
            raise ConflictError("返修问题集与审查回执不一致")
        if any(item.get("location", {}).get("draft_id") != draft_id for item in selected):
            raise ConflictError("返修问题不属于目标正文")

        base = await self._repo.get(db, uuid.UUID(draft_id))
        if base is None or str(base.novel_id) != novel_id:
            raise NotFoundError(f"Draft {draft_id} not found")
        frozen = next(
            (
                item
                for item in review.result.get("frozen_manifest") or []
                if isinstance(item, dict) and item.get("draft_id") == draft_id
            ),
            None,
        )
        if frozen is None or frozen.get("content_hash") != base.content_hash:
            raise ConflictError("审查后正文已变化，不能套用旧问题返修。")
        await validate_candidate_upstream(db, base, require_review=False)
        provenance = dict(base.provenance_json or {})
        bundle = await _scene_bundle(
            db,
            novel_id=novel_id,
            scene_id=str(provenance.get("scene_id") or "") or None,
        )
        if frozen.get("scene_execution_bundle_hash") != _bundle_hash(bundle):
            raise ConflictError("审查后场景合同已变化，不能套用旧问题返修。")
        profile = llm_execution_snapshot.get("profile")
        model = str(profile.get("model") or "") if isinstance(profile, dict) else ""
        if not model:
            raise ValidationError("targeted revision requires a frozen project LLM model")
        preserve = list(
            dict.fromkeys(
                value
                for item in selected
                for value in item.get("preserve") or []
                if isinstance(value, str) and value.strip()
            )
        )
        contract = (bundle or {}).get("execution_contract") or {}
        must_not_change = list(
            dict.fromkeys(
                value
                for value in [contract.get("must_not_happen"), *preserve]
                if isinstance(value, str) and value.strip()
            )
        )
        request = LLMCallRequest(
            model=model,
            temperature=0.4,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是定向改稿执行者。只修复指定 finding，严格保留 preserve 和"
                        " must_not_change，不扩展世界设定，不改写无关段落。"
                        "输出完整的新正文候选，不要输出说明或 Markdown 围栏。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "base_draft": {
                                "draft_id": draft_id,
                                "chapter_index": base.chapter_index,
                                "content": base.content or "",
                            },
                            "findings": selected,
                            "execution_bundle": bundle,
                            "allowed_scope": "single_draft",
                            "preserve": preserve,
                            "must_not_change": must_not_change,
                            "author_instruction": instruction,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                ),
            ],
        )
        try:
            async with self._open_client(
                db,
                novel_id=novel_id,
                snapshot=llm_execution_snapshot,
            ) as client:
                await self._checkpoint(db)
                response = await run_managed_generate(
                    client,
                    request,
                    step_name="writing.targeted_revision.generate",
                    timeout=SEMANTIC_REVIEW_TIMEOUT_SECONDS,
                )
                managed = build_managed_llm_provenance(
                    client,
                    step_name="writing.targeted_revision.generate",
                    request=request,
                    novel_id=novel_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe = redact_diagnostic(f"{type(exc).__name__}: {exc}", limit=500)
            raise RuntimeError(safe) from None

        await require_active_project(db, novel_id)
        current = await self._repo.get_for_update(db, uuid.UUID(draft_id))
        if current is None or current.content_hash != frozen["content_hash"]:
            raise ConflictError("返修期间基线正文已变化，已丢弃过时结果。")
        await validate_candidate_upstream(db, current, require_review=False)
        current_bundle = await _scene_bundle(
            db,
            novel_id=novel_id,
            scene_id=str(provenance.get("scene_id") or "") or None,
        )
        if _bundle_hash(current_bundle) != _bundle_hash(bundle):
            raise ConflictError("返修期间场景合同已变化，已丢弃过时结果。")
        content = sanitize_writing_text(response.content.strip()).text or ""
        if not content:
            raise ValidationError("定向返修返回了空正文")
        candidate = await self._repo.create_with_status(
            db,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=base.chapter_index,
                title=base.title,
                content=content,
                provenance_json={
                    **provenance,
                    "source": "writing_targeted_revision",
                    "source_task_id": task_id,
                    "review_task_id": review_task_id,
                    "finding_ids": finding_ids,
                    "base_draft_id": draft_id,
                    "base_content_hash": base.content_hash,
                    "scene_execution_bundle_hash": _bundle_hash(bundle),
                    "allowed_scope": "single_draft",
                    "preserve": preserve,
                    "must_not_change": must_not_change,
                    "supersedes": draft_id,
                    "review_required": True,
                    "independent_review": None,
                    "managed_llm_steps": [managed],
                },
            ),
            status="candidate",
        )
        return WritingDraftResponse.model_validate(candidate)
