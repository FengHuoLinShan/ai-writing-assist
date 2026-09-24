"""Scene-local World candidates; Evolution owns provider calls and transactions."""

from collections import Counter

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from modules.imports.contracts import SceneWorldIdentityChangedError
from modules.imports.entity_extraction.scene_entity_persistence import (
    SceneEntityPersistenceMixin,
    entity_key,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    SceneEntityExtractionOutput,
)
from modules.world.facade import find_exact_identity_candidates


async def identity_context(db, novel_id, terms):
    """Only identity labels enter the prompt, never later World descriptions."""
    queries, candidates, mapping = [], [], {}
    for entity_type, name in sorted(set(terms)):
        matches = await find_exact_identity_candidates(db, novel_id, name, entity_type)
        rows = sorted(
            (str(item.existing_entity_id), item.existing_entity_name) for item in matches
        )
        queries.append({"name": name, "entity_type": entity_type, "matches": rows})
        for entity_id, canonical_name in rows:
            ref = f"existing_{entity_id}"
            if ref not in mapping:
                candidates.append(
                    {
                        "prompt_ref": ref,
                        "name": canonical_name,
                        "entity_type": entity_type,
                        "aliases": [],
                    }
                )
                mapping[ref] = entity_id
    return {
        "identity_candidates": candidates,
        "_entity_ref_map": mapping,
        "_identity_queries": queries,
    }


async def require_current_identities(db, novel_id, context):
    for queries in (
        context["_identity_queries"],
        context.get("_initial_identity_queries", []),
    ):
        terms = [(item["entity_type"], item["name"]) for item in queries]
        current = await identity_context(db, novel_id, terms)
        if content_hash(current["_identity_queries"]) != content_hash(queries):
            raise SceneWorldIdentityChangedError(
                "世界对象身份已变化，请保留结果并重新核对"
            )


def blocked_identity_ids(context, world):
    queries = context["_identity_queries"]
    new_names = {
        entity_key(item["entity_type"], item["name"])
        for item in world["entities"]
        if item["suggested_action"] == "create_new"
    }
    return {
        match[0]
        for item in queries
        if len(item["matches"]) > 1
        or entity_key(item["entity_type"], item["name"]) in new_names
        for match in item["matches"]
    }


def ambiguous_new_names(world):
    counts = Counter(
        entity_key(item["entity_type"], item["name"])
        for item in world["entities"]
        if item["suggested_action"] == "create_new"
    )
    return {key for key, count in counts.items() if count > 1}


def relation_context(context, world):
    """Uncommitted new candidates get local refs, resolved only in the final UoW."""
    ambiguous_ids = blocked_identity_ids(context, world)
    candidates = [
        item
        for item in context["identity_candidates"]
        if context["_entity_ref_map"][item["prompt_ref"]] not in ambiguous_ids
    ]
    new_refs = {}
    ambiguous = ambiguous_new_names(world)
    known = {
        entity_key(item["entity_type"], item["name"])
        for item in context["identity_candidates"]
    }
    for index, entity in enumerate(world["entities"]):
        key = entity_key(entity["entity_type"], entity["name"])
        if entity["suggested_action"] != "create_new" or key in known or key in ambiguous:
            continue
        ref = f"new_{index}"
        new_refs[ref] = index
        candidates.append(
            {
                "prompt_ref": ref,
                "name": entity["name"],
                "entity_type": entity["entity_type"],
                "aliases": [],
            }
        )
        known.add(key)
    allowed = {item["prompt_ref"] for item in candidates}
    return {
        **context,
        "identity_candidates": candidates,
        "_new_entity_refs": new_refs,
        "_entity_ref_map": {
            ref: value
            for ref, value in context["_entity_ref_map"].items()
            if ref in allowed
        },
    }


async def apply_world_candidates(
    db,
    novel_id,
    *,
    scene_id,
    scene_index,
    chapter_index,
    workflow_id,
    attempt_id,
    world,
    relations,
    context,
    review,
):
    """No canon or state writes; errors abort the caller's receipt transaction."""
    await require_current_identities(db, novel_id, context)
    if review and review["status"] != "passed":
        return {"result_refs": [], "pending": ["scene_world_requires_review"]}
    output = SceneEntityExtractionOutput.model_validate(world)
    persistence = SceneEntityPersistenceMixin()
    provenance = {"evolution_ref": {"run_key": workflow_id, "attempt_id": attempt_id}}
    refs, pending, by_index, by_key = [], [], {}, {}
    queries = {
        entity_key(item["entity_type"], item["name"]): item["matches"]
        for item in context["_identity_queries"]
    }
    blocked_ids = blocked_identity_ids(context, world)
    ambiguous = ambiguous_new_names(world)
    for index, entity in enumerate(output.entities):
        if entity.suggested_action in {"ignore", "temporary_only"}:
            pending.append(f"world_identity:{index}")
            continue
        key = entity_key(entity.entity_type, entity.name)
        matches = queries[key]
        # A model choosing among identical names is not identity authorization.
        if (
            key in ambiguous
            or len(matches) > 1
            or any(match[0] in blocked_ids for match in matches)
        ):
            pending.append(f"world_identity_ambiguous:{index}")
            continue
        if key in by_key:
            by_index[index] = by_key[key]
            continue
        if matches and any(
            getattr(entity, field) for field in ("summary", "public_info", "hidden_truth")
        ):
            pending.append(f"world_fields_require_review:{index}")
        item_refs = []
        try:
            await persistence._persist_entities(
                db,
                novel_id,
                [entity],
                scene_index,
                chapter_index,
                workflow_id=workflow_id,
                scene_id=scene_id,
                result_refs=item_refs,
                strict=True,
                provenance=provenance,
                identity_matches={key: matches[0][0] if matches else None},
                candidate_id=next(
                    (
                        value
                        for ref, value in context.get("_new_entity_ids", {}).items()
                        if context["_new_entity_refs"][ref] == index
                    ),
                    None,
                ),
            )
        except ConflictError:
            # A domain duplicate confirmation is pending; DB failures still propagate.
            pending.append(f"world_duplicate_requires_confirmation:{index}")
            continue
        if item_refs:
            by_index[index] = by_key[key] = item_refs[0]["id"]
            refs.extend(item_refs)
    mapping = {
        **context["_entity_ref_map"],
        **{
            ref: by_index[index]
            for ref, index in context["_new_entity_refs"].items()
            if index in by_index
        },
    }
    if any(
        mapping.get(ref) != entity_id
        for ref, entity_id in context.get("_new_entity_ids", {}).items()
    ):
        raise SceneWorldIdentityChangedError(
            "本场新身份未能创建，请核对重复对象后重新准备"
        )
    result = await persistence._persist_alias_relation_output(
        db,
        novel_id,
        AliasRelationExtractionOutput.model_validate(relations),
        scene_index=scene_index,
        source_chapter_index=chapter_index,
        workflow_id=workflow_id,
        scene_id=scene_id,
        result_refs=refs,
        strict=True,
        provenance=provenance,
        context_bundle={**context, "_entity_ref_map": mapping},
        current_scene_text=context["_current_scene_text"],
    )
    if output.uncertain_items or result["uncertain_count"]:
        pending.append("scene_world_uncertainties")
    # Phase2a deltas are proposals only; the independent state gate is the owner.
    if output.delta_events:
        pending.append("scene_world_delta_proposals")
    if refs:
        pending.append("scene_world_candidates_require_adoption")
    return {
        "result_refs": refs,
        "pending": pending,
        "diagnostics": result["diagnostics"],
        "relation_snapshots": result["relation_snapshots"],
    }
