"""Bounded, resumable completion over Evidence's shared one-hop search.

Imports owns permission, checkpoints and the fixed completion step. Evidence owns
retrieval/neighbor nomination; World owns every apply and rollback decision.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.imports.llm_schemas import RelationKind, _normalize_ai_world_entity_type
from modules.imports.workflow_schemas import DeepImportStep

COMPLETION_VERSION = "imports.targeted_completion.v1"
BATCH_SIZE = 5


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def normalize_roots(targets: list[dict]) -> list[dict]:
    roots = {}
    for target in targets:
        entity_id = str(target.get("entity_id") or "").strip()
        name = str(target.get("name") or "").strip()
        if bool(entity_id) == bool(name):
            raise ValueError("a completion root requires entity_id or name")
        key = "entity:" + entity_id if entity_id else "name:" + name.casefold()
        roots.setdefault(
            key,
            {"key": key, **({"entity_id": entity_id} if entity_id else {"name": name})},
        )
    return list(roots.values())


async def freeze_completion_permission(
    db,
    *,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    options: dict | None,
    targets: list[dict] | None = None,
) -> dict | None:
    from modules.writing.facade import list_latest_drafts_for_chapters

    if not options or options.get("enabled") is not True:
        return None
    drafts = await list_latest_drafts_for_chapters(
        db, novel_id, list(range(start_chapter, end_chapter + 1)), content_limit=0
    )
    manifest = {str(draft.id): draft.content_hash for draft in drafts}
    if not manifest or any(not value for value in manifest.values()):
        raise ValueError("专项补全需要可校验的章节正文")
    return {
        "version": COMPLETION_VERSION,
        "enabled": True,
        "roots": normalize_roots(targets or []),
        "root_selection": "explicit" if targets else "import_completion_hints",
        "source_manifest": manifest,
        "source_manifest_hash": stable_hash(manifest),
        "chapter_from": start_chapter,
        "chapter_to": end_chapter,
        "max_depth": 1,
        "actions": ["create_entity", "create_relation", "append_alias", "fill_empty"],
        "batch_size": BATCH_SIZE,
    }


async def authorize_completion(
    db, *, novel_id: str, task_id: str, permission: dict
) -> dict:
    from modules.world.facade import authorize_focused_world_completion

    receipt = await authorize_focused_world_completion(
        db,
        novel_id=novel_id,
        roots=permission["roots"],
        source_manifest=permission["source_manifest"],
        chapter_from=permission["chapter_from"],
        chapter_to=permission["chapter_to"],
        max_depth=1,
        actions=permission["actions"],
        root_selection=permission["root_selection"],
        task_id=task_id,
        workflow_id=task_id,
    )
    return {**permission, **receipt}


class _Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_key: str
    quote: str = Field(min_length=1, max_length=5000)


class _Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confidence: float | None = Field(default=None, ge=0, le=1)
    certainty: Literal["explicit", "inference", "uncertain"] = "uncertain"
    uncertainties: list[str] = Field(default_factory=list, max_length=10)


class _Entity(_Judgment):
    target_key: str
    entity_type: str = "other"
    summary: str | None = Field(default=None, max_length=5000)
    public_info: str | None = Field(default=None, max_length=5000)
    hidden_truth: str | None = Field(default=None, max_length=5000)
    field_evidence: dict[str, list[_Quote]] = Field(default_factory=dict)

    @field_validator("entity_type", mode="before")
    @classmethod
    def entity_type_known(cls, value):
        return _normalize_ai_world_entity_type(value)


class _Alias(_Judgment):
    target_key: str
    alias: str = Field(min_length=1, max_length=200)
    alias_kind: Literal["name", "title", "identity"] = "name"
    alias_type: str = Field(default="别名", max_length=100)
    evidence: list[_Quote] = Field(min_length=1, max_length=8)


class _Relation(_Judgment):
    source_key: str
    target_key: str
    relation_type: str = Field(min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    description: str = Field(min_length=1, max_length=5000)
    evidence: list[_Quote] = Field(min_length=1, max_length=8)


class CompletionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[_Entity] = Field(default_factory=list, max_length=5)
    aliases: list[_Alias] = Field(default_factory=list, max_length=10)
    relations: list[_Relation] = Field(default_factory=list, max_length=10)
    uncertain_items: list[str] = Field(default_factory=list, max_length=30)


def _batch_payload(result, *, targets: list, batch_keys: list[str]) -> dict:
    selected_evidence = [
        item for item in result.evidence if set(item.target_keys).intersection(batch_keys)
    ]
    identity_keys = set(batch_keys).union(
        *(set(item.target_keys) for item in selected_evidence)
    )
    payload = {
        "targets": [
            {
                "key": target.key,
                "name": target.name,
                "depth": target.depth,
                "resolution": target.resolution,
            }
            for target in targets
            if target.key in identity_keys
        ],
        "requested_target_keys": batch_keys,
        "evidence": [item.model_dump(mode="json") for item in selected_evidence],
    }
    if len(json.dumps(payload, ensure_ascii=False)) > 100_000:
        raise ValueError("专项补全单批资料超过冻结预算，保留进度待恢复")
    return payload


async def _complete_batch(
    client, *, result, targets: list, batch_keys: list[str]
) -> CompletionOutput:
    from infrastructure.llm.agent_step_harness import run_managed_structured
    from infrastructure.llm.prompt_loader import load_prompt
    from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

    payload = _batch_payload(result, targets=targets, batch_keys=batch_keys)
    request = LLMCallRequest(
        model=client.model_name,
        temperature=0.2,
        max_tokens=8192,
        response_format={"type": "json_object"},
        messages=[
            LLMMessage(
                role="system",
                content=load_prompt("targeted_completion"),
            ),
            LLMMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
    )
    return await asyncio.wait_for(
        run_managed_structured(
            client,
            request,
            CompletionOutput,
            step_name="imports.targeted_completion.structured",
            max_fix_attempts=1,
            transport_retries=False,
        ),
        timeout=270,
    )


def _source_ref(source_range: dict, quote: str, *, workflow_id: str) -> dict:
    return {
        "source_type": "manuscript",
        "source_id": str(source_range["draft_id"]),
        "source_hash": source_range["source_hash"],
        "source_version": str(source_range["version_number"]),
        "range_start": source_range["start_offset"],
        "range_end": source_range["end_offset"],
        "source_range": source_range,
        "quote": quote,
        "workflow_id": workflow_id,
    }


def materialize_completion(
    output: CompletionOutput,
    result,
    *,
    batch_keys: list[str],
    workflow_id: str,
    entity_refs: dict[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Only known target identities and exact source quotes become World inputs."""
    targets = {target.key: target for target in result.targets}
    evidence = {item.key: item for item in result.evidence}
    diagnostics = list(output.uncertain_items)
    items = []
    entity_refs = entity_refs if entity_refs is not None else {}
    entity_refs.update(
        {
            key: target.target_ref["target_id"]
            for key, target in targets.items()
            if target.resolution == "resolved" and target.target_ref
        }
    )

    def refs(quotes: list[_Quote]) -> list[dict]:
        found = []
        for quote in quotes:
            item = evidence.get(quote.evidence_key)
            if (
                item is None
                or item.source_ref is None
                or not item.text
                or quote.quote not in item.text
            ):
                continue
            source = asdict(item.source_ref)
            start = item.text.find(quote.quote)
            source["start_offset"] += start
            source["end_offset"] = source["start_offset"] + len(quote.quote)
            source["range_hash"] = hashlib.sha256(quote.quote.encode()).hexdigest()
            found.append(_source_ref(source, quote.quote, workflow_id=workflow_id))
        return found

    def append(kind, key, payload, source_refs, judgment):
        target = targets[key]
        for direct in target.direct_evidence_refs:
            source_range = direct.get("source_ref") or direct.get("source_range")
            quote = direct.get("quote")
            if isinstance(source_range, dict) and quote:
                source_refs.append(
                    _source_ref(source_range, quote, workflow_id=workflow_id)
                )
        review_reasons = []
        if judgment.confidence is None or judgment.confidence < 0.90:
            review_reasons.append("missing_or_low_confidence")
        if judgment.certainty != "explicit":
            review_reasons.append("inferred_or_uncertain_claim")
        if judgment.uncertainties:
            review_reasons.extend(judgment.uncertainties)
        item = {
            "kind": kind,
            "root_key": target.root_keys[0] if target.root_keys else key,
            "depth": target.depth,
            "authority_kind": "manuscript_observation",
            "disposition": "open" if review_reasons else "include",
            "review_reasons": review_reasons,
            "payload": payload,
            "source_refs": source_refs,
        }
        for direct in target.direct_evidence_refs:
            if direct.get("basis") == "canonical_relation" and direct.get("relation_id"):
                item["direct_relation_ref"] = {
                    "relation_id": direct["relation_id"],
                    "source_hash": direct.get("source_hash", ""),
                }
                break
        item["item_key"] = "i_" + stable_hash(item)[:40]
        items.append(item)
        return item["item_key"]

    for observation in output.entities:
        key = observation.target_key
        target = targets.get(key)
        if key not in batch_keys or target is None or target.resolution == "ambiguous":
            diagnostics.append("对象身份不明确或不在本批范围，已保留待复核")
            continue
        fields, field_refs = {}, refs(observation.field_evidence.get("name", []))
        for field in ("summary", "public_info", "hidden_truth"):
            value = getattr(observation, field)
            references = refs(observation.field_evidence.get(field, []))
            if value and references:
                fields[field] = value
                field_refs.extend(references)
            elif value:
                diagnostics.append(f"{target.name}：{field} 缺少可定位引文")
        if key in entity_refs:
            if fields:
                append(
                    "core_entity",
                    key,
                    {
                        "operation": "fill_empty",
                        "entity_id": entity_refs[key],
                        "fields": fields,
                    },
                    field_refs,
                    observation,
                )
        else:
            identity_refs = refs(observation.field_evidence.get("name", []))
            type_refs = refs(observation.field_evidence.get("entity_type", []))
            if (
                not identity_refs
                or not type_refs
                or not any(target.name in ref["quote"] for ref in identity_refs)
            ):
                diagnostics.append(f"{target.name}：名称或类型缺少可定位引文")
                continue
            item_key = append(
                "core_entity",
                key,
                {
                    "operation": "create",
                    "entity": {
                        "name": target.name,
                        "entity_type": observation.entity_type,
                        **fields,
                    },
                },
                identity_refs + type_refs + field_refs,
                observation,
            )
            entity_refs[key] = "local:" + item_key
    for alias in output.aliases:
        target = targets.get(alias.target_key)
        references = refs(alias.evidence)
        if (
            alias.target_key not in batch_keys
            or alias.target_key not in entity_refs
            or not references
            or target is None
            or not any(alias.alias in ref["quote"] for ref in references)
        ):
            diagnostics.append("别名缺少唯一对象或精确引文，已保留待复核")
            continue
        append(
            "entity_alias",
            alias.target_key,
            {
                "entity_ref": entity_refs[alias.target_key],
                "alias": alias.alias,
                "alias_kind": alias.alias_kind,
                "alias_type": alias.alias_type,
            },
            references,
            alias,
        )
    for relation in output.relations:
        references = refs(relation.evidence)
        left, right = targets.get(relation.source_key), targets.get(relation.target_key)
        if (
            left is None
            or right is None
            or relation.source_key not in entity_refs
            or relation.target_key not in entity_refs
            or relation.source_key == relation.target_key
            or not references
            or not ({relation.source_key, relation.target_key} & set(batch_keys))
            or (left.depth == right.depth == 1)
        ):
            diagnostics.append("关系端点不明确、越过一跳范围或缺少精确引文，已保留待复核")
            continue
        anchor = relation.source_key if left.depth else relation.target_key
        append(
            "entity_relation",
            anchor,
            {
                "operation": "create",
                "source_ref": entity_refs[relation.source_key],
                "target_ref": entity_refs[relation.target_key],
                "relation_type": relation.relation_type,
                "relation_kind": relation.relation_kind,
                "description": relation.description,
            },
            references,
            relation,
        )
    return items, diagnostics


async def select_automatic_roots(
    db, *, novel_id: str, workflow_id: str, progress
) -> list[dict]:
    """Select explicit gaps and unresolved provenance from this workflow only."""
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import trace_novel_evidence
    from modules.world.facade import get_world_context

    hints, entity_ids = [], set()
    for phase in ("phase2", "phase2b"):
        for scene in (progress.checkpoints.get(phase) or {}).get("scenes", []):
            hints.extend(scene.get("completion_hints", []))
            entity_ids.update(scene.get("created_entity_ids", []))
    current = {}
    ids = sorted(entity_ids)
    for offset in range(0, len(ids), 100):
        context = await get_world_context(
            db,
            novel_id,
            entity_ids=ids[offset : offset + 100],
            include_review=True,
            reveal_mode="author_full",
            limit=100,
        )
        for entity in context.entities:
            current[entity.entity_id] = entity
    roots = []
    for hint in hints:
        name = str(hint.get("name") or "").strip()
        if not name or not hint.get("quote"):
            continue
        identities = [
            entity
            for entity in current.values()
            if name in [entity.name, *entity.aliases]
        ]
        if hint.get("kind") == "field_gap" and len(identities) == 1:
            if not any(
                not str(getattr(identities[0], field, "") or "").strip()
                for field in hint.get("fields", [])
            ):
                continue
        roots.append(
            {"entity_id": identities[0].entity_id}
            if len(identities) == 1
            else {"name": name}
        )
    for entity_id in current:
        for field in ("summary", "public_info", "hidden_truth", "aliases"):
            trace = await trace_novel_evidence(
                db,
                novel_id=novel_id,
                target_ref={
                    "target_type": "core_entity",
                    "target_id": entity_id,
                    "target_path": field,
                },
                claim_path=field,
                content_mode="working",
                visibility=VisibilityContextContract(mode="author"),
            )
            for link in trace.get("links", []):
                provenance = link.get("provenance") or {}
                if (
                    link.get("status") == "needs_review"
                    and provenance.get("workflow_id") == workflow_id
                    and provenance.get("quote")
                ):
                    roots.append({"entity_id": entity_id})
                    hints.append(
                        {
                            "entity_id": entity_id,
                            "kind": "unresolved_evidence",
                            "field": field,
                            "quote": provenance["quote"],
                            "scene_id": provenance.get("scene_id"),
                            "reason": provenance.get("review_reason"),
                            "evidence_link_id": link.get("id"),
                        }
                    )
    progress.checkpoints["completion_hints"] = hints
    return normalize_roots(roots)


async def run_targeted_completion(
    db, *, task, progress, checkpoint, project_settings: dict
) -> None:
    permission = progress.authorization_snapshot.get("targeted_completion")
    if not permission:
        return
    from modules.evidence.contracts import (
        CompileOptions,
        ContextSnapshotRequest,
        FocusedEvidenceRequest,
        FocusedEvidenceResult,
        FocusedEvidenceRoot,
    )
    from modules.evidence.facade import (
        fail_context_snapshot,
        open_context_snapshot,
        retrieve_focused_evidence,
        revalidate_focused_evidence,
        succeed_context_snapshot,
    )
    from modules.project.facade import (
        create_project_snapshot_llm_client,
        require_active_project_exclusive,
    )
    from modules.world.contracts import (
        FocusedWorldPackageApplyRequest,
        FocusedWorldPackageRequest,
    )
    from modules.world.facade import (
        apply_focused_world_package,
        submit_focused_world_package,
    )

    if (
        permission.get("version") != COMPLETION_VERSION
        or permission.get("enabled") is not True
        or not permission.get("authorization_id")
        or not permission.get("source_manifest")
        or permission.get("max_depth") != 1
    ):
        raise ValueError("专项补全授权缺失或过期")
    if (
        permission["chapter_from"] != int(task.meta["start_chapter"])
        or permission["chapter_to"] != int(task.meta["end_chapter"])
        or permission.get("source_manifest_hash")
        != stable_hash(permission["source_manifest"])
    ):
        raise ValueError("专项补全来源范围与原授权不一致")
    novel_id = str(task.meta["novel_id"])
    state = dict(progress.checkpoints.get("targeted_completion") or {})
    fingerprint = stable_hash(permission)
    if state and state.get("permission_fingerprint") != fingerprint:
        raise ValueError("专项补全授权已改变")
    if state.get("status") == "done":
        return
    if not state:
        roots = permission["roots"] or await select_automatic_roots(
            db, novel_id=novel_id, workflow_id=str(task.id), progress=progress
        )
        state = {
            "version": 1,
            "permission_fingerprint": fingerprint,
            "roots": roots,
            "root_position": 0,
            "status": "running",
            "continuation": None,
            "packages": [],
            "entity_results": {},
            "page": None,
            "counts": {"created": 0, "filled": 0, "review": 0},
        }
    state["status"] = "running"
    progress.phase = "running"
    progress.current_step = DeepImportStep.targeted_completion
    progress.current_phase = "targeted_completion"

    async def save():
        progress.checkpoints["targeted_completion"] = state
        progress.targeted_completion = {
            "status": state["status"],
            "root_count": len(state["roots"]),
            "completed_roots": state["root_position"],
            **state["counts"],
            "coverage": state.get("coverage", {}),
            "warnings": state.get("warnings", []),
            "available_actions": (["resume"] if state["status"] == "partial" else [])
            + (["rollback"] if state["packages"] else []),
        }
        progress.message = "正在查读指定对象与直接关联资料"
        await checkpoint(progress, 0.8)

    await save()
    while state["root_position"] < len(state["roots"]):
        batch = state["roots"][
            state["root_position"] : state["root_position"] + BATCH_SIZE
        ]
        request = FocusedEvidenceRequest(
            novel_id=novel_id,
            roots=[
                FocusedEvidenceRoot(
                    key=root["key"],
                    name=root.get("name"),
                    target_ref=(
                        {
                            "target_type": "entity",
                            "target_id": root["entity_id"],
                            "target_path": "",
                        }
                        if root.get("entity_id")
                        else None
                    ),
                )
                for root in batch
            ],
            chapter_from=permission["chapter_from"],
            chapter_to=permission["chapter_to"],
            max_depth=1,
            compile_options=CompileOptions(
                novel_id=novel_id,
                task="专项补全",
                scope="full",
                consumer_action="imports.targeted_completion",
                context_mode="working",
                content_mode="working",
                include_pending_objects=True,
                reveal_mode="author_safe",
                source_manifest=permission["source_manifest"],
            ),
            continuation=state.get("continuation"),
        )
        page = state.get("page")
        if page is None:
            client = create_project_snapshot_llm_client(
                project_settings, novel_id=novel_id, timeout_override=240
            )
            active_snapshot_id = None
            try:
                result = await retrieve_focused_evidence(
                    db, request, llm_client=client, before_llm=save
                )
                items, diagnostics, outputs, snapshots = [], [], [], []
                keys = [
                    target.key
                    for target in result.targets
                    if any(target.key in item.target_keys for item in result.evidence)
                ]
                for offset in range(0, len(keys), BATCH_SIZE):
                    selected = keys[offset : offset + BATCH_SIZE]
                    payload = _batch_payload(
                        result, targets=result.targets, batch_keys=selected
                    )
                    snapshot = await open_context_snapshot(
                        db,
                        ContextSnapshotRequest(
                            novel_id=novel_id,
                            task_id=str(task.id),
                            workflow_id=str(task.id),
                            phase="targeted_completion",
                            operation="complete_target_batch",
                            prompt_name="targeted_completion",
                            model=client.model_name,
                            attempt=int(task.attempt),
                            compile_options={
                                "source_manifest": permission["source_manifest"],
                                "max_depth": 1,
                                "chapter_from": permission["chapter_from"],
                                "chapter_to": permission["chapter_to"],
                            },
                            included_asset_ids={"targets": selected},
                            context_summary={
                                "input_fingerprint": stable_hash(payload),
                                "source_fingerprint": result.source_fingerprint,
                            },
                            section_metadata={
                                "target_keys": selected,
                                "sources": [
                                    item.model_dump(mode="json", exclude={"text"})
                                    for item in result.evidence
                                ],
                            },
                            token_metadata={
                                "input_characters": len(
                                    json.dumps(payload, ensure_ascii=False)
                                ),
                                "max_tokens": 8192,
                                "timeout_seconds": 270,
                            },
                            rendered_context=json.dumps(payload, ensure_ascii=False),
                            retain_rendered_context=False,
                        ),
                    )
                    active_snapshot_id = snapshot.id
                    snapshots.append(snapshot.id)
                    state.setdefault("snapshot_ids", []).append(snapshot.id)
                    await save()
                    output = await _complete_batch(
                        client, result=result, targets=result.targets, batch_keys=selected
                    )
                    await succeed_context_snapshot(
                        db, novel_id=novel_id, snapshot_id=snapshot.id, result_refs=[]
                    )
                    active_snapshot_id = None
                    outputs.append((selected, output))
                # Entity packages precede all links, so links across target batches
                # resolve earlier package receipts without broadening discovery.
                entity_refs = {}
                for selected, output in outputs:
                    materialized, uncertain = materialize_completion(
                        output.model_copy(update={"aliases": [], "relations": []}),
                        result,
                        batch_keys=selected,
                        workflow_id=str(task.id),
                        entity_refs=entity_refs,
                    )
                    items.append(materialized)
                    diagnostics.extend(uncertain)
                for selected, output in outputs:
                    materialized, uncertain = materialize_completion(
                        output.model_copy(update={"entities": [], "uncertain_items": []}),
                        result,
                        batch_keys=selected,
                        workflow_id=str(task.id),
                        entity_refs=entity_refs,
                    )
                    items.append(materialized)
                    diagnostics.extend(uncertain)
            except Exception as exc:
                from infrastructure.llm.redaction import redact_diagnostic

                if active_snapshot_id:
                    await fail_context_snapshot(
                        db,
                        novel_id=novel_id,
                        snapshot_id=active_snapshot_id,
                        error_kind=type(exc).__name__,
                        error_message=redact_diagnostic(exc, limit=300),
                    )
                state["status"] = "partial"
                await save()
                raise
            finally:
                await client.close()
            page_result = result.model_dump(
                mode="json", exclude={"evidence": {"__all__": {"text"}}}
            )
            page_result["evidence"] = [
                item for item in page_result["evidence"] if item.get("source_ref")
            ]
            page = {
                "result": page_result,
                "item_batches": items,
                "batch_snapshots": snapshots + snapshots,
                "snapshot_result_refs": {},
                "next_batch": 0,
                "diagnostics": diagnostics,
            }
            state["page"] = page
            await save()
        result = FocusedEvidenceResult.model_validate(page["result"])
        while page["next_batch"] < len(page["item_batches"]):
            items = json.loads(json.dumps(page["item_batches"][page["next_batch"]]))
            local_keys = {item["item_key"] for item in items}
            for item in items:
                for field in ("source_ref", "target_ref", "entity_ref"):
                    ref = str(item["payload"].get(field) or "")
                    if ref.startswith("local:") and ref[6:] not in local_keys:
                        resolved = state["entity_results"].get(ref[6:])
                        if resolved:
                            item["payload"][field] = resolved
                        else:
                            item["disposition"] = "open"

            await require_active_project_exclusive(db, novel_id)
            await revalidate_focused_evidence(db, request, result)
            if items:
                package = await submit_focused_world_package(
                    db,
                    FocusedWorldPackageRequest(
                        novel_id=novel_id,
                        authorization_id=permission["authorization_id"],
                        task_id=str(task.id),
                        task_type=task.task_type,
                        attempt=int(task.attempt),
                        lease_id=str(task.lease_id),
                        items=items,
                        source_manifest_hash=permission["source_manifest_hash"],
                        context_fingerprint=result.source_fingerprint,
                        roots=(
                            batch
                            if permission["root_selection"] == "import_completion_hints"
                            else state["roots"]
                        ),
                    ),
                )
                receipt = {}
                if package.get("included_count", len(items)):
                    receipt = await apply_focused_world_package(
                        db,
                        FocusedWorldPackageApplyRequest(
                            novel_id=novel_id,
                            authorization_id=permission["authorization_id"],
                            task_id=str(task.id),
                            task_type=task.task_type,
                            attempt=int(task.attempt),
                            lease_id=str(task.lease_id),
                            suggestion_id=package["suggestion_id"],
                            expected_preview_hash=package["expected_preview_hash"],
                        ),
                    )
                if receipt:
                    state["packages"].append(package["suggestion_id"])
                else:
                    state.setdefault("review_packages", []).append(
                        package["suggestion_id"]
                    )
                if receipt.get("review_suggestion_id"):
                    state.setdefault("review_packages", []).append(
                        receipt["review_suggestion_id"]
                    )
                for ref in receipt.get("result_refs", []):
                    if ref.get("item_key") and ref.get("id"):
                        state["entity_results"][ref["item_key"]] = str(ref["id"])
                state["counts"]["review"] += int(package.get("review_count", 0))
                snapshot_id = page["batch_snapshots"][page["next_batch"]]
                refs = page["snapshot_result_refs"].setdefault(snapshot_id, [])
                refs.extend(receipt.get("result_refs", []))
                await succeed_context_snapshot(
                    db, novel_id=novel_id, snapshot_id=snapshot_id, result_refs=refs
                )
                for change in receipt.get("applied_changes", []):
                    key = (
                        "filled" if change.get("operation") == "fill_empty" else "created"
                    )
                    state["counts"][key] += 1
            page["next_batch"] += 1
            await save()
        state["counts"]["review"] += len(page["diagnostics"])
        state.setdefault("diagnostics", []).extend(page["diagnostics"])
        state["coverage"] = result.coverage.model_dump()
        state["warnings"] = result.warnings
        state["continuation"] = (
            result.continuation.model_dump(mode="json") if result.continuation else None
        )
        state["page"] = None
        if result.coverage.complete and result.continuation is None:
            state["root_position"] += len(batch)
        elif result.continuation is None:
            state["status"] = "partial"
            await save()
            raise RuntimeError("专项补全尚有未完成的查读，请恢复任务后继续")
        await save()
    state["status"] = "done"
    progress.completed_steps = list(
        dict.fromkeys([*progress.completed_steps, "targeted_completion"])
    )
    await save()


async def rollback_targeted_completion(db, *, novel_id: str, task_id: str) -> dict:
    from infrastructure.tasks.facade import update_task_projection
    from modules.imports.contracts import TaskNotFoundError
    from modules.imports.workflow_runs import ImportWorkflowRunService
    from modules.project.facade import require_active_project_exclusive
    from modules.world.facade import rollback_focused_world_package

    await require_active_project_exclusive(db, novel_id)
    runs = ImportWorkflowRunService()
    await runs.reconcile_scoped_task_owners(db, task_id=task_id)
    run = await runs.get_by_task(db, task_id=task_id, for_update=True)
    if run is None or str(run.novel_id) != novel_id:
        raise TaskNotFoundError(task_id)
    if run.status in {"pending", "running"}:
        raise ValueError("请先停止任务，再撤销本次补全")
    result = dict(run.progress or {})
    checkpoints = dict(result.get("checkpoints") or {})
    state = dict(checkpoints.get("targeted_completion") or {})
    if not state or not (run.authorization_snapshot or {}).get("targeted_completion"):
        raise ValueError("该任务没有可撤销的专项补全")
    if state.get("rollback_receipts") is not None and not state.get("rollback_conflicts"):
        return {
            "task_id": task_id,
            "status": "rolled_back",
            "receipts": state["rollback_receipts"],
        }
    receipts = []
    for suggestion_id in reversed(state.get("packages", [])):
        receipts.append(
            await rollback_focused_world_package(
                db, novel_id=novel_id, suggestion_id=suggestion_id
            )
        )
    conflicts = sum(
        item.get("status") == "conflict"
        for receipt in receipts
        for item in receipt.get("results", [])
    )
    status = "partial" if conflicts else "rolled_back"
    state["rollback_conflicts"] = conflicts
    state["rollback_receipts"] = receipts
    checkpoints["targeted_completion"] = state
    result["checkpoints"] = checkpoints
    result["targeted_completion"] = {
        **dict(result.get("targeted_completion") or {}),
        "rollback_status": status,
        "rollback_conflicts": conflicts,
        "available_actions": ["rollback"] if conflicts else [],
    }
    run.checkpoints = checkpoints
    run.progress = result
    await update_task_projection(
        db, task_id=task_id, task_type=run.workflow_type, novel_id=novel_id, result=result
    )
    return {
        "task_id": task_id,
        "status": status,
        "conflicts": conflicts,
        "receipts": receipts,
    }
