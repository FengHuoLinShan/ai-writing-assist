"""Saved-only author focus resolution and host-built source dependency receipts."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid5

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.account.facade import (
    is_anonymous_rp_principal,
    is_demo_readonly_principal,
    require_account_active,
)
from modules.assistant.contracts import ForecastContext, ForecastDomainFact
from modules.assistant.forecast.contracts import (
    EvidenceRef,
    FocusRequest,
    ResolvedScope,
    TextRange,
)
from modules.assistant.proactive import _watch
from modules.evidence import facade as evidence
from modules.evidence.contracts import VisibilityContextContract
from modules.project.facade import get_any_project_context, require_active_project
from modules.story.facade import get_scene_contract
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    list_manuscript_sources,
)


def scope_matches(scope, frozen):
    current = scope.model_dump(mode="json")
    if "context_keys" not in frozen:
        current.pop("context_keys", None)
    return current == frozen


async def authorize(db, novel_id, *, persona="author"):
    if persona == "rp":
        return await get("assistant.forecast.personas")["rp"]["authorize"](db, novel_id)
    if is_demo_readonly_principal() or is_anonymous_rp_principal():
        raise NotFoundError("前瞻仅对当前账户自己的作品开放")
    await require_active_project(db, novel_id)
    project = await get_any_project_context(db, novel_id)
    if project is None or project.project_kind != "author":
        raise NotFoundError("作品不可访问")
    await require_account_active(db, UUID(str(project.owner_id)))
    return project


async def materialize(
    db, novel_id, focus: FocusRequest, *, persona="author", include_understanding=True
):
    if persona == "rp":
        return await get("assistant.forecast.personas")["rp"]["materialize"](
            db, novel_id, focus
        )
    if focus.page == "interaction":
        raise NotFoundError("请从旅程入口查看互动建议")
    project = await authorize(db, novel_id)
    watch = await _watch(db, novel_id)
    generation = watch.generation if watch else 0
    excluded = (
        {
            str(value).rsplit(":", 1)[-1]
            for value in ((watch.policy_json or {}).get("settings") or {}).get(
                "excluded_targets", []
            )
        }
        if watch
        else set()
    )
    confirmed = None
    excluded.update(str(value).rsplit(":", 1)[-1] for value in focus.excluded_targets)
    if focus.context_confirmation_id and focus.excluded_targets:
        raise ConflictError(
            "请先在参考资料中更新排除项并重新确认", code="CONFIRMATION_SCOPE_CONFLICT"
        )
    if focus.context_confirmation_id:
        confirmed = await evidence.prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=focus.context_confirmation_action,
            confirmation_id=str(focus.context_confirmation_id),
        )
    sources, refs, dependencies = [], [], []
    chapter_index = None
    saved_draft_hash = None
    scope = {
        "novel_id": novel_id,
        "owner_id": str(project.owner_id),
        "persona": "author",
        "excluded": sorted(excluded),
        "confirmation": str(focus.context_confirmation_id or ""),
        "action": focus.context_confirmation_action,
        "policy_generation": generation,
    }

    def remember(
        kind, resource_id, value, *, label, revision=None, text_range=None, full_hash=None
    ):
        if str(resource_id) in excluded:
            raise NotFoundError("当前资料不在可读范围内")
        value_text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
        source_hash = full_hash or content_hash(value)
        evidence_id = f"source_{len(refs)}"
        refs.append(
            EvidenceRef(
                evidence_id=evidence_id,
                resource_kind=kind,
                resource_id=resource_id,
                source_hash=source_hash,
                revision_token=revision or source_hash,
                source_range=text_range,
                range_hash=hashlib.sha256(value_text.encode()).hexdigest()
                if text_range
                else None,
                label=label,
            )
        )
        sources.append({"evidence_id": evidence_id, "text": value_text, "label": label})
        dependencies.append(
            {
                "dependency_key": f"{kind}:{resource_id}",
                "resource_kind": kind,
                "resource_id": str(resource_id),
                "revision_token": revision or source_hash,
                "role": "content",
                "required": True,
            }
        )

    if focus.draft_id:
        draft = await get_draft(db, novel_id, str(focus.draft_id))
        latest = (
            await get_latest_draft_for_chapter(db, novel_id, draft.chapter_index)
            if draft
            else None
        )
        if (
            draft is None
            or latest is None
            or latest.id != draft.id
            or (
                focus.expected_source_hash
                and draft.content_hash != focus.expected_source_hash
            )
        ):
            raise ConflictError("正文保存版本已变化，请刷新参考资料", code="SOURCE_STALE")
        chapter_index = draft.chapter_index
        saved_draft_hash = draft.content_hash
        content = draft.content or ""
        selected = focus.selected_range
        focus_label = "选中文字" if selected else "章末资料（未指定位置）"
        if selected and selected.end_offset > len(content):
            raise ValidationError(
                "所选文字超出保存版本", code="INVALID_RANGE", status_code=422
            )
        if confirmed:
            allowed = {
                str(value)
                for values in confirmed.confirmation.selected_asset_ids.values()
                for value in values
            }
            allowed.update(
                (confirmed.compile_options.get("source_manifest") or {}).keys()
            )
            denied = {
                str(value)
                for values in confirmed.confirmation.excluded_asset_ids.values()
                for value in values
            }
            if str(draft.id) not in allowed or str(draft.id) in denied:
                raise ConflictError(
                    "焦点正文不在原确认的资料内", code="CONFIRMATION_SCOPE_CONFLICT"
                )
        if content and not confirmed:
            if selected is None and focus.cursor_offset is not None:
                cursor = focus.cursor_offset
                if cursor > len(content):
                    raise ValidationError(
                        "光标超出保存版本", code="INVALID_RANGE", status_code=422
                    )
                start = content.rfind("\n", 0, cursor) + 1
                end = content.find("\n", cursor)
                end = end if end >= 0 else len(content)
                if end > start:
                    selected = TextRange(start_offset=start, end_offset=end)
                    focus_label = "光标所在段落"
            selected = selected or TextRange(
                start_offset=max(0, len(content) - 12000), end_offset=len(content)
            )
            from modules.writing.facade import build_manuscript_range_ref

            source_ref = await build_manuscript_range_ref(
                db,
                novel_id,
                draft_id=str(draft.id),
                start_offset=selected.start_offset,
                end_offset=selected.end_offset,
                content_mode="working",
            )
            await evidence.read_novel_evidence(
                db,
                novel_id=novel_id,
                source_ref=source_ref,
                visibility=VisibilityContextContract(
                    mode="author", cutoff_chapter=chapter_index
                ),
                before=0,
                after=0,
            )
            remember(
                "writing_draft",
                draft.id,
                content[selected.start_offset : selected.end_offset],
                label=f"{draft.title or f'第 {chapter_index} 章'} · {focus_label}",
                revision=f"{draft.version_number}:{draft.content_hash}",
                text_range=selected,
                full_hash=draft.content_hash,
            )
    if focus.context_confirmation_id:
        included_ids = {
            str(value)
            for values in confirmed.confirmation.selected_asset_ids.values()
            for value in values
        }
        if included_ids & excluded:
            raise ConflictError(
                "原确认包含当前已排除资料，请在原入口重新确认",
                code="CONFIRMATION_SCOPE_CONFLICT",
            )
        remember(
            "context_confirmation",
            focus.context_confirmation_id,
            evidence.render_compiled_context(confirmed.compiled),
            label="本次已确认资料",
        )
        allowed = {
            str(value)
            for values in confirmed.confirmation.selected_asset_ids.values()
            for value in values
        }
        denied = {
            str(value)
            for values in confirmed.confirmation.excluded_asset_ids.values()
            for value in values
        }
        if (
            focus.scene_id
            and (str(focus.scene_id) not in allowed or str(focus.scene_id) in denied)
        ) or (
            focus.target
            and (
                str(focus.target.resource_id) not in allowed
                or str(focus.target.resource_id) in denied
            )
        ):
            raise ConflictError(
                "焦点资料不在原确认中", code="CONFIRMATION_SCOPE_CONFLICT"
            )
    targets = []
    if focus.scene_id:
        targets.append(("scene", focus.scene_id))
    if focus.target:
        targets.append((focus.target.resource_kind, focus.target.resource_id))
    understanding_boundary_known = True
    for kind, resource_id in targets:
        if kind == "scene":
            # Case goals and author constraints have no Scene-time proof.
            understanding_boundary_known = False
            scene = await get_scene_contract(db, novel_id, str(resource_id))
            if scene is None:
                raise NotFoundError("场景不可访问")
            if not scene.chapter_ids:
                understanding_boundary_known = False
            else:
                # chapter_ids are stringified indices; compare numerically so a
                # focus Scene can only tighten, never break, the chapter cutoff.
                first_chapter = min(int(value) for value in scene.chapter_ids)
                chapter_index = (
                    min(chapter_index, first_chapter) if chapter_index else first_chapter
                )
    for kind, resource_id in targets:
        if confirmed:
            continue
        if kind in {"map_atlas_node", "import_workflow", "domain_result"}:
            continue
        inspection = await evidence.inspect_novel_target(
            db,
            novel_id=novel_id,
            target_ref={
                "target_type": {
                    "scene": "outline_scene",
                    "world_bible_draft": "world_bible_page_draft",
                }.get(kind, kind),
                "target_id": str(resource_id),
            },
            content_mode="working",
            visibility=VisibilityContextContract(
                mode="author", cutoff_chapter=chapter_index
            ),
        )
        if not inspection.get("visible"):
            raise NotFoundError("焦点资料不可访问")
        remember(kind, resource_id, inspection, label="当前工作资料")
    facts = []
    domains = {
        "writing": ["writing", "story"],
        "scene": ["story", "writing"],
        "outline": ["story"],
        "world": ["world"],
        "map": ["world"],
        "rag": ["evidence"],
        "imports": ["imports"],
        "assistant": ["assistant", "world"],
        "project": ["project", "assistant"],
        "today": ["project", "assistant"],
        "account": ["account"],
    }.get(focus.page, [])
    # A confirmation is the entire selected/excluded set. Derived domain queries
    # never widen that set; selected confirmation text was rematerialized above.
    if focus.prior_forecast_run_id and "assistant" not in domains:
        domains.append("assistant")
    if not focus.context_confirmation_id:
        for domain in dict.fromkeys([*domains, "account"]):
            for raw in await get("assistant.forecast.sources")[domain](
                db, novel_id, focus, excluded
            ):
                fact = ForecastDomainFact.model_validate(raw)
                identity = uuid5(
                    UUID(novel_id),
                    f"forecast:{domain}:{fact.capability_id}:{fact.subject}",
                )
                remember(
                    "domain_result",
                    identity,
                    fact.model_dump(mode="json"),
                    label=fact.title,
                )
                facts.append((fact, refs[-1]))
        policy = (watch.policy_json or {}).get("forecast_v1", {}) if watch else {}
        fact = ForecastDomainFact(
            capability_id="account.cost_gate.v1",
            subject="forecast_authorization",
            title="按本次授权开始计算",
            summary="手动分析最多四次模型请求；后台计算还需单独授权，并与主动检查共享每日上限。",
            source={"policy": policy, "generation": generation, "request_limit": 4},
            scope_label="当前前瞻授权分区与固定请求上限；不推算未经验证的模型价格",
            target={"page": "assistant"},
        )
        remember(
            "policy",
            uuid5(UUID(novel_id), "forecast-cost-policy"),
            fact.model_dump(mode="json"),
            label=fact.title,
        )
        facts.append((fact, refs[-1]))
    understanding = {}
    if include_understanding and not confirmed and understanding_boundary_known:
        packet, omissions = await evidence.collect_forecast_understanding(
            db, novel_id, chapter_index=chapter_index, excluded=excluded
        )
        understanding = {"records": [], "excluded": omissions}
        if packet and any(
            source.content["content"] != sources[index]["text"]
            for source in packet.resources
            for index, ref in enumerate(refs)
            if str(ref.resource_id) == str(source.id)
        ):
            packet = None
            understanding["excluded"].append({"reason": "root_not_fully_selected"})
        if packet:
            original_lengths = len(sources), len(refs), len(dependencies)
            source_map = {}
            for source in packet.resources:
                body = source.content["content"]
                if str(source.id) not in {str(ref.resource_id) for ref in refs}:
                    remember(
                        "writing_draft",
                        source.id,
                        body,
                        label=f"前文依据 · {source.label}",
                        revision=source.revision,
                        full_hash=hashlib.sha256(body.encode()).hexdigest(),
                        text_range=TextRange(start_offset=0, end_offset=len(body))
                        if body
                        else None,
                    )
                    sources[-1]["chapter_index"] = source.chapter_index
                source_map[source.key] = next(
                    ref.evidence_id
                    for ref in refs
                    if str(ref.resource_id) == str(source.id)
                )
            understanding = {
                **packet.cognition.model_dump(mode="json"),
                "source_map": source_map,
                "excluded": [*omissions, *packet.cognition.excluded],
            }
            for ref in packet.cognition.records:
                dependencies.append(
                    {
                        "dependency_key": f"cognition:{ref.record_id}",
                        "resource_kind": "cognition",
                        "resource_id": str(ref.record_id),
                        "revision_token": f"{ref.revision_id}:{ref.content_hash}",
                        "role": "interpretation",
                        "required": True,
                    }
                )
            if (
                len(json.dumps([sources, understanding["records"]], ensure_ascii=False))
                > 22000
            ):
                del sources[original_lengths[0] :]
                del refs[original_lengths[1] :]
                del dependencies[original_lengths[2] :]
                understanding = {
                    "records": [],
                    "excluded": [{"reason": "not_selected_capacity"}],
                }
    elif include_understanding and not confirmed:
        understanding = {
            "records": [],
            "excluded": [{"reason": "historical_understanding_unavailable"}],
        }
    # Include the authorized collection, not just cited hits, in negative-query freshness.
    manuscript = await list_manuscript_sources(db, novel_id, content_mode="working")
    collection = [
        (source.chapter_index, source.id, source.content_hash)
        for source in manuscript
        if str(source.id) not in excluded
        and (chapter_index is None or source.chapter_index <= chapter_index)
    ]
    manifest_hash = content_hash(collection)
    dependencies.append(
        {
            "dependency_key": "query_scope:working",
            "resource_kind": "query_scope",
            "resource_id": novel_id,
            "revision_token": manifest_hash,
            "role": "query_scope",
            "required": True,
        }
    )
    dependencies.append(
        {
            "dependency_key": "policy:forecast",
            "resource_kind": "policy",
            "resource_id": novel_id,
            "revision_token": str(generation),
            "role": "authorization",
            "required": True,
        }
    )
    context_fields = focus.model_dump(
        mode="json",
        exclude={
            "client_context_id",
            "focus_seq",
            "editor_state",
            "expected_source_hash",
        },
    )
    if not focus.excluded_targets:
        context_fields.pop("excluded_targets", None)
    if focus.cursor_offset is None:
        context_fields.pop("cursor_offset", None)
    scope["chapter_index"] = chapter_index
    scope_hash = content_hash(scope)
    context_hash = content_hash(
        {"focus": context_fields, "scope": scope_hash, "dependencies": dependencies}
    )
    context_keys = {
        "authority_scope_key": scope_hash,
        "evidence_snapshot_key": content_hash(
            {
                "dependencies": dependencies,
                "evidence": [ref.model_dump(mode="json") for ref in refs],
            }
        ),
        "task_context_key": content_hash(
            {
                key: value
                for key, value in context_fields.items()
                if key not in {"page", "cursor_offset"}
            }
        ),
        "presentation_focus": content_hash(
            {
                "page": focus.page,
                "cursor": focus.cursor_offset,
                "client": str(focus.client_context_id),
                "sequence": focus.focus_seq,
            }
        ),
    }
    if (
        len(json.dumps([sources, understanding.get("records", [])], ensure_ascii=False))
        > 22000
    ):
        raise ValidationError("本次资料过多，请缩小选择范围", code="CONTEXT_TOO_LARGE")
    for item in dependencies:
        item["scope_stamp"] = scope_hash
    return ForecastContext(
        ResolvedScope(
            novel_id=novel_id,
            owner_id=project.owner_id,
            persona="author",
            audience_key="author",
            scope_hash=scope_hash,
            context_hash=context_hash,
            policy_generation=generation,
            source_manifest_hash=manifest_hash,
            context_keys=context_keys,
        ),
        focus,
        sources,
        refs,
        dependencies,
        chapter_index,
        sorted(excluded),
        facts,
        saved_draft_hash,
        understanding,
    )
