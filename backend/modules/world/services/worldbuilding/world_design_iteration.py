"""Immutable world-design revisions using the existing checkpoint carrier."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from core.errors import ValidationError
from modules.world.schemas import (
    WorldDesignCheckpointPayload,
    WorldDesignRevisionRequest,
)


def _identity(item: dict) -> str:
    if "id" in item:
        return item["id"]
    return ":".join(item[key] for key in ("from", "to", "kind"))


def _merge_entries(before: list[dict], updates: list[dict]) -> list[dict]:
    identities = [_identity(item) for item in updates]
    if len(identities) != len(set(identities)):
        raise ValidationError("本轮变化包含重复身份，请合并后保存")
    items = {_identity(item): item for item in before}
    items.update(zip(identities, updates, strict=True))
    return list(items.values())


def _evidence(value):
    if isinstance(value, dict):
        yield from value.get("evidence", [])
        for key, child in value.items():
            if key != "evidence":
                yield from _evidence(child)
    elif isinstance(value, list):
        for child in value:
            yield from _evidence(child)


def _check_proposal(value, evidence: set[str]) -> None:
    if isinstance(value, dict):
        if value.get("status") in {"canon", "valid"}:
            raise ValidationError("本轮推演只能提出候选，不能声明正式采用或验证有效")
        if set(value.get("evidence", [])) - evidence:
            raise ValidationError("本轮变化引用了未确认的来源")
        for child in value.values():
            _check_proposal(child, evidence)
    elif isinstance(value, list):
        for child in value:
            _check_proposal(child, evidence)


def revise_world_design(
    parent: WorldDesignCheckpointPayload,
    request: WorldDesignRevisionRequest,
) -> WorldDesignCheckpointPayload:
    """Merge only explicit entries; recompute lineage and invalidate dependents."""
    state = parent.world_state.model_dump(mode="json", by_alias=True)
    changes = request.changes.model_dump(mode="json", by_alias=True, exclude_none=True)
    replacements = {}
    for section in ("rules", "actors", "places", "institutions", "history"):
        for item in changes[section]:
            if item["id"].startswith("new:"):
                replacements[item["id"]] = (
                    f"{section}:{uuid.uuid5(request.parent_checkpoint_id, item['id'])}"
                )

    def resolve_refs(value, field=""):
        if isinstance(value, dict):
            return {key: resolve_refs(child, key) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve_refs(child, field) for child in value]
        if isinstance(value, str) and field in {
            "id",
            "from",
            "to",
            "dependencies",
            "actors",
            "artifacts",
            "nodes",
        }:
            return replacements.get(value, value)
        return value

    changes = resolve_refs(changes)
    allowed_evidence = set(_evidence(state)) | {
        seed.source_ref.source_id for seed in parent.seeds
    }
    if request.context_confirmation_id:
        allowed_evidence.add(f"confirmation:{request.context_confirmation_id}")
    _check_proposal(changes, allowed_evidence)
    changed: set[str] = set()
    for section, updates in changes.items():
        if not updates:
            continue
        before = state[section]
        if section == "premise":
            state[section] = updates
            if before != updates:
                changed.add(state["project"]["id"])
        elif isinstance(before, list):
            old = {_identity(item): item for item in before}
            changed.update(
                _identity(item) for item in updates if old.get(_identity(item)) != item
            )
            state[section] = _merge_entries(before, updates)
        else:
            for key, value in updates.items():
                if isinstance(before[key], list):
                    old = {_identity(item): item for item in before[key]}
                    changed.update(
                        _identity(item)
                        for item in value
                        if old.get(_identity(item)) != item
                    )
                    before[key] = _merge_entries(before[key], value)
                elif before[key] != value:
                    before[key] = value
                    changed.add(f"{section}:{key}")

    old_decisions = {
        item.item_key: item.model_dump(mode="json") for item in parent.decisions
    }
    decision_updates = [item.model_dump(mode="json") for item in request.decisions]
    if len({item["item_key"] for item in decision_updates}) != len(decision_updates):
        raise ValidationError("作者决定包含重复身份")
    for item in decision_updates:
        if set(item["source_keys"]) - allowed_evidence:
            raise ValidationError("作者决定引用了未确认的来源")
        if old_decisions.get(item["item_key"]) != item:
            changed.add(f"decision:{item['item_key']}")
        old_decisions[item["item_key"]] = item
    decisions = list(old_decisions.values())
    if decision_updates:
        # Replace checkpoint decisions while preserving imported authority entries.
        previous_texts = {item.text for item in parent.decisions}
        authority = state["authority"]
        for group, disposition in (
            ("locked_decisions", "locked"),
            ("open_questions", "open"),
        ):
            authority[group] = [
                item
                for item in authority[group]
                if item["question"] not in previous_texts
            ]
            authority[group].extend(
                {
                    "id": f"decision:{item['item_key']}",
                    "question": item["text"],
                    "status": "author-required" if disposition == "open" else "proposed",
                    "evidence": item["source_keys"],
                }
                for item in decisions
                if item["disposition"] == disposition
            )
        previous_rejected = {
            item.text for item in parent.decisions if item.disposition == "rejected"
        }
        authority["constraints"] = list(
            dict.fromkeys(
                [
                    *(
                        text
                        for text in authority["constraints"]
                        if text not in previous_rejected
                    ),
                    *(
                        item["text"]
                        for item in decisions
                        if item["disposition"] == "rejected"
                    ),
                ]
            )
        )

    affected = set(changed)
    # ponytail: bounded checkpoint graph (512 edges); use adjacency if this cap grows.
    while True:
        following = {
            edge["from"]
            for edge in state["dependencies"]
            if edge["status"] != "deprecated" and edge["to"] in affected
        }
        following.update(
            item["id"]
            for item in [*state["rules"], *state["facets"]]
            if set(item.get("dependencies", [])) & affected
        )
        if following <= affected:
            break
        affected.update(following)
    for section in ("facets", "coupling_chains"):
        for item in state[section]:
            if item["id"] in affected and item["id"] not in changed:
                item["status"] = "partial" if item["evidence"] else "gap"
                item["reason"] = "依赖已变化，旧记录保留，需重新检查"
    for item in state["pressure_tests"]:
        if item["id"] in affected and item["id"] not in changed:
            item["status"] = "not-run"
    invalidated = []
    for name, pipeline in state["fiction_core"].items():
        if set(pipeline["artifacts"]) & affected:
            pipeline["status"] = "needs-review"
            pipeline["invalidated_by"] = sorted(
                set(pipeline["invalidated_by"]) | (set(pipeline["artifacts"]) & affected)
            )
            invalidated.append(name)
    if changed:
        state["audit"]["valid"] = None

    depth = request.depth or parent.depth
    active_rules = [rule for rule in state["rules"] if rule["status"] != "deprecated"]
    if depth in {"candidate", "instance"}:
        if (
            not active_rules
            or not any(rule["evidence"] and rule["costs"] for rule in active_rules)
            or not any(
                item["evidence"] and item["scenario"]
                for item in state["situated_tests"].values()
            )
        ):
            raise ValidationError(
                "进入候选阶段需要有来源的规则、代价与具体生活推演；可以保留当前阶段保存"
            )
    if depth == "instance" and not any(
        item["evidence"] and item["summary"] and item["status"] != "deprecated"
        for section in ("actors", "places", "institutions")
        for item in state[section]
    ):
        raise ValidationError("实例阶段需要有来源的具体人物、地点或制度实例")
    digest = hashlib.sha256(
        json.dumps(
            {
                "parent": str(request.parent_checkpoint_id),
                "source": parent.source_manifest_hash,
                "request": request.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    state["change_log"].append(
        {
            "id": f"change:{uuid.uuid4()}",
            "at": datetime.now(UTC).isoformat(),
            "summary": request.summary,
            "source": digest,
            "authority": "proposed",
            "changed_ids": sorted(changed),
            "invalidated_layers": invalidated,
        }
    )
    state["extensions"].setdefault("iteration", {}).update(
        {
            "depth": depth,
            "round_no": parent.round_no + 1,
            "action": request.action,
        }
    )
    payload = parent.model_dump(mode="json", by_alias=True)
    payload.update(
        world_state=state,
        parent_checkpoint_id=str(request.parent_checkpoint_id),
        source_manifest_hash=digest,
        depth=depth,
        round_no=parent.round_no + 1,
        action=request.action,
        decisions=decisions,
        world_core=None,
        decision_state=None,
    )
    return WorldDesignCheckpointPayload.model_validate(payload)
