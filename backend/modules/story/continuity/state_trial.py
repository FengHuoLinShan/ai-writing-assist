"""指定切片的只读条件比较：保管转移与三条件开锁，候选仅在内存重放。"""

from __future__ import annotations

import uuid

from core.container import get
from core.service_keys import WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY
from infrastructure.llm.collaboration import content_hash
from infrastructure.stable_hash import stable_hash
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.contracts import SceneStateTrialRequest
from modules.story.observations import ResolutionBatch, StateDelta, replay_batch


async def compare_scene_state_trial(
    db, novel_id: str, request: SceneStateTrialRequest
) -> dict:
    from core.errors import ConflictError, ValidationError

    service = SceneStateViewService()
    author = await service.get_view(
        db,
        novel_id=novel_id,
        scene_id=str(request.scene_id),
        viewpoint={"kind": "author"},
    )
    if author.state_fingerprint != request.state_fingerprint:
        raise ConflictError(
            "本场状态已有变化，请刷新后重新比较", code="STATE_TRIAL_STALE"
        )
    role = await service.get_view(
        db,
        novel_id=novel_id,
        scene_id=str(request.scene_id),
        viewpoint={"kind": "character", "target_id": str(request.actor_id)},
    )
    latest = await service.get_view(
        db,
        novel_id=novel_id,
        scene_id=str(request.scene_id),
        viewpoint={"kind": "author"},
    )
    if latest.model_dump() != author.model_dump():
        raise ConflictError(
            "本场状态在核对期间已有变化，请重试", code="STATE_TRIAL_STALE"
        )
    if request.action == "transfer_key" and not request.recipient_id:
        raise ValidationError("请指定接收钥匙的人物")
    if request.action == "open_lock" and not request.lock_id:
        raise ValidationError("请指定要检查的锁")
    facts = {
        (fact.subject_id, fact.field): fact
        for dim in author.dimensions
        if dim.status == "ok"
        for fact in dim.facts
        if fact.layer == "fact"
    }
    known_people = set(author.subject_labels)
    for person in (request.actor_id, request.recipient_id, request.candidate_holder_id):
        if person is not None and (
            str(person) not in known_people
            or not await get(WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY)(
                db, novel_id, str(person)
            )
        ):
            raise ValidationError("所选人物未在本场状态中登记，请先补充核对")
    for subject in (request.key_id, request.lock_id):
        if subject is not None and str(subject) not in known_people:
            raise ValidationError("该对象未在本场状态中登记；不能凭空加入试验")
    key_id, actor = str(request.key_id), str(request.actor_id)
    holder = facts.get((key_id, "custody_holder"))
    owner = facts.get((key_id, "custody_owner"))
    moon = next(
        (
            fact
            for dim in author.dimensions
            if dim.dimension == "timeline" and dim.status == "ok"
            for fact in reversed(dim.facts)
            if isinstance(fact.value, dict) and fact.value.get("moon_phase") is not None
        ),
        None,
    )
    base = {
        "revision": 0,
        "resource_holders": {key_id: holder.value} if holder else {},
        "owners": {key_id: owner.value} if owner else {},
    }
    candidate = {**base, "resource_holders": dict(base["resource_holders"])}
    assumptions = []
    if request.candidate_holder_id is not None:
        if holder is not None:
            candidate["resource_holders"][key_id] = str(request.candidate_holder_id)
        assumptions.append("本次假设：钥匙由所选人物保管；没有改变所有权或授予知识")
    if request.candidate_moon_phase is not None:
        assumptions.append("本次假设：使用所选月相；不写入历史")

    def readable(value):
        if value is None:
            return "未记载"
        if value in ("full", "other"):
            return "月圆" if value == "full" else "非月圆"
        text = str(value)
        if text in author.subject_labels:
            return author.subject_labels[text]
        try:
            uuid.UUID(text)
        except ValueError:
            return text
        return "未记录名称的对象"

    def condition(label, observed, expected, source=None, *, assumption=False):
        status = (
            "unknown"
            if observed is None or expected is None
            else "met"
            if observed == expected
            else "unmet"
        )
        return {
            "label": label,
            "status": status,
            "source": source or {},
            "assumption": assumption,
            "observed": readable(observed),
            "expected": readable(expected),
        }

    def place(fact):
        if fact is None:
            return None
        value = fact.value
        if isinstance(value, dict):
            return (
                value.get("location_id") or value.get("node") or value.get("text_state")
            )
        return value

    def evaluate(state, *, trial):
        conditions = []
        if request.action == "transfer_key":
            conditions.append(
                condition(
                    "行动者当前保管钥匙",
                    state["resource_holders"].get(key_id),
                    actor,
                    holder.source if holder else None,
                    assumption=trial and request.candidate_holder_id is not None,
                )
            )
            for person in (actor, str(request.recipient_id)):
                location = facts.get((person, "location"))
                # location事实在locations维度，不用当前World补过去。
                reference = facts.get((actor, "location"))
                conditions.append(
                    condition(
                        "交接双方在同一位置",
                        place(location),
                        place(reference),
                        location.source if location else None,
                    )
                )
        else:
            lock = str(request.lock_id)
            required_key = facts.get((lock, "opening_key_id"))
            required_moon = facts.get((lock, "opening_moon_phase"))
            required_phrase = facts.get((lock, "opening_passphrase"))
            conditions.append(
                condition(
                    "锁所需的钥匙已有明确记录",
                    key_id,
                    required_key.value if required_key else None,
                    required_key.source if required_key else None,
                )
            )
            conditions.append(
                condition(
                    "行动者保管所需钥匙",
                    state["resource_holders"].get(key_id),
                    actor,
                    holder.source if holder else None,
                    assumption=trial and request.candidate_holder_id is not None,
                )
            )
            phase = (
                request.candidate_moon_phase
                if trial and request.candidate_moon_phase is not None
                else moon.value.get("moon_phase")
                if moon
                else None
            )
            conditions.append(
                condition(
                    "当前月相满足开锁条件",
                    phase,
                    required_moon.value if required_moon else None,
                    moon.source if moon else None,
                    assumption=trial and request.candidate_moon_phase is not None,
                )
            )
            candidates = [
                fact
                for dim in role.dimensions
                if dim.dimension == "knowledge" and dim.status == "ok"
                for fact in dim.facts
                if fact.subject_id == actor
                and fact.field == f"knows:{lock}"
                and not fact.possibly_false
                and "opening_passphrase" in fact.source.get("known_fields", [])
            ]
            knowledge = next(
                (
                    fact
                    for fact in candidates
                    if required_phrase
                    and fact.source.get("known_values", {}).get("opening_passphrase")
                    == required_phrase.value
                ),
                candidates[0] if candidates else None,
            )
            conditions.append(
                condition(
                    "行动者有口令知识依据",
                    knowledge.source.get("known_values", {}).get("opening_passphrase")
                    if knowledge
                    else None,
                    required_phrase.value if required_phrase else None,
                    knowledge.source if knowledge else None,
                )
            )
        states = {item["status"] for item in conditions}
        verdict = (
            "failed"
            if "unmet" in states
            else "uncertain"
            if "unknown" in states
            else "succeeded"
        )
        patches = []
        if verdict == "succeeded" and request.action == "transfer_key":
            patches.append(
                StateDelta(
                    kind="resource_holder",
                    key=key_id,
                    before=state["resource_holders"][key_id],
                    after=str(request.recipient_id),
                )
            )
        batch = ResolutionBatch(
            base_state_revision=0,
            base_state_hash=content_hash(state),
            intents_hash=stable_hash(
                request.model_dump(mode="json", exclude={"comparison_digest"})
            ),
            rule_revision=stable_hash("scene-key-lock-v1"),
            events=[
                {
                    "actor_id": actor,
                    "kind": request.action,
                    "outcome": verdict,
                    "truth": "simulated_outcome",
                }
            ],
            state_patches=patches,
            unresolved_outcomes=[actor] if verdict == "uncertain" else [],
            assumptions=["给定依据和假设下的条件比较，不是已经发生的事件。"],
        )
        # observation协议使用content_hash；只在候选内存重放，零事件写入。

        replayed = replay_batch(state, batch)
        return {
            "outcome": verdict,
            "conditions": conditions,
            "candidate_state": replayed,
            "resource_state": {
                "holder": readable(replayed["resource_holders"].get(key_id)),
                "owner": readable(replayed["owners"].get(key_id)),
            },
            "resolution": batch.model_dump(mode="json"),
        }

    result = {
        "scene_id": str(request.scene_id),
        "state_fingerprint": author.state_fingerprint,
        "action": request.action,
        "actor_id": actor,
        "baseline": evaluate(base, trial=False),
        "candidate": evaluate(candidate, trial=True),
        "assumptions": assumptions,
        "not_checked": [
            "仅核对钥匙保管/位置及明确记载的开锁钥匙、月相、口令知识；未推演心理、远期因果或新增事实"
        ],
        "authority": "仅为本次试验；原稿、世界设定与场景事件均未写入",
    }

    result["comparison_digest"] = stable_hash(result)
    if (
        request.comparison_digest
        and request.comparison_digest != result["comparison_digest"]
    ):
        raise ConflictError(
            "条件或来源已变化，请重新比较后再试改", code="STATE_TRIAL_STALE"
        )
    return result
