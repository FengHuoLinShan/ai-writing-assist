"""Immutable world-design revisions using the existing checkpoint carrier."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime

from core.errors import ValidationError
from infrastructure.stable_hash import stable_hash
from modules.world.schemas import (
    WorldDesignChanges,
    WorldDesignCheckpointPayload,
    WorldDesignRevisionRequest,
)


def _identity(item: dict) -> str:
    if "id" in item:
        return item["id"]
    return ":".join(item[key] for key in ("from", "to", "kind"))


def _merge_fields(before: dict, update: dict) -> dict:
    result = deepcopy(before)
    for key, value in update.items():
        result[key] = (
            _merge_fields(before.get(key, {}), value)
            if isinstance(value, dict)
            else value
        )
    return result


def _merge_entries(before: list[dict], updates: list[dict]) -> list[dict]:
    identities = [_identity(item) for item in updates]
    if len(identities) != len(set(identities)):
        raise ValidationError("本轮变化包含重复身份，请合并后保存")
    items = {_identity(item): item for item in before}
    for identity, update in zip(identities, updates, strict=True):
        items[identity] = _merge_fields(items.get(identity, {}), update)
    return list(items.values())


def merge_world_design_changes(
    previous: WorldDesignChanges, repair: WorldDesignChanges
) -> WorldDesignChanges:
    """Apply a repair to the previous proposal, preserving its untouched entries."""
    merged = previous.model_dump(mode="json", by_alias=True, exclude_unset=True)
    for section, updates in repair.model_dump(
        mode="json", by_alias=True, exclude_unset=True, exclude_none=True
    ).items():
        if isinstance(updates, list):
            merged[section] = _merge_entries(merged.get(section, []), updates)
        elif section == "premise":
            merged[section] = _merge_fields(merged.get(section) or {}, updates)
        else:
            group = merged.setdefault(section, {})
            for key, value in updates.items():
                group[key] = (
                    _merge_entries(group.get(key, []), value)
                    if isinstance(value, list)
                    else _merge_fields(group.get(key, {}), value)
                )
    return WorldDesignChanges.model_validate(merged)


def complete_world_design_changes(
    parent: WorldDesignCheckpointPayload,
    changes: WorldDesignChanges,
    parent_checkpoint_id: uuid.UUID,
    *,
    previous: WorldDesignChanges | None = None,
) -> WorldDesignChanges:
    """Preserve omitted fields; an explicitly supplied empty value still clears."""
    changes = resolve_world_design_change_ids(parent, changes, parent_checkpoint_id)
    if previous is not None:
        changes = merge_world_design_changes(
            resolve_world_design_change_ids(parent, previous, parent_checkpoint_id),
            changes,
        )
    state = parent.world_state.model_dump(mode="json", by_alias=True)
    patch = changes.model_dump(mode="json", by_alias=True, exclude_unset=True)

    def entries(before, updates, *, fixed_names=False):
        existing = {_identity(item): item for item in before}
        completed = []
        for item in updates:
            old = existing.get(_identity(item), {})
            merged = _merge_fields(old, item)
            if fixed_names and old:
                merged["name"] = old["name"]
            completed.append(merged)
        return completed

    for section, updates in patch.items():
        if isinstance(updates, list):
            patch[section] = entries(
                state[section],
                updates,
                fixed_names=section in {"facets", "coupling_chains", "pressure_tests"},
            )
        elif section == "premise":
            if updates is not None:
                patch[section] = _merge_fields(state[section], updates)
        else:
            patch[section] = {
                key: entries(state[section][key], value)
                if isinstance(value, list)
                else _merge_fields(state[section][key], value)
                for key, value in updates.items()
            }
    return WorldDesignChanges.model_validate(patch)


def resolve_world_design_change_ids(
    parent: WorldDesignCheckpointPayload,
    changes: WorldDesignChanges,
    parent_checkpoint_id: uuid.UUID,
) -> WorldDesignChanges:
    """Use one identity space for proposal, review, repair and saved knowledge."""
    state = parent.world_state.model_dump(mode="json", by_alias=True)
    payload = changes.model_dump(mode="json", by_alias=True, exclude_unset=True)
    groups = [
        (section, state[section], payload.get(section, []))
        for section in ("rules", "actors", "places", "institutions", "history")
    ]
    groups.extend(
        ("knowledge", state["knowledge_layers"][group], entries)
        for group, entries in payload.get("knowledge_layers", {}).items()
    )
    replacements = {}
    for section, existing, updates in groups:
        existing_ids = {item["id"] for item in existing}
        for item in updates:
            identity = item["id"]
            if identity.startswith("new:") and identity not in existing_ids:
                replacements[identity] = (
                    f"{section}:{uuid.uuid5(parent_checkpoint_id, identity)}"
                )

    def resolve(value, field=""):
        if isinstance(value, dict):
            return {key: resolve(child, key) for key, child in value.items()}
        if isinstance(value, list):
            return [resolve(child, field) for child in value]
        if isinstance(value, str) and field in {
            "id",
            "from",
            "to",
            "dependencies",
            "actors",
            "artifacts",
            "nodes",
            "known_by",
        }:
            return replacements.get(value, value)
        return value

    return WorldDesignChanges.model_validate(resolve(payload))


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


def world_design_revision_content_hash(
    *,
    summary: str,
    changes,
    depth: str,
    decisions: list | None = None,  # noqa: ANN001
) -> str:
    """Hash only author-editable proposal content, independent of transport metadata."""
    change_payload = WorldDesignChanges.model_validate(changes).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    decision_payload = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in (decisions or [])
    ]
    return stable_hash(
        {
            "summary": summary,
            "changes": change_payload,
            "decisions": decision_payload,
            "depth": depth,
        }
    )


def revise_world_design(
    parent: WorldDesignCheckpointPayload,
    request: WorldDesignRevisionRequest,
    *,
    decision_state=None,  # noqa: ANN001
    review_reference: dict | None = None,
) -> WorldDesignCheckpointPayload:
    """Merge only explicit entries; recompute lineage and invalidate dependents."""
    state = parent.world_state.model_dump(mode="json", by_alias=True)
    changes = complete_world_design_changes(
        parent, request.changes, request.parent_checkpoint_id
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
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
    if review_reference is not None:
        state["extensions"]["verified_counterexample_review"] = review_reference
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
        decision_state=(
            decision_state.model_dump(mode="json")
            if hasattr(decision_state, "model_dump")
            else decision_state
        ),
    )
    return WorldDesignCheckpointPayload.model_validate(payload)
