"""Bounded candidate review; World alone owns adoption and undo."""

from __future__ import annotations

import asyncio
import json
from collections import Counter

from core.errors import ConflictError
from infrastructure.llm.errors import LLMError
from modules.imports.review_resolution_schemas import (
    MAX_GROUP_REQUESTS,
    VERSION,
    ReviewJudgments,
    judgment_outcome,
)
from modules.imports.targeted_completion import _source_ref, stable_hash
from shared.utils import parse_uuid


async def review_summary(
    db, novel_id, *, start_chapter=1, end_chapter=0, asset_keys=None, workflow_id=None
):
    from modules.story.facade import get_scenes_by_novel
    from modules.world.facade import list_review_resolution_candidates

    rows = await list_review_resolution_candidates(
        db,
        novel_id,
        workflow_id=workflow_id,
        keys=set(asset_keys) if asset_keys else None,
    )
    scenes = await get_scenes_by_novel(
        db, novel_id, status_filter=["draft", "candidate", "canonical"]
    )
    selected_scenes = {
        str(scene["id"]): scene
        for scene in scenes
        if any(
            int(ch) >= start_chapter and (not end_chapter or int(ch) <= end_chapter)
            for ch in scene.get("chapter_ids", [])
            if str(ch).isdigit()
        )
    }
    selected = []
    for row in rows:
        scene_id = str(row["meta"].get("scene_id") or "")
        chapter = row["meta"].get("source_chapter_index")
        if scene_id and scene_id not in selected_scenes:
            continue
        if chapter and (
            int(chapter) < start_chapter or end_chapter and int(chapter) > end_chapter
        ):
            continue
        selected.append(row)
    if asset_keys and set(asset_keys) != {row["key"] for row in selected}:
        raise ConflictError("所选资料已变化或不在章节范围内")
    return {
        "version": VERSION,
        "counts": dict(Counter(row["kind"] for row in selected)),
        "unclassified": len(selected),
        "candidate_keys": [row["key"] for row in selected],
        "candidates": selected,
        "scenes": list(selected_scenes.values()),
    }


async def freeze_resolution(
    db,
    *,
    novel_id,
    start_chapter,
    end_chapter,
    asset_keys=None,
    repair_scenes=True,
    workflow_id=None,
):
    from modules.writing.facade import list_latest_drafts_for_chapters

    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, list(range(start_chapter, end_chapter + 1)), content_limit=1
    )
    manifest = {str(draft.id): draft.content_hash for draft in drafts}
    if not manifest or any(not value for value in manifest.values()):
        raise ValueError("智能整理需要可验证的章节正文")
    summary = await review_summary(
        db,
        novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        asset_keys=asset_keys,
        workflow_id=workflow_id,
    )
    from modules.story.facade import preview_import_scene_resolution

    scene_items = (
        await preview_import_scene_resolution(db, novel_id, start_chapter, end_chapter)
        if repair_scenes
        else []
    )
    omissions = []
    if repair_scenes:
        for scene in summary["scenes"]:
            chapters = [
                int(value)
                for value in scene.get("chapter_ids", [])
                if str(value).isdigit()
            ]
            if chapters and (
                min(chapters) < start_chapter or max(chapters) > end_chapter
            ):
                omissions.append(
                    {
                        "scene_id": str(scene["id"]),
                        "title": scene.get("title") or "场景",
                        "chapter_from": min(chapters),
                        "chapter_to": max(chapters),
                    }
                )
    if omissions and not scene_items and not summary["candidates"]:
        from core.errors import ValidationError

        first = omissions[0]
        raise ValidationError(
            f"所选范围只包含跨章场景的一部分，请至少包含第 "
            f"{first['chapter_from']}～{first['chapter_to']} 章"
        )
    return {
        "version": VERSION,
        "scope_omissions": omissions,
        "scene_items": scene_items,
        "prompt_manifest": prompt_manifest(),
        "chapter_from": start_chapter,
        "chapter_to": end_chapter,
        "source_manifest": manifest,
        "items": summary["candidates"],
        "repair_scenes": repair_scenes,
        "scope_hash": stable_hash(
            {
                "novel_id": novel_id,
                "chapters": [start_chapter, end_chapter],
                "keys": sorted(asset_keys or []),
                "repair_scenes": repair_scenes,
                "manifest": manifest,
            }
        ),
    }


async def authorize_resolution(db, *, novel_id, task_id, permission):
    from modules.world.facade import authorize_review_resolution

    if not permission["items"]:
        return permission
    grant = await authorize_review_resolution(
        db,
        novel_id=novel_id,
        task_id=task_id,
        source_manifest=permission["source_manifest"],
        chapter_from=permission["chapter_from"],
        chapter_to=permission["chapter_to"],
        items=permission["items"],
    )
    return {**permission, **grant}


async def judge(client, *, rows, evidence, stage="review", previous=None):
    from infrastructure.llm.agent_step_harness import (
        ContextBudget,
        run_managed_structured,
    )
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    payload = {
        "stage": stage,
        "candidates": [
            {
                key: row[key]
                for key in ("key", "kind", "fields", "identities", "required_fields")
            }
            for row in rows
        ],
        "evidence": evidence,
        "previous": previous,
    }
    if len(json.dumps(payload, ensure_ascii=False)) > 100_000:
        raise ValueError("该组原文超过单次查读范围，保留未完成项")
    result = await asyncio.wait_for(
        run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                temperature=0.1,
                max_tokens=32768,
                response_format={"type": "json_object"},
                messages=[
                    LLMMessage(
                        role="system",
                        content=load_prompt("review_resolution")
                        + "\n"
                        + load_prompt("review_resolution_groups")
                        + "\nJSON Schema:\n"
                        + json.dumps(
                            ReviewJudgments.model_json_schema(), ensure_ascii=False
                        ),
                    ),
                    LLMMessage(
                        role="user", content=json.dumps(payload, ensure_ascii=False)
                    ),
                ],
            ),
            ReviewJudgments,
            step_name=f"imports.review_resolution.{stage}",
            max_fix_attempts=0,
            transport_retries=False,
            timeout=600,
            context_budget=ContextBudget(
                max_input_chars=100_000, max_output_chars=80_000
            ),
        ),
        timeout=600,
    )
    if {item.candidate_key for item in result.judgments} != {row["key"] for row in rows}:
        raise ValueError("模型返回的候选集合不完整")
    return result


def evidence_for_judgment(judgment, evidence):
    by_key = {item["key"]: item for item in evidence}
    selected = []
    valid = True
    for ref in [
        ref for refs in judgment.field_evidence.values() for ref in refs
    ] + judgment.counter_evidence:
        item = by_key.get(ref.evidence_key)
        if item is None or item["text"].count(ref.quote) != 1:
            valid = False
        else:
            selected.append((item["source_ref"], ref.quote))
    return selected, valid


def package_item(row, judgment, selected, workflow_id):
    refs = [_source_ref(ref, quote, workflow_id=workflow_id) for ref, quote in selected]
    kind = {
        "entity": "core_entity",
        "relation": "entity_relation",
        "alias": "entity_alias",
    }[row["kind"]]
    fields = row["fields"]
    if row["kind"] == "entity":
        payload = {"operation": "promote", "entity_id": row["entity_id"]}
    elif row["kind"] == "relation":
        payload = {
            "operation": "promote",
            "relation_id": row["relation_id"],
            "source_ref": row["baseline"]["source_id"],
            "target_ref": row["baseline"]["target_id"],
            "relation_type": fields["relation_type"],
            "relation_kind": fields["relation_kind"],
            "description": fields["description"],
        }
    else:
        payload = {
            "entity_ref": row["entity_id"],
            "alias": fields["alias"],
            "alias_type": fields["type"],
            "alias_kind": fields["kind"] or "name",
        }
    item = {
        "item_key": row["key"],
        "kind": kind,
        "payload": payload,
        "disposition": "include",
        "authority_kind": "manuscript_observation",
        "source_refs": refs,
        "root_key": f"entity:{row['entity_id']}",
        "depth": 0,
        "review_evidence": {
            field: [ref.quote for ref in refs]
            for field, refs in judgment.field_evidence.items()
        },
    }
    if row["kind"] == "entity":
        item["baseline"] = {"expected_status": "candidate"}
    return item


async def run_resolution(db, *, task, progress, checkpoint, project_settings):
    from core.errors import DomainError
    from modules.evidence.facade import read_review_resolution_sources
    from modules.project.facade import create_project_snapshot_llm_client
    from modules.world.contracts import (
        FocusedWorldPackageApplyRequest,
        FocusedWorldPackageRequest,
    )
    from modules.world.facade import (
        apply_focused_world_package,
        list_review_resolution_candidates,
        submit_focused_world_package,
    )

    permission = progress.authorization_snapshot.get("review_resolution") or {}
    bound = progress.checkpoints.get("review_resolution_permission")
    if bound:
        if bound.get("parent_scope_hash") != stable_hash(permission):
            raise ValueError("整理的原授权范围已变化")
        permission = bound
    if permission.get("version") != VERSION:
        raise ValueError("智能整理缺少原授权快照")
    if permission.get("prompt_manifest") != prompt_manifest():
        raise ValueError("整理提示词或输出契约已更新，请新建整理任务")
    if permission.get("items") and not permission.get("authorization_id"):
        raise ValueError("智能整理缺少领域采用授权")
    state = progress.checkpoints.setdefault(
        "review_resolution",
        {
            "version": VERSION,
            "groups": [],
            "position": 0,
            "outcomes": {},
            "packages": [],
            "requests": 0,
        },
    )
    if state["version"] != VERSION or state.get("rollback_started"):
        raise ValueError("此整理记录不可继续，请开始新任务")
    if not state["groups"]:
        by_scene = {}
        for row in permission["items"]:
            by_scene.setdefault(str(row["meta"].get("scene_id") or "missing"), []).append(
                row["key"]
            )
        state["groups"] = [
            {"scene_id": scene, "keys": keys[i : i + 32], "requests": 0}
            for scene, keys in by_scene.items()
            for i in range(0, len(keys), 32)
        ]
        state["request_limit"] = (
            len(state["groups"]) * MAX_GROUP_REQUESTS
            + len(permission.get("scene_items", [])) * 2
        )
    incomplete = {
        key for key, item in state["outcomes"].items() if item["outcome"] == "incomplete"
    }
    if incomplete:
        state["position"] = min(
            i
            for i, group in enumerate(state["groups"])
            if incomplete.intersection(group["keys"])
        )
        state["outcomes"] = {
            key: item for key, item in state["outcomes"].items() if key not in incomplete
        }
    frozen = {row["key"]: row for row in permission["items"]}

    async def save():
        counts = dict(Counter(item["outcome"] for item in state["outcomes"].values()))
        progress.review_resolution = {
            "version": VERSION,
            "counts": counts,
            "fact_count": len(frozen),
            "processed_count": len(state["outcomes"]),
            "question_count": len(
                {
                    item["group_key"]
                    for item in state["outcomes"].values()
                    if item["outcome"] == "decision"
                }
            ),
            "groups": list(state["outcomes"].values()),
            "requests": state["requests"],
            "request_limit": state["request_limit"],
            "qualification_profile": state.get("qualification_profile", {}),
            "packages": state["packages"],
            "scene_results": list(state.get("scene_results", {}).values()),
            "scene_counts": dict(
                Counter(
                    item["outcome"] for item in state.get("scene_results", {}).values()
                )
            ),
        }
        progress.message = "正在核对导入资料，可离开后继续查看"
        await checkpoint(
            progress, min(0.99, state["position"] / max(1, len(state["groups"])))
        )

    await save()
    client = create_project_snapshot_llm_client(
        project_settings, novel_id=task.meta["novel_id"], timeout_override=540
    )
    from infrastructure.llm.agent_step_harness import build_managed_llm_provenance

    qualification_profile = build_managed_llm_provenance(
        client,
        step_name="imports.review_resolution.qualification",
        novel_id=task.meta["novel_id"],
    )
    state["qualification_profile"] = {
        "prompt_hash": permission["prompt_manifest"],
        "profile_hash": qualification_profile["profile_hash"],
        "model": str(getattr(client, "model_name", "")),
    }
    try:
        if permission.get("repair_scenes"):
            await resolve_scene_boundaries(
                db,
                task=task,
                progress=progress,
                permission=permission,
                client=client,
                state=state,
                save=save,
            )
        for index in range(state["position"], len(state["groups"])):
            group = state["groups"][index]
            rows = [frozen[key] for key in group["keys"]]
            from modules.world.facade import resolve_redundant_review_alias

            for row in rows:
                if row["kind"] != "alias" or row["key"] in state["outcomes"]:
                    continue
                if (
                    row["fields"]["alias"].strip().casefold()
                    != row["identities"][0]["name"].strip().casefold()
                ):
                    continue
                request = FocusedWorldPackageRequest(
                    novel_id=task.meta["novel_id"],
                    authorization_id=permission["authorization_id"],
                    task_id=str(task.id),
                    task_type=str(task.task_type),
                    attempt=int(task.attempt),
                    lease_id=str(task.lease_id),
                    items=[],
                    source_manifest_hash=stable_hash(permission["source_manifest"]),
                    context_fingerprint=row["fingerprint"],
                )
                receipt = await resolve_redundant_review_alias(
                    db, request=request, candidate_key=row["key"]
                )
                if receipt:
                    state["packages"].append({**receipt, "key": row["key"]})
                    state["outcomes"][row["key"]] = {
                        "key": row["key"],
                        "kind": "alias",
                        "outcome": "organized",
                        "reason": "same_as_canonical_name",
                        "label": row["fields"]["alias"],
                        "explanation": "与对象正式名称相同，已保留来源并消解重复称呼。",
                        "group_key": row["key"],
                        "fingerprint": row["fingerprint"],
                    }
                    await save()
            rows = [
                row
                for row in rows
                if row["key"] not in state["outcomes"]
                or state["outcomes"][row["key"]]["outcome"] != "organized"
            ]
            if not rows:
                state["position"] = index + 1
                await save()
                continue
            try:
                evidence = await read_review_resolution_sources(
                    db,
                    novel_id=task.meta["novel_id"],
                    scene_id=group["scene_id"],
                    source_manifest=permission["source_manifest"],
                    chapter_from=permission["chapter_from"],
                    chapter_to=permission["chapter_to"],
                )
                origin_last_chapter = max(
                    item["source_ref"]["chapter_index"] for item in evidence
                )
                fingerprint = stable_hash(evidence)
                if group.get("evidence_fingerprint") not in (None, fingerprint):
                    raise ValueError("原文已变化，旧判断不可继续")
                group["evidence_fingerprint"] = fingerprint
                output = (
                    ReviewJudgments.model_validate(group["judgment"])
                    if group.get("judgment")
                    else None
                )
                if output is None:
                    output = await initial_group_judgment(
                        db,
                        task=task,
                        client=client,
                        rows=rows,
                        evidence=evidence,
                        group=group,
                        state=state,
                        save=save,
                    )
                    group["judgment"] = output.model_dump(mode="json")
                    await save()
                questions = group.get("questions") or list(
                    dict.fromkeys(
                        q for item in output.judgments for q in item.missing_evidence
                    )
                )
                group["questions"] = questions
                if questions and (
                    group["requests"] < MAX_GROUP_REQUESTS
                    or group.get("supplemental_hash")
                ):
                    extra = await supplement_evidence(
                        db,
                        novel_id=task.meta["novel_id"],
                        rows=rows,
                        permission=permission,
                        questions=questions,
                    )
                    fresh = [item for item in extra if is_new_source(item, evidence)]
                    if fresh:
                        evidence = [*evidence, *fresh]
                        supplemental_hash = stable_hash(fresh)
                        if group.get("supplemental_hash") not in (
                            None,
                            supplemental_hash,
                        ):
                            raise ValueError("补查来源已变化，请重新整理")
                        group["supplemental_hash"] = supplemental_hash
                        for stage in (
                            () if group.get("revision_checked") else ("revise", "verify")
                        ):
                            if group.get(f"{stage}_judgment"):
                                output = ReviewJudgments.model_validate(
                                    group[f"{stage}_judgment"]
                                )
                                continue
                            if group["requests"] >= MAX_GROUP_REQUESTS:
                                raise ValueError("本组返修额度已用完")
                            group["requests"] += 1
                            state["requests"] += 1
                            await save()
                            output = await audited_judgment(
                                db,
                                task=task,
                                client=client,
                                rows=rows,
                                evidence=evidence,
                                stage=stage,
                                save=save,
                                previous=output.model_dump(mode="json"),
                            )
                            group[f"{stage}_judgment"] = output.model_dump(mode="json")
                            await save()
                    group["revision_checked"] = True
                    group["judgment"] = output.model_dump(mode="json")
                    await save()
                approved_groups = validated_problem_groups(output, rows)
                for judgment in output.judgments:
                    row = frozen[judgment.candidate_key]
                    if (
                        state["outcomes"].get(row["key"], {}).get("outcome")
                        == "organized"
                    ):
                        continue
                    selected, valid = evidence_for_judgment(judgment, evidence)
                    outcome, reason = judgment_outcome(
                        judgment,
                        required_fields=set(row["required_fields"]),
                        valid_evidence=valid,
                    )
                    if row["protected"]:
                        outcome, reason = "decision", "author_edited"
                    if outcome == "eligible" and any(
                        ref["chapter_index"] > origin_last_chapter
                        for ref, _quote in selected
                    ):
                        outcome, reason = "decision", "later_evidence_requires_visibility"

                    result = {
                        "key": row["key"],
                        "kind": row["kind"],
                        "outcome": outcome,
                        "reason": reason,
                        "explanation": judgment.explanation,
                        "question": judgment.question,
                        "group_key": stable_hash(
                            {
                                "scene": group["scene_id"],
                                "identities": [item["id"] for item in row["identities"]],
                                "reason": reason,
                            }
                        ),
                        "fingerprint": row["fingerprint"],
                    }
                    result["label"] = "、".join(
                        item["name"] for item in row["identities"]
                    )
                    result["proposed_fields"] = row["fields"]
                    result["evidence"] = [
                        {"source_ref": ref, "quote": quote} for ref, quote in selected
                    ]
                    if outcome == "decision" and row["key"] in approved_groups:
                        group_info = approved_groups[row["key"]]
                        result.update(
                            group_key=group_info["key"], question=group_info["question"]
                        )
                    if outcome == "eligible":
                        # Admission requires held-out human qualification per category.
                        from modules.imports.review_resolution_quality import qualified

                        if not qualified(
                            row["kind"],
                            prompt_hash=permission["prompt_manifest"],
                            profile_hash=qualification_profile["profile_hash"],
                            model=str(getattr(client, "model_name", "")),
                        ):
                            result.update(
                                outcome="optional", reason="quality_not_qualified"
                            )
                        else:
                            current = await list_review_resolution_candidates(
                                db, task.meta["novel_id"], keys={row["key"]}
                            )
                            if (
                                not current
                                or current[0]["fingerprint"] != row["fingerprint"]
                            ):
                                raise ValueError("候选已变化，需要重新整理")
                            request = FocusedWorldPackageRequest(
                                novel_id=task.meta["novel_id"],
                                authorization_id=permission["authorization_id"],
                                task_id=str(task.id),
                                task_type=str(task.task_type),
                                attempt=int(task.attempt),
                                lease_id=str(task.lease_id),
                                items=[
                                    package_item(row, judgment, selected, str(task.id))
                                ],
                                source_manifest_hash=stable_hash(
                                    permission["source_manifest"]
                                ),
                                context_fingerprint=fingerprint,
                            )
                            package = await submit_focused_world_package(db, request)
                            await save()
                            if package["included_count"] != 1:
                                result.update(
                                    outcome="decision", reason="domain_review_required"
                                )
                            else:
                                receipt = await apply_focused_world_package(
                                    db,
                                    FocusedWorldPackageApplyRequest(
                                        novel_id=request.novel_id,
                                        authorization_id=request.authorization_id,
                                        task_id=request.task_id,
                                        task_type=request.task_type,
                                        attempt=request.attempt,
                                        lease_id=request.lease_id,
                                        suggestion_id=package["suggestion_id"],
                                        expected_preview_hash=package[
                                            "expected_preview_hash"
                                        ],
                                    ),
                                )
                                state["packages"].append(
                                    {
                                        "suggestion_id": package["suggestion_id"],
                                        "status": "accepted",
                                        "key": row["key"],
                                    }
                                )
                                result.update(outcome="organized", receipt=receipt)
                    state["outcomes"][row["key"]] = result
                    await save()
            except (ValueError, DomainError, TimeoutError, LLMError) as exc:
                from infrastructure.llm.redaction import redact_diagnostic

                for row in rows:
                    if row["key"] not in state["outcomes"]:
                        state["outcomes"][row["key"]] = {
                            "key": row["key"],
                            "kind": row["kind"],
                            "outcome": "incomplete",
                            "reason": redact_diagnostic(exc, limit=200),
                            "group_key": group["scene_id"],
                            "fingerprint": row["fingerprint"],
                            "label": "、".join(
                                identity["name"] for identity in row["identities"]
                            ),
                        }
            state["position"] = index + 1
            await save()
    finally:
        await client.close()
    progress.phase = "done"
    progress.current_step = None
    progress.quality_status = (
        "partial"
        if any(
            item["outcome"] == "incomplete"
            for item in [
                *state["outcomes"].values(),
                *state.get("scene_results", {}).values(),
            ]
        )
        else "complete"
    )
    await save()
    progress.message = "资料整理完成；需要决定、可选建议和未完成项已分别保留"
    if progress.quality_status == "partial":
        from modules.imports.orchestrator import DeepImportWorkflowFailedError

        progress.phase = "failed"
        progress.recovery_required = True
        await checkpoint(progress, 0.99)
        raise DeepImportWorkflowFailedError("部分资料尚未查证完成，可继续整理")
    await checkpoint(progress, 1.0)


async def rollback_resolution(db, *, novel_id, task_id, release_run=True):
    from modules.imports.workflow_runs import ImportWorkflowRunService
    from modules.project.facade import require_active_project_exclusive
    from modules.world.facade import rollback_focused_world_package

    await require_active_project_exclusive(db, novel_id)
    run = await ImportWorkflowRunService().get_by_task(db, task_id=task_id)
    if (
        run is None
        or str(run.novel_id) != str(parse_uuid(novel_id))
        or not run.authorization_snapshot.get("review_resolution")
    ):
        raise ValueError("整理记录不存在")
    if run.status in {"pending", "running"}:
        raise ConflictError("请先停止整理，再撤销已保存结果")
    state = dict((run.checkpoints or {}).get("review_resolution") or {})
    state["rollback_started"] = True
    receipts = []
    for package in reversed(state.get("packages", [])):
        receipts.append(
            await rollback_focused_world_package(
                db, novel_id=novel_id, suggestion_id=package["suggestion_id"]
            )
        )
    from modules.story.facade import rollback_import_scene_resolution

    scene_undo = []
    world_conflict = any(
        item.get("status") == "conflict"
        for receipt in receipts
        for item in receipt.get("results", [])
    )
    for receipt in reversed(list(state.get("scene_results", {}).values())):
        if world_conflict and (receipt.get("members") or receipt.get("after")):
            scene_undo.append("conflict")
            continue
        scene_undo.append(
            await rollback_import_scene_resolution(db, novel_id=novel_id, receipt=receipt)
        )
    state["scene_rollback"] = scene_undo
    state["rollback_receipts"] = receipts
    run.checkpoints = {**run.checkpoints, "review_resolution": state}
    conflicts = sum(
        item.get("status") == "conflict"
        for receipt in receipts
        for item in receipt.get("results", [])
    )
    conflicts += scene_undo.count("conflict")
    result = {
        "status": "partial" if conflicts else "complete",
        "conflicts": conflicts,
        "receipts": receipts,
    }
    run.progress = {
        **run.progress,
        "review_resolution": {
            **run.progress.get("review_resolution", {}),
            "rollback": result,
        },
    }
    from infrastructure.tasks.facade import update_task_projection

    if release_run:
        run.recovery_required = False
        run.progress = {**run.progress, "recovery_required": False, "recoverable": False}
    run.progress = {**run.progress, "checkpoints": run.checkpoints}
    await update_task_projection(
        db,
        task_id=task_id,
        task_type=run.workflow_type,
        novel_id=novel_id,
        result=run.progress,
        meta_patch={"recovery_required": False} if release_run else {},
    )
    await db.flush()
    return result


async def freeze_future_resolution(db, *, novel_id, start_chapter, end_chapter, options):
    from modules.imports.review_resolution_schemas import ReviewResolutionOptions
    from modules.writing.facade import list_latest_drafts_for_chapters

    parsed = ReviewResolutionOptions.model_validate(options or {})
    if not parsed.enabled:
        return None
    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, list(range(start_chapter, end_chapter + 1)), content_limit=1
    )
    manifest = {str(draft.id): draft.content_hash for draft in drafts}
    if not manifest or any(not value for value in manifest.values()):
        raise ValueError("智能整理需要可验证正文")
    return {
        "version": VERSION,
        "origin": "workflow_candidates",
        "prompt_manifest": prompt_manifest(),
        "chapter_from": start_chapter,
        "chapter_to": end_chapter,
        "source_manifest": manifest,
        "repair_scenes": parsed.repair_scenes,
        "items": [],
    }


async def resolve_import_candidates(db, *, task, progress, checkpoint, project_settings):
    permission = progress.authorization_snapshot.get("review_resolution") or {}
    if not permission:
        return
    if (
        permission.get("origin") != "workflow_candidates"
        or permission.get("version") != VERSION
    ):
        raise ValueError("本次导入没有自动整理新候选的授权")
    if "review_resolution_permission" not in progress.checkpoints:
        from modules.world.facade import list_review_resolution_candidates

        items = await list_review_resolution_candidates(
            db, task.meta["novel_id"], workflow_id=str(task.id)
        )
        from modules.story.facade import preview_import_scene_resolution

        scene_items = (
            await preview_import_scene_resolution(
                db,
                task.meta["novel_id"],
                permission["chapter_from"],
                permission["chapter_to"],
            )
            if permission.get("repair_scenes")
            else []
        )
        scene_items = [
            scene
            for scene in scene_items
            if scene["meta"].get("workflow_id") == str(task.id)
        ]
        bound = await authorize_resolution(
            db,
            novel_id=task.meta["novel_id"],
            task_id=str(task.id),
            permission={**permission, "items": items, "scene_items": scene_items},
        )
        progress.checkpoints["review_resolution_permission"] = {
            **bound,
            "parent_scope_hash": stable_hash(permission),
        }
        await checkpoint(progress, 0.8)
    phase, step = progress.phase, progress.current_step

    async def update(updated, value):
        updated.phase = phase
        updated.current_step = step
        await checkpoint(updated, 0.8 + value * 0.03)

    from modules.imports.orchestrator import DeepImportWorkflowFailedError

    try:
        await run_resolution(
            db,
            task=task,
            progress=progress,
            checkpoint=update,
            project_settings=project_settings,
        )
    except DeepImportWorkflowFailedError:
        progress.degraded = True
        progress.quality_status = "partial"
        progress.recovery_required = False
        progress.phase_artifacts["review_resolution"] = {
            "status": "partial",
            "message": "部分资料仍需处理，其他导入步骤继续",
        }
    finally:
        progress.phase, progress.current_step = phase, step


async def supplement_evidence(db, *, novel_id, rows, permission, questions):
    from modules.evidence.contracts import (
        CompileOptions,
        FocusedEvidenceLimits,
        FocusedEvidenceRequest,
        FocusedEvidenceRoot,
    )
    from modules.evidence.facade import retrieve_focused_evidence

    roots = {
        identity["id"]: FocusedEvidenceRoot(
            key=f"entity:{identity['id']}",
            target_ref={"target_type": "entity", "target_id": identity["id"]},
        )
        for row in rows
        for identity in row["identities"]
    }
    request = FocusedEvidenceRequest(
        novel_id=novel_id,
        roots=list(roots.values()),
        question="核对支持与反证：" + "；".join(questions)[:1900],
        chapter_from=permission["chapter_from"],
        chapter_to=permission["chapter_to"],
        max_depth=0,
        sources=["manuscript"],
        limits=FocusedEvidenceLimits(chapters_per_batch=100, characters_per_batch=100000),
        compile_options=CompileOptions(
            novel_id=novel_id,
            task="核对候选事实与反证",
            scope="full",
            consumer_action="imports.review_resolution",
            context_mode="working",
            content_mode="working",
            include_pending_objects=True,
            reveal_mode="author_full",
            source_manifest=permission["source_manifest"],
        ),
    )
    evidence = []
    while True:
        result = await retrieve_focused_evidence(db, request)
        if result.blockers:
            raise ValueError("来源检索无法完整验证")
        for item in result.evidence:
            if item.source_ref is not None:
                evidence.append(
                    {
                        "key": item.key,
                        "text": item.text,
                        "source_ref": item.source_ref.__dict__,
                    }
                )
        if sum(len(item["text"]) for item in evidence) > 100000:
            raise ValueError("补查资料超过本组预算，需拆分范围")
        if result.continuation is None:
            return evidence
        request = request.model_copy(update={"continuation": result.continuation})


async def audited_judgment(
    db, *, task, client, rows, evidence, stage, save, previous=None
):
    from infrastructure.llm.redaction import redact_diagnostic
    from modules.evidence.contracts import ContextSnapshotRequest
    from modules.evidence.facade import (
        fail_context_snapshot,
        open_context_snapshot,
        succeed_context_snapshot,
    )

    snapshot = await open_context_snapshot(
        db,
        ContextSnapshotRequest(
            novel_id=task.meta["novel_id"],
            task_id=str(task.id),
            workflow_id=str(task.id),
            phase="review_resolution",
            operation=stage,
            prompt_name="review_resolution",
            model=client.model_name,
            compile_options={"stage": stage},
            included_asset_ids={"candidate_keys": [row["key"] for row in rows]},
            context_summary={
                "input_fingerprint": stable_hash(
                    {"rows": rows, "evidence": evidence, "previous": previous}
                )
            },
            section_metadata={
                "sources": [
                    {k: v for k, v in item.items() if k != "text"} for item in evidence
                ]
            },
            token_metadata={
                "max_tokens": 32768,
                "max_input_chars": 100000,
                "timeout_seconds": 600,
            },
            attempt=int(task.attempt),
        ),
    )
    await save()
    try:
        result = await judge(
            client, rows=rows, evidence=evidence, stage=stage, previous=previous
        )
    except Exception as exc:
        await fail_context_snapshot(
            db,
            novel_id=task.meta["novel_id"],
            snapshot_id=snapshot.id,
            error_kind=type(exc).__name__,
            error_message=redact_diagnostic(exc, limit=200),
        )
        await save()
        raise
    await succeed_context_snapshot(
        db,
        novel_id=task.meta["novel_id"],
        snapshot_id=snapshot.id,
        result_refs=[
            {
                "candidate_key": item.candidate_key,
                "judgment_hash": stable_hash(item.model_dump(mode="json")),
            }
            for item in result.judgments
        ],
    )
    return result


async def resolve_scene_boundaries(
    db, *, task, progress, permission, client, state, save
):
    from core.errors import DomainError
    from modules.evidence.facade import read_review_resolution_chapters
    from modules.story.contracts import SceneBoundaryReview
    from modules.story.facade import (
        apply_import_scene_resolution_group,
        group_import_scene_resolution,
    )

    results = state.setdefault("scene_results", {})
    for omission in permission.get("scope_omissions", []):
        key = "scope-" + omission["scene_id"]
        results[key] = {
            "group_key": key,
            "scene_id": omission["scene_id"],
            "label": omission["title"],
            "outcome": "incomplete",
            "explanation": (
                f"需包含第 {omission['chapter_from']}"
                f"～{omission['chapter_to']} 章才能核对该跨章场景，"
                "当前没有扩大授权。"
            ),
        }
    groups = await group_import_scene_resolution(permission.get("scene_items", []))
    for frozen in groups:
        key = frozen["group_key"]
        if len(frozen["members"]) > 32:
            results[key] = {
                "scene_id": frozen["scene_id"],
                "group_key": key,
                "outcome": "incomplete",
                "explanation": "本组关联场景过多，请在场景工作台进一步整理。",
            }
            continue
        previous = results.get(key, {})
        if previous.get("outcome") in {"organized", "decision"}:
            continue
        try:
            evidence = await read_review_resolution_chapters(
                db,
                novel_id=task.meta["novel_id"],
                chapters=frozen["chapters"],
                source_manifest=permission["source_manifest"],
            )
            input_hash = stable_hash({"scene": frozen, "evidence": evidence})
            if previous.get("input_hash") not in (None, input_hash):
                raise ValueError("修复来源已变化")
            for stage in ("repair", "verify"):
                if previous.get(stage):
                    continue
                if previous.get("requests", 0) >= 2:
                    raise ValueError("本组场景核对额度已用完")
                previous.update(
                    requests=previous.get("requests", 0) + 1,
                    input_hash=input_hash,
                    outcome="running",
                )
                state["requests"] += 1
                results[key] = previous
                await save()
                output = await audited_scene_judgment(
                    db,
                    task=task,
                    client=client,
                    frozen=frozen,
                    evidence=evidence,
                    stage=stage,
                    previous=previous.get("repair"),
                    save=save,
                )
                previous[stage] = output.model_dump(mode="json")
                await save()
            judgments = SceneBoundaryReview.model_validate(previous["verify"]).scenes
            receipt = await apply_import_scene_resolution_group(
                db,
                novel_id=task.meta["novel_id"],
                frozen=frozen,
                judgments=judgments,
                evidence=evidence,
                workflow_id=str(task.id),
            )
            results[key] = {**previous, **receipt, "label": frozen["title"]}
        except (ValueError, DomainError, TimeoutError, LLMError) as exc:
            from infrastructure.llm.redaction import redact_diagnostic

            results[key] = {
                **previous,
                "scene_id": frozen["scene_id"],
                "group_key": key,
                "fingerprint": frozen["fingerprint"],
                "outcome": "incomplete",
                "explanation": redact_diagnostic(exc, limit=200),
                "label": frozen["title"],
            }
        await save()


async def audited_scene_judgment(
    db, *, task, client, frozen, evidence, stage, previous, save
):
    from infrastructure.llm.agent_step_harness import (
        ContextBudget,
        run_managed_structured,
    )
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.redaction import redact_diagnostic
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
    from modules.evidence.contracts import ContextSnapshotRequest
    from modules.evidence.facade import (
        fail_context_snapshot,
        open_context_snapshot,
        succeed_context_snapshot,
    )
    from modules.story.contracts import SceneBoundaryReview

    payload = {
        "scenes": frozen["members"],
        "evidence": evidence,
        "stage": stage,
        "draft": previous,
    }
    snapshot = await open_context_snapshot(
        db,
        ContextSnapshotRequest(
            novel_id=task.meta["novel_id"],
            task_id=str(task.id),
            workflow_id=str(task.id),
            phase="review_resolution",
            operation=f"scene_{stage}",
            prompt_name="review_resolution_scenes",
            model=client.model_name,
            compile_options={"chapters": frozen["chapters"]},
            included_asset_ids={
                "scene_ids": [item["scene_id"] for item in frozen["members"]]
            },
            context_summary={"input_hash": stable_hash(payload)},
            section_metadata={"source_refs": [item["source_ref"] for item in evidence]},
            token_metadata={"max_tokens": 32768, "max_input_chars": 100000},
        ),
    )
    await save()
    try:
        result = await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
                max_tokens=32768,
                response_format={"type": "json_object"},
                messages=[
                    LLMMessage(
                        role="system",
                        content=load_prompt("review_resolution_scenes")
                        + "\nverify阶段是独立终检，只保留原文支持的结论。\n"
                        + json.dumps(
                            SceneBoundaryReview.model_json_schema(), ensure_ascii=False
                        ),
                    ),
                    LLMMessage(
                        role="user", content=json.dumps(payload, ensure_ascii=False)
                    ),
                ],
            ),
            SceneBoundaryReview,
            step_name=f"imports.review_resolution.scene_{stage}",
            max_fix_attempts=0,
            transport_retries=False,
            timeout=600,
            context_budget=ContextBudget(max_input_chars=100000, max_output_chars=80000),
        )
        if len(result.scenes) != len(frozen["members"]) or {
            item.scene_id for item in result.scenes
        } != {item["scene_id"] for item in frozen["members"]}:
            raise ValueError("场景核对结果超出范围")
    except Exception as exc:
        await fail_context_snapshot(
            db,
            novel_id=task.meta["novel_id"],
            snapshot_id=snapshot.id,
            error_kind=type(exc).__name__,
            error_message=redact_diagnostic(exc, limit=200),
        )
        await save()
        raise
    await succeed_context_snapshot(
        db,
        novel_id=task.meta["novel_id"],
        snapshot_id=snapshot.id,
        result_refs=[
            {
                "scene_id": frozen["scene_id"],
                "judgment_hash": stable_hash(result.model_dump(mode="json")),
            }
        ],
    )
    return result


def validated_problem_groups(output, rows):
    """The model may group a shared identity question, never unrelated facts."""
    by_key = {row["key"]: row for row in rows}
    judgments = {item.candidate_key: item for item in output.judgments}
    grouped = {}
    for proposed in output.groups:
        keys = proposed.candidate_keys
        if len(set(keys)) != len(keys) or any(
            key not in by_key or key in grouped for key in keys
        ):
            continue
        signatures = {
            tuple(identity["id"] for identity in by_key[key]["identities"])
            for key in keys
        }
        if len(signatures) != 1 or any(
            judgments[key].identity not in {"ambiguous", "secret"} for key in keys
        ):
            continue
        entry = {
            "key": stable_hash(
                {"members": sorted(keys), "identities": sorted(signatures)}
            ),
            "question": proposed.question,
        }
        grouped.update({key: entry for key in keys})
    return grouped


async def accept_decision(db, *, novel_id, task_id, data):
    from core.errors import DomainError
    from modules.imports.workflow_runs import ImportWorkflowRunService
    from modules.world.facade import (
        apply_review_resolution_decision,
        prepare_review_resolution_decision,
    )

    run = await ImportWorkflowRunService().get_by_task(db, task_id=task_id)
    if run is None or str(run.novel_id) != str(parse_uuid(novel_id)):
        raise ValueError("整理记录不存在")
    if run.status in {"pending", "running"}:
        raise ConflictError("请等待当前整理停止后再决定")
    await inspect_resolution(db, novel_id=novel_id, task_id=task_id)

    permission = (
        (run.checkpoints or {}).get("review_resolution_permission")
        or (run.authorization_snapshot or {}).get("review_resolution")
        or {}
    )
    state = dict((run.checkpoints or {}).get("review_resolution") or {})
    rows = {row["key"]: row for row in permission.get("items", [])}
    keys = data.candidate_keys
    if (
        len(set(keys)) != len(keys)
        or set(keys) != set(data.expected_fingerprints)
        or any(
            key not in rows or rows[key]["fingerprint"] != data.expected_fingerprints[key]
            for key in keys
        )
    ):
        raise ConflictError("本次选择不属于原整理结果")
    if state.get("rollback_started"):
        raise ConflictError("本次整理已撤销，请重新整理后决定")
    decision_key = stable_hash(
        {"keys": sorted(keys), "fingerprints": data.expected_fingerprints}
    )
    decisions = state.setdefault("manual_decisions", {})
    if decisions.get(decision_key, {}).get("status") == "accepted":
        return decisions[decision_key]
    package = decisions.get(decision_key) or await prepare_review_resolution_decision(
        db, novel_id=novel_id, task_id=task_id, rows=[rows[key] for key in keys]
    )
    try:
        async with db.begin_nested():
            receipt = await apply_review_resolution_decision(
                db, novel_id=novel_id, package=package
            )
        package = {**package, "status": "accepted", "receipt": receipt}
        for key in keys:
            state["outcomes"][key] = {
                **state["outcomes"].get(key, {}),
                "outcome": "organized",
                "reason": "author_decision",
            }
        state.setdefault("packages", []).append(
            {
                "suggestion_id": package["suggestion_id"],
                "status": "accepted",
                "keys": keys,
            }
        )
    except DomainError as exc:
        package = {
            **package,
            "status": "requires_review",
            "message": getattr(exc, "message", str(exc)),
        }
    decisions[decision_key] = package
    run.checkpoints = {**run.checkpoints, "review_resolution": state}
    summary = {
        **run.progress.get("review_resolution", {}),
        "counts": dict(Counter(item["outcome"] for item in state["outcomes"].values())),
        "groups": list(state["outcomes"].values()),
        "question_count": len(
            {
                item["group_key"]
                for item in state["outcomes"].values()
                if item["outcome"] == "decision"
            }
        ),
        "packages": state.get("packages", []),
    }
    run.progress = {**run.progress, "review_resolution": summary}
    from infrastructure.tasks.facade import update_task_projection

    await update_task_projection(
        db,
        task_id=task_id,
        task_type=run.workflow_type,
        novel_id=novel_id,
        result=run.progress,
    )
    await db.flush()
    return package


async def latest_resolution(db, novel_id):
    from sqlalchemy import select

    from modules.imports.models import ImportWorkflowRun
    from shared.utils import parse_uuid

    run = await db.scalar(
        select(ImportWorkflowRun)
        .where(
            ImportWorkflowRun.novel_id == parse_uuid(novel_id),
            ImportWorkflowRun.workflow_type == "import_review_resolution",
        )
        .order_by(ImportWorkflowRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return None
    return {
        "task_id": str(run.task_id),
        "status": run.status,
        "result": run.progress.get("review_resolution", {}),
    }


async def inspect_resolution(db, *, novel_id, task_id, cutoff_chapter=None):
    from modules.imports.workflow_runs import ImportWorkflowRunService

    run = await ImportWorkflowRunService().get_by_task(db, task_id=task_id)
    if run is None or str(run.novel_id) != str(parse_uuid(novel_id)):
        raise ValueError("整理记录不存在")
    if cutoff_chapter is not None and run.end_chapter > cutoff_chapter:
        return {"omission": "该整理范围超出当前章节，请在原范围查看"}
    from modules.writing.facade import list_latest_drafts_for_chapters

    permission = (
        (run.checkpoints or {}).get("review_resolution_permission")
        or (run.authorization_snapshot or {}).get("review_resolution")
        or {}
    )
    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, list(range(run.start_chapter, run.end_chapter + 1)), content_limit=1
    )
    manifest = {str(draft.id): draft.content_hash for draft in drafts}
    if permission.get("source_manifest") != manifest:
        raise ConflictError("正文来源已变化，请重新整理后决定")
    from modules.world.facade import list_review_resolution_candidates

    current = {
        row["key"]: row["fingerprint"]
        for row in await list_review_resolution_candidates(db, novel_id)
    }
    summary = dict(run.progress.get("review_resolution") or {})
    summary["groups"] = [
        item
        for item in summary.get("groups", [])
        if item.get("fingerprint") == current.get(item.get("key"))
    ]
    return {
        "task_id": task_id,
        "status": run.status,
        "chapter_from": run.start_chapter,
        "chapter_to": run.end_chapter,
        "summary": summary,
        "coverage": "仅为本次整理结果，候选建议不代表已采用事实",
    }


def prompt_manifest():
    from infrastructure.llm.prompt_loader import load_prompt
    from modules.story.contracts import SceneBoundaryReview

    return stable_hash(
        {
            "prompts": {
                name: load_prompt(name)
                for name in (
                    "review_resolution",
                    "review_resolution_groups",
                    "review_resolution_scenes",
                )
            },
            "judgments": ReviewJudgments.model_json_schema(),
            "scenes": SceneBoundaryReview.model_json_schema(),
            "requests_per_group": MAX_GROUP_REQUESTS,
            "scene_group_execution_version": 2,
        }
    )


async def initial_group_judgment(db, *, task, client, rows, evidence, group, state, save):
    """One schema repair consumes the same three-call budget as semantic repair."""
    from infrastructure.llm.errors import LLMInvalidResponseError

    async def call(stage, previous=None):
        if group["requests"] >= MAX_GROUP_REQUESTS:
            raise ValueError("本组查证额度已用完")
        group["requests"] += 1
        state["requests"] += 1
        await save()
        return await audited_judgment(
            db,
            task=task,
            client=client,
            rows=rows,
            evidence=evidence,
            stage=stage,
            previous=previous,
            save=save,
        )

    if not group.get("format_failure"):
        try:
            return await call("review")
        except LLMInvalidResponseError:
            group["format_failure"] = {
                "error_kind": "invalid_structured_output",
                "instruction": "修正输出格式与枚举；只返回原候选及原证据支持的结论。",
            }
            await save()
    for stage in ("revise", "verify"):
        key = f"{stage}_judgment"
        if group.get(key):
            continue
        previous = (
            group.get("revise_judgment") if stage == "verify" else group["format_failure"]
        )
        output = await call(stage, previous)
        group[key] = output.model_dump(mode="json")
        await save()
    group["revision_checked"] = True
    return ReviewJudgments.model_validate(group["verify_judgment"])


async def accept_scene_group(db, *, novel_id, task_id, group_key, data):
    from infrastructure.tasks.facade import update_task_projection
    from modules.evidence.facade import read_review_resolution_chapters
    from modules.imports.workflow_runs import ImportWorkflowRunService
    from modules.project.facade import require_active_project_exclusive
    from modules.story.contracts import SceneBoundaryReview
    from modules.story.facade import (
        apply_import_scene_resolution_group,
        group_import_scene_resolution,
    )

    await require_active_project_exclusive(db, novel_id)
    run = await ImportWorkflowRunService().get_by_task(db, task_id=task_id)
    if run is None or str(run.novel_id) != str(parse_uuid(novel_id)):
        raise ConflictError("整理记录不存在")
    if run.status in {"pending", "running"}:
        raise ConflictError("请等待当前整理结束后确认")
    permission = (
        (run.checkpoints or {}).get("review_resolution_permission")
        or (run.authorization_snapshot or {}).get("review_resolution")
        or {}
    )
    if permission.get("prompt_manifest") != prompt_manifest():
        raise ConflictError("核对规则已更新，请重新整理")
    state = dict((run.checkpoints or {}).get("review_resolution") or {})
    if state.get("rollback_started"):
        raise ConflictError("本次整理已经撤销")
    record = state.get("scene_results", {}).get(group_key)
    if not record or record.get("fingerprint") != data.expected_fingerprint:
        raise ConflictError("场景提案已变化，请重新查看")
    if record.get("author_confirmed"):
        return {"task_id": task_id, "status": "accepted", "scene": record}
    if not record.get("can_apply") or not record.get("verify"):
        raise ConflictError("此项需要在场景工作台继续处理")
    groups = await group_import_scene_resolution(permission.get("scene_items", []))
    frozen = next((group for group in groups if group["group_key"] == group_key), None)
    if frozen is None:
        raise ConflictError("场景不属于原授权分组")
    evidence = await read_review_resolution_chapters(
        db,
        novel_id=novel_id,
        chapters=frozen["chapters"],
        source_manifest=permission["source_manifest"],
    )
    try:
        receipt = await apply_import_scene_resolution_group(
            db,
            novel_id=novel_id,
            frozen=frozen,
            judgments=SceneBoundaryReview.model_validate(record["verify"]).scenes,
            evidence=evidence,
            workflow_id=task_id,
            confirmed=True,
        )
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc
    record = {**record, **receipt, "author_confirmed": True}
    state["scene_results"][group_key] = record
    run.checkpoints = {**run.checkpoints, "review_resolution": state}
    summary = {
        **run.progress.get("review_resolution", {}),
        "scene_results": list(state["scene_results"].values()),
        "scene_counts": dict(
            Counter(item["outcome"] for item in state["scene_results"].values())
        ),
    }
    run.progress = {
        **run.progress,
        "checkpoints": run.checkpoints,
        "review_resolution": summary,
    }
    await update_task_projection(
        db,
        task_id=task_id,
        task_type=run.workflow_type,
        novel_id=novel_id,
        result=run.progress,
    )
    await db.flush()
    resumed = False
    if run.status == "failed" and run.recovery_required:
        from modules.imports.orchestrator import DeepImportOrchestrator

        await DeepImportOrchestrator().resume_interrupted(db, task_id)
        resumed = True
    return {
        "task_id": task_id,
        "status": "pending" if resumed else "accepted",
        "scene": record,
    }


def is_new_source(item, existing):
    source = item["source_ref"]
    return not any(
        ref["source_ref"]["draft_id"] == source["draft_id"]
        and ref["source_ref"]["source_hash"] == source["source_hash"]
        and ref["source_ref"]["start_offset"] <= source["start_offset"]
        and ref["source_ref"]["end_offset"] >= source["end_offset"]
        for ref in existing
    )


async def review_dispositions(db, novel_id):
    """Fresh per-asset outcomes for author attention; unknown candidates stay unknown."""
    from sqlalchemy import select

    from modules.imports.models import ImportWorkflowRun
    from modules.world.facade import list_review_resolution_candidates
    from modules.writing.facade import (
        list_chapter_indices,
        list_latest_drafts_for_chapters,
    )

    candidates = await list_review_resolution_candidates(db, novel_id)
    current = {row["key"]: row["fingerprint"] for row in candidates}
    if not current:
        return {"imported_keys": [], "outcomes": {}}
    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, await list_chapter_indices(db, novel_id), content_limit=1
    )
    sources = {str(draft.id): draft.content_hash for draft in drafts}
    runs = (
        await db.execute(
            select(
                ImportWorkflowRun.authorization_snapshot["review_resolution"],
                ImportWorkflowRun.progress["review_resolution"],
            )
            .where(
                ImportWorkflowRun.novel_id == parse_uuid(novel_id),
                ImportWorkflowRun.progress["review_resolution"].as_string().is_not(None),
            )
            .order_by(ImportWorkflowRun.created_at.desc())
            .limit(100)
        )
    ).all()
    outcomes = {}
    expected_prompt = prompt_manifest()
    for permission, result in runs:
        if (
            not isinstance(permission, dict)
            or permission.get("prompt_manifest") != expected_prompt
            or not isinstance(result, dict)
        ):
            continue
        if any(
            sources.get(key) != value
            for key, value in permission.get("source_manifest", {}).items()
        ):
            continue
        for item in result.get("groups", []):
            key = item.get("key")
            if (
                key in current
                and key not in outcomes
                and current[key] == item.get("fingerprint")
            ):
                outcomes[key] = item
    return {"imported_keys": list(current), "outcomes": outcomes}
