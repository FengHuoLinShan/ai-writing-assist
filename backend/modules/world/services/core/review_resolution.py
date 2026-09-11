"""World-owned frozen candidate inventory and guarded resolution adoption."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from modules.world.models import CoreEntity, EntityRelation
from modules.world.services.worldbuilding.focused_adoption import (
    entity_state,
    relation_state,
    stable_hash,
)
from shared.utils import parse_uuid

RESOLUTION_POLICY = "world.review_resolution.v1"


def _alias_key(entity_id, alias):
    return f"alias-{entity_id}-{stable_hash(alias.casefold().strip())[:16]}"


def _identity(entity):
    return {
        "id": str(entity.id),
        "name": entity.name,
        "entity_type": entity.entity_type,
        "status": entity.status,
        "aliases": [
            item if isinstance(item, str) else item.get("alias", "")
            for item in (entity.content_json or {}).get("aliases", [])
            if isinstance(item, str)
            or item.get("status") in {"canonical", "confirmed", "active"}
        ],
    }


async def candidates(db, novel_id, *, workflow_id=None, keys=None):
    nid = parse_uuid(novel_id)
    entities = list(
        (
            await db.scalars(
                select(CoreEntity)
                .where(
                    CoreEntity.novel_id == nid,
                    CoreEntity.status.in_(("candidate", "canonical", "draft")),
                )
                .order_by(CoreEntity.id)
            )
        ).all()
    )
    by_id = {str(entity.id): entity for entity in entities}
    rows = []
    for entity in entities:
        content = deepcopy(entity.content_json or {})
        meta = dict(content.get("_meta") or {})
        if entity.created_by == "ai_import":
            meta.setdefault("source", "deep_import")
        content.pop("aliases", None)
        content.pop("_meta", None)
        if entity.status == "candidate":
            fields = {
                key: value
                for key, value in {
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "summary": entity.summary,
                    "public_info": entity.public_info,
                    "hidden_truth": entity.hidden_truth,
                    "content_json": content,
                }.items()
                if value not in (None, "", {})
            }
            rows.append(
                {
                    "key": f"entity-{entity.id}",
                    "kind": "entity",
                    "entity_id": str(entity.id),
                    "fields": fields,
                    "identities": [_identity(entity)],
                    "baseline": entity_state(entity),
                    "meta": meta,
                }
            )
        for alias in (entity.content_json or {}).get("aliases", []):
            if not isinstance(alias, dict) or alias.get("status") not in {
                "candidate",
                "pending",
                "conflicted",
            }:
                continue
            text = str(alias.get("alias") or "").strip()
            rows.append(
                {
                    "key": _alias_key(entity.id, text),
                    "kind": "alias",
                    "entity_id": str(entity.id),
                    "fields": {
                        "alias": text,
                        "kind": alias.get("kind") or alias.get("alias_kind") or "",
                        "type": alias.get("type") or alias.get("alias_type") or "name",
                    },
                    "identities": [_identity(entity)],
                    "baseline": {"alias": deepcopy(alias), "identity": _identity(entity)},
                    "meta": {**meta, **alias},
                }
            )
    relations = (
        await db.scalars(
            select(EntityRelation)
            .where(EntityRelation.novel_id == nid, EntityRelation.status == "candidate")
            .order_by(EntityRelation.id)
        )
    ).all()
    for relation in relations:
        endpoints = [
            by_id.get(str(value)) for value in (relation.source_id, relation.target_id)
        ]
        rows.append(
            {
                "key": f"relation-{relation.id}",
                "kind": "relation",
                "relation_id": str(relation.id),
                "entity_id": str(relation.source_id),
                "fields": {
                    "relation_type": relation.relation_type,
                    "relation_kind": relation.relation_kind,
                    "description": relation.description,
                },
                "identities": [_identity(item) for item in endpoints if item is not None],
                "baseline": {
                    **relation_state(relation),
                    "source_id": str(relation.source_id),
                    "target_id": str(relation.target_id),
                    "identities": [
                        _identity(item) for item in endpoints if item is not None
                    ],
                },
                "meta": relation.review_meta or {},
            }
        )
    selected = []
    for row in rows:
        if row["meta"].get("source") != "deep_import":
            continue
        if workflow_id and row["meta"].get("workflow_id") != workflow_id:
            continue
        if keys is not None and row["key"] not in keys:
            continue
        fingerprint_basis = deepcopy(row["baseline"])
        for identity in fingerprint_basis.get(
            "identities", [fingerprint_basis.get("identity", {})]
        ):
            identity.pop("status", None)
        row["fingerprint"] = stable_hash(fingerprint_basis)
        row["required_fields"] = sorted(
            key
            for key, value in row["fields"].items()
            if value not in (None, "", {})
            and key not in {"kind", "type", "relation_kind"}
        )
        row["protected"] = bool(row["meta"].get("user_edited"))
        selected.append(row)
    if len({row["key"] for row in selected}) != len(selected):
        raise ConflictError("重复候选名称需要先确认归属")
    return selected


async def authorize_resolution(
    db, *, novel_id, task_id, source_manifest, chapter_from, chapter_to, items
):
    from modules.world.services.worldbuilding.focused_adoption import authorize

    roots = {
        row["entity_id"]: {
            "key": f"entity:{row['entity_id']}",
            "entity_id": row["entity_id"],
        }
        for row in items
    }
    if not roots:
        raise ValidationError("没有可整理的候选资料")
    return await authorize(
        db,
        novel_id=novel_id,
        roots=list(roots.values()),
        source_manifest=source_manifest,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        task_id=task_id,
        workflow_id=task_id,
        actions=["promote_entity", "promote_relation", "resolve_alias"],
        max_depth=0,
        resolution_scope={
            row["key"]: {
                "fingerprint": row["fingerprint"],
                "required_fields": row["required_fields"],
            }
            for row in items
        },
    )


async def validate_resolution_item(service, db, novel_id, item, snapshot):
    """Only a versioned resolution grant can promote an existing candidate."""
    from modules.world.services.worldbuilding.focused_adoption import check_sources

    frozen = snapshot.get("resolution_scope", {}).get(item.item_key)
    if not frozen:
        raise ValidationError("候选不在本次整理授权中")
    current = await candidates(db, novel_id, keys={item.item_key})
    if len(current) != 1 or current[0]["fingerprint"] != frozen["fingerprint"]:
        raise ConflictError("资料已变化，请重新整理")
    row = current[0]
    action = {
        "entity": "promote_entity",
        "relation": "promote_relation",
        "alias": "resolve_alias",
    }[row["kind"]]
    if (
        action not in snapshot["actions"]
        or item.root_key != f"entity:{row['entity_id']}"
        or item.depth != 0
    ):
        raise ValidationError("操作不在本次整理授权中")
    if row["protected"]:
        raise ConflictError("作者已编辑的资料需要确认")
    texts = await check_sources(db, novel_id, item, snapshot)
    if any(
        not any(
            identity["name"] in text
            or any(alias in text for alias in identity["aliases"])
            for text in texts
        )
        for identity in row["identities"]
    ):
        raise ValidationError("证据中未确认资料身份")
    if row["kind"] == "entity":
        if (
            item.kind != "core_entity"
            or item.payload.get("operation") != "promote"
            or item.payload.get("entity_id") != row["entity_id"]
        ):
            raise ValidationError("整理不能改写候选内容")
    elif row["kind"] == "relation":
        if len(row["identities"]) != 2 or any(
            identity["status"] != "canonical" for identity in row["identities"]
        ):
            raise ConflictError("先确认关系两端对象")
        if (
            item.kind != "entity_relation"
            or item.payload.get("operation") != "promote"
            or item.payload.get("relation_id") != row["relation_id"]
            or item.payload.get("source_ref") != row["baseline"]["source_id"]
            or item.payload.get("target_ref") != row["baseline"]["target_id"]
            or item.payload.get("relation_type") != row["fields"]["relation_type"]
            or item.payload.get("relation_kind") != row["fields"]["relation_kind"]
            or item.payload.get("description") != row["fields"]["description"]
        ):
            raise ValidationError("整理不能改变关系身份")
        if row["meta"].get("claim_status") in {"changed", "ended"} or row["meta"].get(
            "persistence_scope"
        ) in {"episodic", "uncertain"}:
            raise ValidationError("关系变化需要作者决定")
    else:
        if (
            row["identities"][0]["status"] != "canonical"
            or row["fields"]["kind"] == "identity"
        ):
            raise ConflictError("别名身份需要作者决定")
        if (
            item.kind != "entity_alias"
            or item.payload.get("entity_ref") != row["entity_id"]
            or item.payload.get("alias") != row["fields"]["alias"]
            or not any(row["fields"]["alias"] in text for text in texts)
        ):
            raise ValidationError("别名不在已查证范围中")
    if not item.review_evidence or set(item.review_evidence) != set(
        frozen["required_fields"]
    ):
        raise ValidationError("必须核实所有待采用字段")
    supplied = {ref.quote for ref in item.source_refs}
    if any(
        not quotes or any(quote not in supplied for quote in quotes)
        for quotes in item.review_evidence.values()
    ):
        raise ValidationError("字段证据缺失或未校验")


async def prepare_manual_decision(db, *, novel_id, task_id, rows):
    from modules.world.schemas import (
        WorldAdoptionPackagePayload,
        WorldAdoptionPackageSaveRequest,
    )
    from modules.world.services.core.review_queue import (
        default_alias_kind,
        default_relation_kind,
    )
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )

    current = {
        row["key"]: row
        for row in await candidates(db, novel_id, keys={row["key"] for row in rows})
    }
    items = []
    for row in rows:
        if (
            row["key"] not in current
            or current[row["key"]]["fingerprint"] != row["fingerprint"]
        ):
            raise ConflictError("资料已变化，请重新查看后决定")
        fields = row["fields"]
        if row["kind"] == "entity":
            payload = {"operation": "promote", "entity_id": row["entity_id"]}
        elif row["kind"] == "relation":
            kind = fields["relation_kind"] or default_relation_kind(
                fields["relation_type"]
            )
            if not kind:
                raise ValidationError("此关系需要先在详细审阅中确认分类")
            payload = {
                "operation": "promote",
                "relation_id": row["relation_id"],
                "source_ref": row["baseline"]["source_id"],
                "target_ref": row["baseline"]["target_id"],
                "relation_type": fields["relation_type"],
                "relation_kind": kind,
                "description": fields["description"],
            }
        else:
            kind = fields["kind"] or default_alias_kind(fields["type"])
            if not kind:
                raise ValidationError("此别名需要先在详细审阅中确认分类")
            payload = {
                "entity_ref": row["entity_id"],
                "alias": fields["alias"],
                "alias_kind": kind,
                "alias_type": fields["type"],
                "candidate_fingerprint": row["fingerprint"],
            }
        item = {
            "item_key": row["key"],
            "kind": {
                "entity": "core_entity",
                "relation": "entity_relation",
                "alias": "entity_alias",
            }[row["kind"]],
            "disposition": "include",
            "authority_kind": "author_seed",
            "source_refs": [
                {
                    "source_type": "author_decision",
                    "source_id": task_id,
                    "source_hash": stable_hash(
                        {
                            "candidate_key": row["key"],
                            "fingerprint": row["fingerprint"],
                            "action": "accept",
                        }
                    ),
                }
            ],
            "payload": payload,
        }
        if row["kind"] == "entity":
            item["baseline"] = {"expected_status": "candidate"}
        items.append(item)
    local_entities = {
        row["entity_id"]: row["key"] for row in rows if row["kind"] == "entity"
    }
    for item in items:
        for key in ("entity_ref", "source_ref", "target_ref"):
            ref = item["payload"].get(key)
            if ref in local_entities:
                item["payload"][key] = "local:" + local_entities[ref]
    service = WorldAdoptionPackageService()
    saved = await service.save(
        db,
        WorldAdoptionPackageSaveRequest(
            novel_id=novel_id,
            package=WorldAdoptionPackagePayload(
                schema_version="world_adoption_package.v2",
                source_manifest_hash=stable_hash({"task": task_id, "items": items}),
                review_resolution_run=task_id,
                items=items,
            ),
        ),
        source_module="imports",
    )
    preview = await service.preview(db, novel_id, saved.id)
    return {
        "suggestion_id": saved.id,
        "expected_preview_hash": preview.expected_preview_hash,
    }


async def apply_manual_decision(db, *, novel_id, package):
    from modules.world.schemas import WorldAdoptionPackageApplyRequest
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )

    result = await WorldAdoptionPackageService().apply(
        db,
        novel_id,
        package["suggestion_id"],
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=package["expected_preview_hash"]
        ),
    )
    return result.result_ref_json


async def resolve_redundant_alias(db, *, request, candidate_key):
    from modules.world.models import CreationSuggestion
    from modules.world.services.core.entity_alias_service import EntityAliasService
    from modules.world.services.core.entity_revision_service import EntityRevisionService
    from modules.world.services.worldbuilding.focused_adoption import fence

    snapshot = await fence(db, request)
    if snapshot.get("policy") != RESOLUTION_POLICY:
        raise ValidationError("原授权不包含候选整理")
    existing = (
        await db.scalars(
            select(CreationSuggestion).where(
                CreationSuggestion.novel_id == parse_uuid(request.novel_id),
                CreationSuggestion.target_type == "world_adoption_package",
                CreationSuggestion.status == "accepted",
            )
        )
    ).all()
    for saved in existing:
        if (
            saved.result_ref_json.get("redundant_candidate") == candidate_key
            and saved.payload_json.get("focused_authorization_id")
            == request.authorization_id
        ):
            return {"suggestion_id": str(saved.id), "status": "accepted"}
    rows = await candidates(db, request.novel_id, keys={candidate_key})
    if len(rows) != 1:
        return None
    row = rows[0]
    frozen = snapshot.get("resolution_scope", {}).get(candidate_key)
    if not frozen or frozen["fingerprint"] != row["fingerprint"]:
        raise ConflictError("候选已变化")
    if (
        row["kind"] != "alias"
        or row["protected"]
        or row["identities"][0]["status"] != "canonical"
    ):
        return None
    identity = row["identities"][0]
    if row["fields"]["alias"].strip().casefold() != identity["name"].strip().casefold():
        return None
    entity = await db.scalar(
        select(CoreEntity)
        .where(
            CoreEntity.novel_id == parse_uuid(request.novel_id),
            CoreEntity.id == parse_uuid(row["entity_id"]),
        )
        .with_for_update()
    )
    before = {"content_json": deepcopy(entity.content_json)}
    await EntityRevisionService().create_snapshot(
        db,
        row["entity_id"],
        request.novel_id,
        revision_reason="redundant_alias_resolution",
    )
    await EntityAliasService().update_alias(
        db,
        request.novel_id,
        row["entity_id"],
        row["fields"]["alias"],
        {
            "status": "ignored",
            "needs_review": False,
            "resolution_reason": "same_as_canonical_name",
            "resolution_workflow_id": request.task_id,
        },
    )
    item = {
        "item_key": candidate_key,
        "kind": "entity_alias",
        "disposition": "rejected",
        "authority_kind": "canonical_baseline",
        "source_refs": [
            {
                "source_type": "core_entity",
                "source_id": row["entity_id"],
                "source_hash": row["fingerprint"],
            }
        ],
        "payload": {
            "entity_ref": row["entity_id"],
            "alias": row["fields"]["alias"],
            "alias_kind": "name",
            "alias_type": "name",
        },
    }
    saved = CreationSuggestion(
        novel_id=parse_uuid(request.novel_id),
        source_module="imports",
        review_group="world_adoption",
        target_type="world_adoption_package",
        action_schema="world_adoption_package.v2",
        payload_json={
            "schema_version": "world_adoption_package.v2",
            "focused_authorization_id": request.authorization_id,
            "context_fingerprint": request.context_fingerprint,
            "source_manifest_hash": request.source_manifest_hash,
            "items": [item],
        },
        evidence_refs_json=item["source_refs"],
        result_ref_json={
            "redundant_candidate": candidate_key,
            "applied_changes": [
                {
                    "item_key": candidate_key,
                    "kind": "entity_alias",
                    "id": row["entity_id"],
                    "operation": "resolve_redundancy",
                    "before": before,
                    "after": {"content_json": deepcopy(entity.content_json)},
                }
            ],
        },
        risk_level="low",
        status="accepted",
    )
    db.add(saved)
    await db.flush()
    return {"suggestion_id": str(saved.id), "status": "accepted"}
