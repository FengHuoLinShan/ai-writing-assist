"""Author-visible request/token/time ranges for a scene-director root."""

from __future__ import annotations

from datetime import UTC, datetime

from infrastructure.llm.collaboration import content_hash
from modules.story.director_context import actor_packet, director_only_packet


def director_pending_checkpoint_hash(branch) -> str:
    return content_hash(
        {
            "branch_id": str(branch.id),
            "request": branch.request_json or {},
            "pending_round": branch.pending_round_json or {},
        }
    )


def preview_director_resume(root_id: str, branch, envelope) -> dict:
    snapshot = envelope.snapshot()
    ledger = {
        "requests_started": snapshot.requests_started,
        "requests_settled": snapshot.requests_settled,
        "requests_unknown": snapshot.requests_unknown,
        "recent_attempts_overflow": snapshot.recent_attempts_overflow,
        "request_limit": snapshot.request_limit,
        "token_limit": snapshot.token_limit,
        "tokens_used": snapshot.usage.total_tokens,
        "usage_complete": snapshot.usage_complete,
        "deadline_at": snapshot.deadline_at.isoformat() if snapshot.deadline_at else None,
        "authorization_revision": snapshot.authorization_revision,
    }
    checkpoint_hash = director_pending_checkpoint_hash(branch)
    preview_identity = {
        "root_id": str(root_id),
        "branch_id": str(branch.id),
        "checkpoint_hash": checkpoint_hash,
        "ledger": ledger,
    }
    return {
        "preview_hash": content_hash(preview_identity),
        "pending_checkpoint_hash": checkpoint_hash,
        "current_budget": {
            "requests_used": snapshot.requests_started,
            "requests_authorized": snapshot.request_limit,
            "tokens_used": snapshot.usage.total_tokens,
            "tokens_authorized": snapshot.token_limit,
            "unknown_requests": snapshot.requests_unknown,
            "usage_complete": snapshot.usage_complete,
            "deadline_at": ledger["deadline_at"],
        },
        "possible_charge": (
            "恢复会复用已保存检查点；未得到结果的请求仅在作者明确确认后重试。"
        ),
        "warnings": ["恢复沿用原资料快照、累计账本和时限；资料变化时需要重新开始排演。"],
    }


def preview_director_budget(request, source: dict) -> dict:
    ids = list(request.character_ids)
    round_count = int(request.rounds)
    instructions = str(getattr(request, "instructions", ""))
    intervention = str(getattr(request, "intervention", ""))
    public_stimulus = str(getattr(request, "public_stimulus", ""))
    root_packet = director_only_packet(source, instructions, intervention)
    role_chars = sum(len(actor_packet(source, actor, public_stimulus)) for actor in ids)
    full_chars = len(root_packet) + role_chars
    # One typed intent and one performance card per participant, one finite
    # adjudication, and one scene-material/angle/branch recommendation request.
    per_round = 2 * len(ids) + 2
    requests_minimum = 4 * round_count
    requests_maximum = per_round * round_count
    input_low = max(1, int((full_chars + len(ids) * 1600) / 4.0)) * round_count
    input_high = max(
        input_low, int((full_chars * 3 + len(ids) * 3200) / 3.0) * round_count
    )
    output_low = (len(ids) * 900 + 900) * round_count
    output_high = (len(ids) * 2200 + 2400) * round_count
    preview_identity = {
        "scene_id": request.scene_id,
        "character_ids": sorted(ids),
        "related_object_ids": sorted(request.related_object_ids),
        "primary_character_ids": sorted(request.primary_character_ids),
        "rounds": round_count,
        "source_hash": source["source_hash"],
        "instruction_chars": len(instructions),
        "intervention_chars": len(intervention),
        "public_stimulus_chars": len(public_stimulus),
    }
    return {
        "preview_hash": content_hash(preview_identity),
        "request_count": {"minimum": requests_minimum, "maximum": requests_maximum},
        "token_count": {
            "minimum": input_low + output_low,
            "maximum": input_high + output_high,
            "method": "按已读资料字符长度估算，实际用量以运行账本为准",
        },
        "time_seconds": {
            "minimum": requests_minimum * 2,
            "maximum": requests_maximum * 25,
        },
        "possible_charge": "开始模型请求后可能产生计费请求；不估算或显示金额",
        "rounds": round_count,
        "participants": len(ids),
        "grouping": {
            "primary_character_ids": list(request.primary_character_ids),
            "background_character_ids": [
                actor for actor in ids if actor not in set(request.primary_character_ids)
            ],
            "actor_intents_are_separate": True,
        },
        "omitted": [
            {"source": "object_dossier", "reason": text}
            for text in source["author_brief"].get("omissions", [])
        ],
        "warnings": [
            "预算预览按当前资料指纹计算；开始前若场景或档案变化，需要重新预览。",
            "预算到 80%、用量未知或可能计费结果未确认时会暂停。",
        ],
    }


def preview_director_continuation(request, source: dict, *, parent_round_id: str) -> dict:
    preview = preview_director_budget(request, source)
    identity = {
        "base_preview_hash": preview["preview_hash"],
        "parent_round_id": str(parent_round_id),
        "branch_kind": request.branch_kind,
        "basis_choice": request.basis_choice,
        "rewrite_character_id": request.rewrite_character_id,
        "selected_alternative": getattr(request, "selected_alternative", None),
    }
    preview["preview_hash"] = content_hash(identity)
    preview["parent_round_id"] = str(parent_round_id)
    preview["branch_kind"] = request.branch_kind
    preview["basis_choice"] = request.basis_choice
    return preview


def budget_stop_reason(
    envelope,
    *,
    acknowledged_unknown: int = 0,
    baseline_requests_started: int | None = None,
    baseline_recent_attempts_overflow: int | None = None,
    check_soft_thresholds: bool = True,
) -> str | None:
    snapshot = envelope.snapshot()
    if snapshot.requests_unknown > acknowledged_unknown:
        return "provider_result_unknown"
    baseline = baseline_requests_started or 0
    new_attempts = [
        attempt
        for attempt in snapshot.recent_attempts
        if attempt.request_index > baseline
    ]
    if any(
        attempt.outcome.value == "unknown"
        or attempt.outcome.value == "in_flight"
        or attempt.charge_state.value == "possible"
        for attempt in new_attempts
    ):
        return "provider_result_unknown"
    if baseline_recent_attempts_overflow is None:
        if snapshot.recent_attempts_overflow:
            return "usage_incomplete"
    elif snapshot.recent_attempts_overflow > baseline_recent_attempts_overflow:
        return "usage_incomplete"
    if not snapshot.usage_complete:
        # Acknowledgment covers only the old unknown count. New attempt states
        # were checked above; legacy usage that cannot be tied to such a count
        # remains unresolvable and cannot be waived.
        if (
            acknowledged_unknown == 0
            or baseline_requests_started is None
            or snapshot.legacy_untracked
            or snapshot.requests_unknown > acknowledged_unknown
        ):
            return "usage_incomplete"
    if not check_soft_thresholds:
        if snapshot.request_limit and snapshot.requests_started >= snapshot.request_limit:
            return "request_budget_exhausted"
        if snapshot.token_limit and snapshot.usage.total_tokens >= snapshot.token_limit:
            return "token_budget_exhausted"
        if snapshot.deadline_at is not None:
            deadline = snapshot.deadline_at
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if datetime.now(UTC) >= deadline:
                return "time_budget_exhausted"
        return None
    if snapshot.request_limit:
        if snapshot.requests_started / snapshot.request_limit >= 0.8:
            return "request_budget_80_percent"
    if snapshot.token_limit:
        if snapshot.usage.total_tokens / snapshot.token_limit >= 0.8:
            return "token_budget_80_percent"
    if snapshot.deadline_at is not None:
        started = snapshot.started_at
        deadline = snapshot.deadline_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        duration = (deadline - started).total_seconds()
        if (
            duration > 0
            and (datetime.now(UTC) - started).total_seconds() / duration >= 0.8
        ):
            return "time_budget_80_percent"
    return None
