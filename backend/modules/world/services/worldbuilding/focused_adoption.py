"""Authorization, evidence and undo guards for the existing adoption package."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import String, cast, select

from core.errors import ConflictError, ValidationError
from infrastructure.tasks.facade import require_running_task_attempt
from modules.account.facade import current_account_id
from modules.project.facade import (
    get_project_context,
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.models import CoreEntity, CreationSuggestion, EntityRelation
from modules.world.schemas import (
    WorldAdoptionPackagePayload,
    WorldAdoptionPackageSaveRequest,
)
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import list_manuscript_sources, read_manuscript_range
from shared.utils import parse_uuid

POLICY = "focused_world_completion.v1"
ACTIONS = {"create_entity", "create_relation", "append_alias", "fill_empty"}


def stable_hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def is_empty(value):
    return value is None or isinstance(value, str) and not value.strip()


async def authorize(
    db,
    *,
    novel_id,
    roots,
    source_manifest,
    chapter_from,
    chapter_to,
    max_depth=1,
    actions=None,
    root_selection="explicit",
    task_id=None,
    workflow_id=None,
    authorization_id=None,
):
    await require_active_project(db, novel_id)
    project = await get_project_context(db, novel_id)
    actor = str(current_account_id())
    if not project or project.owner_id != actor:
        raise ValidationError("Focused completion requires the current project owner")
    allowed = list(actions if actions is not None else sorted(ACTIONS))
    if not set(allowed).issubset(ACTIONS) or not allowed or max_depth not in (0, 1):
        raise ValidationError("Invalid focused completion authorization")
    if root_selection not in {"explicit", "import_completion_hints"} or not task_id:
        raise ValidationError("Focused authorization requires a bound task")
    if root_selection == "explicit" and not roots:
        raise ValidationError("Explicit authorization requires roots")
    if not source_manifest or chapter_from < 1 or chapter_to < chapter_from:
        raise ValidationError("Focused authorization requires a frozen manuscript scope")
    if len(roots) > 1000 or any(
        not item.get("key") or not (item.get("entity_id") or item.get("name"))
        for item in roots
    ):
        raise ValidationError("Invalid focused roots")
    snapshot = {
        "policy": POLICY,
        "owner_id": actor,
        "novel_id": str(parse_uuid(novel_id)),
        "roots": roots,
        "source_manifest": source_manifest,
        "chapter_from": chapter_from,
        "chapter_to": chapter_to,
        "max_depth": max_depth,
        "actions": allowed,
        "root_selection": root_selection,
        "task_id": task_id,
        "workflow_id": workflow_id,
        "authorized_at": datetime.now(UTC).isoformat(),
    }
    if authorization_id:
        original = await authorization(db, novel_id, authorization_id)
        immutable = set(snapshot) - {"task_id", "authorized_at"}
        if any(snapshot[key] != original.get(key) for key in immutable):
            raise ValidationError("A resumed executor cannot alter authorization scope")
        record = await db.get(CreationSuggestion, parse_uuid(authorization_id))
        receipt = dict(record.result_ref_json)
        grants = list(receipt.get("executor_grants") or [])
        if not any(grant["task_id"] == task_id for grant in grants):
            grants.append(
                {
                    "task_id": task_id,
                    "owner_id": actor,
                    "granted_at": datetime.now(UTC).isoformat(),
                }
            )
        receipt["executor_grants"] = grants
        record.result_ref_json = receipt
        await db.flush()
        return {
            "authorization_id": authorization_id,
            "authorization_fingerprint": receipt["authorization_fingerprint"],
        }
    fingerprint = stable_hash(snapshot)
    record = CreationSuggestion(
        novel_id=parse_uuid(novel_id),
        source_module="world",
        review_group="focused_authorization",
        target_type="focused_world_authorization",
        action_schema=POLICY,
        payload_json=snapshot,
        evidence_refs_json=[],
        result_ref_json={"authorization_fingerprint": fingerprint},
        risk_level="low",
        status="accepted",
    )
    db.add(record)
    await db.flush()
    return {"authorization_id": str(record.id), "authorization_fingerprint": fingerprint}


async def authorization(db, novel_id, authorization_id):
    await require_active_project(db, novel_id)
    record = await db.scalar(
        select(CreationSuggestion)
        .where(
            CreationSuggestion.id == parse_uuid(authorization_id),
            CreationSuggestion.novel_id == parse_uuid(novel_id),
            CreationSuggestion.target_type == "focused_world_authorization",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if record is None or record.status != "accepted":
        raise ValidationError("Focused authorization is unavailable")
    snapshot = record.payload_json
    project = await get_project_context(db, novel_id)
    if (
        snapshot.get("policy") != POLICY
        or snapshot.get("owner_id") != getattr(project, "owner_id", None)
        or stable_hash(snapshot)
        != record.result_ref_json.get("authorization_fingerprint")
    ):
        raise ValidationError("Focused authorization changed")
    return snapshot


async def fence(db, request):
    await require_active_project_exclusive(db, request.novel_id)
    snapshot = await authorization(db, request.novel_id, request.authorization_id)
    if snapshot.get("task_id") != request.task_id:
        record = await db.get(CreationSuggestion, parse_uuid(request.authorization_id))
        if not any(
            grant.get("task_id") == request.task_id
            and grant.get("owner_id") == snapshot["owner_id"]
            for grant in record.result_ref_json.get("executor_grants", [])
        ):
            raise ValidationError("Focused authorization belongs to another task")
    await require_running_task_attempt(
        db,
        task_id=request.task_id,
        task_type=request.task_type,
        novel_id=request.novel_id,
        lease_id=request.lease_id,
        attempt=request.attempt,
    )
    return snapshot


async def check_sources(db, novel_id, item, snapshot):
    texts = []
    if not item.source_refs:
        raise ValidationError("Focused change requires original manuscript evidence")
    for source in item.source_refs:
        if (
            source.source_type != "manuscript"
            or not source.source_range
            or not source.quote
        ):
            raise ValidationError(
                "Focused change requires an exact manuscript range and quote"
            )
        try:
            ref = SourceRangeRefContract(**source.source_range)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Invalid focused source range") from exc
        if (
            source.source_id != ref.draft_id
            or source.source_hash != ref.source_hash
            or snapshot["source_manifest"].get(ref.draft_id) != ref.source_hash
            or not snapshot["chapter_from"] <= ref.chapter_index <= snapshot["chapter_to"]
        ):
            raise ValidationError("Focused source is outside the authorized manifest")
        read = await read_manuscript_range(db, novel_id, ref, before=0, after=0)
        current = await list_manuscript_sources(
            db, novel_id, [ref.chapter_index], content_mode=ref.content_mode
        )
        if not any(
            str(draft.id) == ref.draft_id and draft.content_hash == ref.source_hash
            for draft in current
        ):
            raise ConflictError("Focused source version is no longer current")
        text = read.text[read.highlight_start : read.highlight_end]
        if text.count(source.quote) != 1:
            raise ValidationError(
                "Focused quote must locate uniquely inside its source range"
            )
        texts.append(text)
    return texts


def _action(item):
    if item.kind == "core_entity":
        return {
            "create": "create_entity",
            "fill_empty": "fill_empty",
            "existing_ref": "reference",
        }.get(item.payload.get("operation", "create"))
    return {"entity_alias": "append_alias", "entity_relation": "create_relation"}.get(
        item.kind
    )


async def valid_direct_relation(db, novel_id, item, root_id):
    from modules.world.services.core.focused_world_read import relation_projection

    proof = item.direct_relation_ref
    if (
        item.depth != 1
        or not root_id
        or not proof
        or set(proof) != {"relation_id", "source_hash"}
    ):
        return False
    target_id = item.payload.get("entity_id") or item.payload.get("entity_ref")
    if not target_id or target_id.startswith("local:"):
        return False
    relation = await db.scalar(
        select(EntityRelation)
        .where(
            EntityRelation.id == parse_uuid(proof["relation_id"]),
            EntityRelation.novel_id == parse_uuid(novel_id),
            EntityRelation.status == "canonical",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return bool(
        relation is not None
        and {str(relation.source_id), str(relation.target_id)}
        == {str(root_id), target_id}
        and relation_projection(relation)["source_hash"] == proof["source_hash"]
    )


async def validate_items(service, db, novel_id, package, snapshot):
    from modules.world.services.core.focused_world_read import _entity, get_terms

    if package.source_manifest_hash != stable_hash(snapshot["source_manifest"]):
        raise ValidationError("Focused source manifest changed")
    if (
        snapshot["root_selection"] == "explicit"
        and package.focused_roots != snapshot["roots"]
    ):
        raise ValidationError("Focused roots changed")

    root_by_key = {root["key"]: root for root in package.focused_roots}
    for item in package.items:
        if item.disposition != "include":
            continue
        try:
            action = _action(item)
            if action != "reference" and action not in snapshot["actions"]:
                raise ValidationError("Change is outside focused write authorization")
            if item.root_key not in root_by_key or item.depth > snapshot["max_depth"]:
                raise ValidationError("Change is outside the authorized roots or depth")
            if (
                item.kind == "entity_relation"
                and item.payload.get("operation", "create") != "create"
            ):
                raise ValidationError(
                    "Focused completion cannot promote existing candidates"
                )
            texts = await check_sources(db, novel_id, item, snapshot)
            root = root_by_key[item.root_key]
            root_name = root.get("name")
            root_terms = [root_name] if root_name else []
            resolved_root_id = root.get("entity_id")
            if root.get("entity_id"):
                entity = await service._canonical_or_candidate_entity(
                    db, novel_id, root["entity_id"], False, allow_canonical=True
                )
                root_name = entity.name
                root_terms = _entity(entity)["terms"]
            elif root_name:
                matches = await get_terms(
                    db, novel_id=novel_id, names=[root_name], include_review=True
                )
                if matches["truncated"] or len(matches["entities"]) > 1:
                    raise ValidationError("Root name has ambiguous identities")
                if matches["entities"]:
                    resolved_root_id = matches["entities"][0]["id"]
                    root_terms = matches["entities"][0]["terms"]
            if not root_terms or not any(
                term in text for term in root_terms for text in texts
            ):
                if not await valid_direct_relation(db, novel_id, item, resolved_root_id):
                    raise ValidationError(
                        "Root identity is not grounded in the supplied evidence"
                    )
            if item.kind == "core_entity" and action == "create_entity":
                entity = item.payload.get("entity") or {}
                if entity.get("content_json") or entity.get("force_create"):
                    raise ValidationError(
                        "Focused creation forbids unverified extension fields"
                    )
                if not any(entity.get("name", "") in text for text in texts):
                    raise ValidationError("New object name is absent from evidence")
                matches = await get_terms(
                    db,
                    novel_id=novel_id,
                    names=[entity.get("name", "")],
                    include_review=True,
                )
                if matches["entities"] or matches["truncated"]:
                    raise ValidationError(
                        "Existing name or alias requires identity review"
                    )
                if item.depth == 0 and entity.get("name") != root_name:
                    raise ValidationError("Depth-zero creation must identify its root")
            if item.kind == "core_entity" and action == "fill_empty":
                entity = await service._canonical_or_candidate_entity(
                    db, novel_id, item.payload["entity_id"], False, allow_canonical=True
                )
                if any(
                    not is_empty(getattr(entity, key)) and getattr(entity, key) != value
                    for key, value in item.payload["fields"].items()
                ):
                    raise ValidationError("Existing content requires author review")
                if item.depth == 0 and str(entity.id) != str(resolved_root_id or ""):
                    raise ValidationError("Depth-zero fill must target its root")
                if not any(
                    term in text for term in _entity(entity)["terms"] for text in texts
                ):
                    raise ValidationError("Fill target identity is absent from evidence")
            if item.kind == "entity_alias":
                alias = item.payload["alias"]
                if not any(alias in text for text in texts):
                    raise ValidationError("Alias text is absent from evidence")
                matches = await get_terms(
                    db, novel_id=novel_id, names=[alias], include_review=True
                )
                if matches["truncated"] or any(
                    row["id"] != item.payload["entity_ref"] for row in matches["entities"]
                ):
                    raise ValidationError("Alias identity requires author review")
            if item.kind == "entity_relation" and not item.payload.get("relation_kind"):
                raise ValidationError("Relation kind requires author review")
            for ref_key in ("entity_ref", "source_ref", "target_ref"):
                ref = item.payload.get(ref_key, "")
                if ref and not ref.startswith("local:"):
                    endpoint = await service._canonical_endpoint(db, novel_id, ref, False)
                    if not any(
                        term in text
                        for term in _entity(endpoint)["terms"]
                        for text in texts
                    ):
                        raise ValidationError("Endpoint identity is absent from evidence")
        except (ValidationError, ConflictError) as exc:
            item.disposition = "open"
            item.review_reasons = [
                str(getattr(exc, "message", "focused_evidence_review_required"))
            ]
    # A local endpoint excluded above cannot be smuggled in by a relation/alias.
    included_keys = {
        item.item_key for item in package.items if item.disposition == "include"
    }
    for item in package.items:
        refs = [
            item.payload.get(key, "")
            for key in ("entity_ref", "source_ref", "target_ref")
        ]
        if any(ref.startswith("local:") and ref[6:] not in included_keys for ref in refs):
            item.disposition = "open"
            item.review_reasons = ["endpoint_requires_review"]


async def submit(service, db, request):
    snapshot = await fence(db, request)
    if request.source_manifest_hash != stable_hash(snapshot["source_manifest"]):
        raise ValidationError("Focused source manifest hash changed")
    if len(request.context_fingerprint) != 64:
        raise ValidationError("Focused context fingerprint is required")
    roots = request.roots or snapshot["roots"]
    if snapshot["root_selection"] == "explicit" and roots != snapshot["roots"]:
        raise ValidationError("Focused roots changed")
    if (
        not roots
        or len(roots) > 1000
        or len({root.get("key") for root in roots}) != len(roots)
    ):
        raise ValidationError("Invalid focused root selection")
    package = WorldAdoptionPackagePayload.model_validate(
        {
            "schema_version": "world_adoption_package.v2",
            "focused_authorization_id": request.authorization_id,
            "focused_roots": roots,
            "context_fingerprint": request.context_fingerprint,
            "source_manifest_hash": request.source_manifest_hash,
            "items": request.items,
        }
    )
    package.focused_request_hash = stable_hash(package.model_dump(mode="json"))
    existing = (
        (
            await db.execute(
                select(CreationSuggestion).where(
                    CreationSuggestion.novel_id == parse_uuid(request.novel_id),
                    CreationSuggestion.target_type == "world_adoption_package",
                    CreationSuggestion.source_module == "imports",
                )
            )
        )
        .scalars()
        .all()
    )
    for candidate in existing:
        if (
            candidate.payload_json.get("focused_request_hash")
            == package.focused_request_hash
        ):
            counts = {
                "included_count": sum(
                    item.get("disposition") == "include"
                    for item in candidate.payload_json["items"]
                ),
                "review_count": sum(
                    item.get("disposition") == "open"
                    for item in candidate.payload_json["items"]
                ),
            }
            if candidate.status == "accepted":
                return {
                    **counts,
                    "suggestion_id": str(candidate.id),
                    "expected_preview_hash": candidate.result_ref_json["preview_hash"],
                    "status": "accepted",
                }
            preview = await service.preview(db, request.novel_id, str(candidate.id))
            return {
                **counts,
                "suggestion_id": str(candidate.id),
                "expected_preview_hash": preview.expected_preview_hash,
                "status": "pending",
            }
    await validate_items(service, db, request.novel_id, package, snapshot)
    saved = await service.save(
        db,
        WorldAdoptionPackageSaveRequest(novel_id=request.novel_id, package=package),
        source_module="imports",
    )
    preview = await service.preview(db, request.novel_id, saved.id)
    return {
        "suggestion_id": saved.id,
        "expected_preview_hash": preview.expected_preview_hash,
        "status": "pending",
        "review_count": sum(item.disposition == "open" for item in package.items),
        "included_count": sum(item.disposition == "include" for item in package.items),
    }


async def apply(service, db, request):
    await fence(db, request)
    suggestion = await service._suggestions._get_suggestion(
        db, request.novel_id, request.suggestion_id
    )
    package = service._package(suggestion)
    if package.focused_authorization_id != request.authorization_id:
        raise ValidationError("Focused package authorization mismatch")
    from modules.world.schemas import WorldAdoptionPackageApplyRequest

    result = await service.apply(
        db,
        request.novel_id,
        request.suggestion_id,
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=request.expected_preview_hash,
            validation_run_id=request.validation_run_id,
        ),
        _focused_request=request,
    )
    return dict(result.result_ref_json)


def entity_state(entity):
    return {
        key: copy.deepcopy(getattr(entity, key))
        for key in (
            "name",
            "entity_type",
            "status",
            "summary",
            "public_info",
            "hidden_truth",
            "content_json",
            "importance",
            "importance_level",
            "reveal_level",
        )
    }


def relation_state(relation):
    return {
        key: copy.deepcopy(getattr(relation, key))
        for key in (
            "status",
            "relation_type",
            "relation_kind",
            "description",
            "quote",
            "review_meta",
        )
    }


async def rollback(service, db, *, novel_id, suggestion_id):
    await require_active_project_exclusive(db, novel_id)
    project = await get_project_context(db, novel_id)
    if not project or project.owner_id != str(current_account_id()):
        raise ValidationError("Rollback requires the project owner")
    suggestion = await db.scalar(
        select(CreationSuggestion)
        .where(
            CreationSuggestion.id == parse_uuid(suggestion_id),
            CreationSuggestion.novel_id == parse_uuid(novel_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        suggestion is None
        or suggestion.status != "accepted"
        or not suggestion.payload_json.get("focused_authorization_id")
    ):
        raise ValidationError("No accepted focused package to roll back")
    receipt = copy.deepcopy(suggestion.result_ref_json)
    outcomes = []
    changed = set()
    for item in reversed(receipt.get("applied_changes", [])):
        if item.get("rolled_back"):
            outcomes.append(
                {"item_key": item["item_key"], "status": "already_rolled_back"}
            )
            continue
        model = EntityRelation if item["kind"] == "entity_relation" else CoreEntity
        obj = await db.scalar(
            select(model)
            .where(
                model.id == parse_uuid(item["id"]), model.novel_id == parse_uuid(novel_id)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = (
            relation_state(obj)
            if obj is not None and model is EntityRelation
            else entity_state(obj)
            if obj is not None
            else None
        )
        # Compare touched fields for fills; complete resources for new assets/aliases.
        after = item["after"]
        matches = current is not None and all(
            current.get(key) == value for key, value in after.items()
        )
        if matches and item["operation"] == "create" and model is CoreEntity:
            external = await db.scalar(
                select(EntityRelation.id)
                .where(
                    EntityRelation.novel_id == parse_uuid(novel_id),
                    EntityRelation.status.in_(("canonical", "candidate")),
                    (EntityRelation.source_id == obj.id)
                    | (EntityRelation.target_id == obj.id),
                )
                .limit(1)
            )
            matches = external is None
            if matches:
                from modules.world.models import WorldBiblePage, WorldBiblePageDraft
                from modules.world.services.core.entity_type_transition_service import (
                    EntityTypeTransitionService,
                )

                blockers = await EntityTypeTransitionService()._collect_blockers(
                    db, obj, obj.entity_type
                )
                matches = not blockers
                for page_model in (WorldBiblePage, WorldBiblePageDraft):
                    linked = await db.scalar(
                        select(page_model.id)
                        .where(
                            page_model.novel_id == obj.novel_id,
                            cast(page_model.linked_asset_refs_json, String).contains(
                                str(obj.id)
                            ),
                        )
                        .limit(1)
                    )
                    if linked is not None:
                        matches = False
        if not matches:
            outcomes.append({"item_key": item["item_key"], "status": "conflict"})
            continue
        if model is CoreEntity:
            from modules.world.services.core.entity_revision_service import (
                EntityRevisionService,
            )

            await EntityRevisionService().create_snapshot(
                db, str(obj.id), novel_id, revision_reason="focused_completion_rollback"
            )
        if item["operation"] == "create":
            obj.status = "deprecated"
        else:
            for key, value in item["before"].items():
                setattr(obj, key, copy.deepcopy(value))
        item["rolled_back"] = True
        outcomes.append({"item_key": item["item_key"], "status": "rolled_back"})
        if model is CoreEntity:
            changed.add(str(obj.id))
        else:
            changed.update((str(obj.source_id), str(obj.target_id)))
    receipt["rollback"] = outcomes
    suggestion.result_ref_json = receipt
    await db.flush()
    if changed:
        await service._mark_context_changed(db, novel_id, changed)
        from modules.world.services.core.entity_activity_invalidation import (
            request_entity_activity_reannotation,
        )

        await request_entity_activity_reannotation(db, novel_id)
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db, novel_id, source_type="focused_rollback", source_id=suggestion_id
        )
    return {"suggestion_id": suggestion_id, "results": outcomes}
