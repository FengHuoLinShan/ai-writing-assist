"""Narrow author-only read projection for Evidence object-pattern briefs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from uuid import UUID

from sqlalchemy import func, select

from core.container import get
from core.service_keys import STORY_SCENE_SOURCE
from infrastructure.llm.collaboration import content_hash
from modules.evolution.ledger import (
    _claim_ranges_current,
    _identity_status,
    claim_freshness,
)
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.models import EvolutionLedgerEntry, EvolutionLedgerRevision
from modules.project.facade import require_active_project

_PATTERN_CATEGORIES = frozenset(
    {"conditional_behavior", "language_habit", "external_appearance"}
)
_MAX_LEDGER_ROWS = 500


def _mapping(value):
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else {}


async def _current_scene_index(
    db, novel_id: str, scene_id: str, cache: dict
) -> int | None:
    if scene_id not in cache:
        scene = await get(STORY_SCENE_SOURCE).get_scene_contract(db, novel_id, scene_id)
        payload = _mapping(scene)
        index = payload.get("scene_index")
        cache[scene_id] = (
            int(index)
            if scene is not None
            and isinstance(index, int)
            and not isinstance(index, bool)
            else None
        )
    return cache[scene_id]


async def read_evolution_object_patterns(
    db,
    *,
    novel_id: str,
    scene_id: str,
    entity_ids: list[str],
    only_adopted: bool = False,
) -> dict:
    """Read current, source-valid history patterns at a server-resolved Scene cutoff.

    This projection is deliberately not a World/Story fact writer. Quotes and raw
    source text are never returned; callers receive stable source coordinates only.
    """
    novel_id = str(UUID(str(novel_id)))
    scene_id = str(UUID(str(scene_id)))
    requested_ids = sorted({str(UUID(str(value))) for value in entity_ids})
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    if not requested_ids:
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": None,
            "items": [],
            "omitted_count": 0,
            "omissions": ["未指定对象"],
            "coverage": "unknown",
            "ledger_fingerprint": content_hash([novel_id, scene_id, "empty"]),
        }

    scene_port = get(STORY_SCENE_SOURCE)
    scene = _mapping(await scene_port.get_scene_contract(db, novel_id, scene_id))
    scene_index = scene.get("scene_index")
    if not scene or not isinstance(scene_index, int) or isinstance(scene_index, bool):
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": None,
            "items": [],
            "omitted_count": 0,
            "omissions": ["Scene 不存在或当前顺序未知，未读取台账"],
            "coverage": "unknown",
            "ledger_fingerprint": content_hash([novel_id, scene_id, "scene_unknown"]),
        }

    state_view = await scene_port.get_scene_state_view(
        db,
        novel_id,
        scene_id,
        viewpoint={"kind": "author"},
    )
    state_payload = _mapping(state_view)
    checkpoint_index = state_payload.get("scene_index")
    if (
        str(state_payload.get("scene_id") or "") != scene_id
        or checkpoint_index != scene_index
    ):
        return {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "items": [],
            "omitted_count": 0,
            "omissions": ["Story checkpoint cutoff 与当前 Scene 顺序不一致"],
            "coverage": "unknown",
            "ledger_fingerprint": content_hash(
                [novel_id, scene_id, scene_index, "checkpoint_mismatch"]
            ),
        }

    nid = UUID(novel_id)
    ranked = (
        select(
            EvolutionLedgerRevision.id,
            func.row_number()
            .over(
                partition_by=EvolutionLedgerRevision.entry_id,
                order_by=EvolutionLedgerRevision.revision.desc(),
            )
            .label("position"),
        )
        .where(
            EvolutionLedgerRevision.novel_id == nid,
            EvolutionLedgerRevision.scene_index <= scene_index,
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(EvolutionLedgerRevision, EvolutionLedgerEntry)
            .join(
                EvolutionLedgerEntry,
                EvolutionLedgerEntry.id == EvolutionLedgerRevision.entry_id,
            )
            .join(ranked, ranked.c.id == EvolutionLedgerRevision.id)
            .where(ranked.c.position == 1)
            .order_by(
                EvolutionLedgerRevision.scene_index.desc(),
                EvolutionLedgerRevision.id,
            )
            .limit(_MAX_LEDGER_ROWS + 1)
        )
    ).all()
    truncated = len(rows) > _MAX_LEDGER_ROWS
    rows = rows[:_MAX_LEDGER_ROWS]
    index_cache: dict[str, int | None] = {scene_id: int(scene_index)}
    items = []
    omissions: list[str] = ["台账候选超过读取上限"] if truncated else []
    omitted_count = 1 if truncated else 0

    for revision, entry in rows:
        if entry.category not in _PATTERN_CATEGORIES:
            continue
        try:
            claim = LedgerClaim.model_validate((revision.body_json or {}).get("claim"))
        except (TypeError, ValueError):
            omitted_count += 1
            omissions.append("存在无法校验的台账主张")
            continue
        targets = [
            target
            for target in claim.targets
            if target.domain == "world"
            and target.kind == "entity"
            and target.binding == "resolved"
            and str(target.target_id) in requested_ids
        ]
        if not targets or claim.realm != "history":
            continue

        current_positions: list[int] = []
        unresolved_scope = False
        for dependency in claim.dependencies:
            current_index = await _current_scene_index(
                db, novel_id, str(dependency.scene_id), index_cache
            )
            if current_index is None or current_index != dependency.scene_index:
                unresolved_scope = True
                break
            current_positions.append(current_index)
        if unresolved_scope:
            omitted_count += 1
            omissions.append("台账来源 Scene 身份或顺序已变化")
            continue
        for evidence in claim.evidence:
            source_scene_id = evidence.position.scene_id
            if not source_scene_id:
                unresolved_scope = True
                break
            current_index = await _current_scene_index(
                db, novel_id, source_scene_id, index_cache
            )
            if (
                current_index is None
                or evidence.position.scene_index is not None
                and current_index != evidence.position.scene_index
            ):
                unresolved_scope = True
                break
            if current_index > scene_index:
                unresolved_scope = True
                break
            current_positions.append(current_index)
        if (
            unresolved_scope
            or not current_positions
            or max(current_positions) > scene_index
        ):
            omitted_count += 1
            omissions.append("台账来源超出截止 Scene 或缺少可验证锚点")
            continue

        review = (revision.body_json or {}).get("review") or {}
        decision = (revision.body_json or {}).get("author_decision") or {}
        decision_key = str(decision.get("decision") or "")
        adopted = decision_key in {"keep", "corrected"}
        if decision_key in {"reject", "unreviewed"} and not adopted:
            continue
        if review.get("verdict") != "supported" and not adopted:
            continue
        if only_adopted and not adopted:
            continue
        if (revision.body_json or {}).get("proposal_target"):
            continue
        if await _identity_status(db, novel_id, claim) != "current":
            omitted_count += 1
            omissions.append("台账对象身份未能重新核实")
            continue
        if (
            await claim_freshness(db, novel_id, claim) != "current"
            or await _claim_ranges_current(db, novel_id, claim) != "current"
        ):
            omitted_count += 1
            omissions.append("台账证据已失效或无法重新核验")
            continue

        target_ids = sorted({str(target.target_id) for target in targets})
        statement = str(decision.get("corrected_statement") or claim.statement)
        evidence_refs = [
            {
                "observation_id": item.observation_id,
                "scene_id": item.position.scene_id,
                "scene_index": index_cache.get(str(item.position.scene_id)),
                "chapter_index": item.position.chapter_index,
                "modality": item.modality,
                "role": item.role,
                "source": {
                    "draft_id": item.source_ref.draft_id,
                    "content_hash": item.source_ref.content_hash,
                    "start_offset": item.source_ref.start_offset,
                    "end_offset": item.source_ref.end_offset,
                    "source_visibility": item.source_ref.source_visibility,
                },
            }
            for item in claim.evidence
        ]
        items.append(
            {
                "entry_id": str(entry.id),
                "revision_id": str(revision.id),
                "revision": revision.revision,
                "entity_ids": target_ids,
                "category": claim.category,
                "statement": statement,
                "conditions": list(claim.conditions),
                "modality": claim.modality,
                "confidence": claim.confidence,
                "competing_explanations": list(claim.competing_explanations),
                "review_verdict": str(review.get("verdict") or ""),
                "author_decision": decision_key or None,
                "evidence_refs": evidence_refs,
                "interpretation_only": True,
            }
        )

    items.sort(key=lambda item: (item["entity_ids"], item["category"], item["entry_id"]))
    fingerprint = content_hash(
        {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "only_adopted": only_adopted,
            "items": items,
            "omitted_count": omitted_count,
        }
    )
    return {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "scene_index": scene_index,
        "checkpoint_identities": sorted(
            {
                str(fact.source.get("checkpoint_id"))
                for dimension in state_payload.get("dimensions") or []
                for fact in dimension.get("facts") or []
                if isinstance(fact, dict) and fact.get("source", {}).get("checkpoint_id")
            }
        ),
        "checkpoint_fingerprint": str(state_payload.get("state_fingerprint") or ""),
        "items": items,
        "omitted_count": omitted_count,
        "omissions": list(dict.fromkeys(omissions)),
        "coverage": "partial" if omitted_count else "complete",
        "ledger_fingerprint": fingerprint,
    }
