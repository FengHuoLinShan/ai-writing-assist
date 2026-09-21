"""Player-visible forecast instructions, separate from author speculation."""

import json
from uuid import UUID, uuid5

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.account.facade import (
    current_account_id,
    is_anonymous_rp_principal,
    is_demo_readonly_principal,
)
from modules.assistant.contracts import (
    EvidenceRef,
    ForecastContext,
    ForecastDomainFact,
    ResolvedScope,
)
from modules.interaction.models import InteractionJourney
from modules.interaction.services import InteractionService, path_hash
from modules.project.facade import get_any_project_context

INSTRUCTIONS = {
    "interaction.visible_next_action.v1": (
        "只根据玩家已读选中历史提出可感知的追问或行动选择，不推测秘密裁决结果。"
    ),
    "interaction.promise_consequence.v1": (
        "只在当前已选历史中找承诺和已发生后果，保留最新明确修正。未发生预测不写成回顾。"
    ),
}


def require_personal():
    if is_anonymous_rp_principal() or is_demo_readonly_principal():
        raise NotFoundError("互动建议仅对自己的私人旅程开放")


async def authorize(db, novel_id):
    require_personal()
    journey = await db.scalar(
        select(InteractionJourney).where(
            InteractionJourney.novel_id == UUID(str(novel_id)),
            InteractionJourney.owner_id == current_account_id(),
            InteractionJourney.status == "active",
        )
    )
    if journey is None:
        raise NotFoundError("旅程不可访问")
    await InteractionService()._owned_journey(db, str(journey.id))
    return await get_any_project_context(db, str(journey.novel_id))


async def materialize(db, novel_id, focus):
    require_personal()
    service = InteractionService()
    if (
        focus.page != "interaction"
        or not focus.journey_id
        or any(
            (
                focus.draft_id,
                focus.scene_id,
                focus.target,
                focus.assistant_session_id,
                focus.context_confirmation_id,
            )
        )
    ):
        raise NotFoundError("请从当前旅程发起互动建议")
    journey = await service._owned_journey(db, str(focus.journey_id))
    if str(journey.novel_id) != str(novel_id):
        raise NotFoundError("旅程不可访问")
    expected = (
        focus.selection_epoch,
        focus.source_context_epoch,
        focus.overview_epoch,
        focus.selected_leaf_node_id,
    )
    actual = (
        journey.selection_epoch,
        journey.source_context_epoch,
        journey.overview_epoch,
        journey.selected_leaf_node_id,
    )
    if expected != actual:
        raise ConflictError("旅程发展、来源或回顾已变化，请刷新建议", code="SOURCE_STALE")
    if await service._repo.get_unresolved_attempt(db, journey=journey):
        raise ConflictError(
            "请先处理或完成当前回应，再查看下一步建议", code="ATTEMPT_ACTIVE"
        )
    nodes = await service._repo.get_selected_path(db, journey=journey)
    if (
        not nodes
        or nodes[-1].role != "assistant"
        or nodes[-1].completion_state != "complete"
    ):
        raise ConflictError(
            "先完成一段正式回应，再查看下一步建议", code="SOURCE_UNAVAILABLE"
        )
    source = None
    if journey.source_revision_id:
        source = await service._sources.require_ready_revision(
            db, journey.source_revision_id
        )
    overview = await service.get_overview(db, journey_id=str(journey.id))
    path_digest = path_hash(nodes)
    boundary = {
        "journey": str(journey.id),
        "owner": str(journey.owner_id),
        "source_revision": str(journey.source_revision_id),
        "source_epoch": journey.source_context_epoch,
        "reference_policy": journey.reference_policy,
        "anchor": journey.source_anchor,
        "player": journey.player_identity,
    }
    scope_hash = content_hash(boundary)
    values = {
        "path": path_digest,
        "selection_epoch": journey.selection_epoch,
        "overview_epoch": journey.overview_epoch,
        "overview_revision": overview.base_revision_id,
        "source_status": source.status if source else None,
    }
    refs, sources, dependencies = [], [], []

    def remember(kind, identity, value, label):
        digest = content_hash(value)
        evidence_id = f"source_{len(refs)}"
        refs.append(
            EvidenceRef(
                evidence_id=evidence_id,
                resource_kind=kind,
                resource_id=identity,
                source_hash=digest,
                revision_token=digest,
                label=label,
            )
        )
        sources.append(
            {
                "evidence_id": evidence_id,
                "text": json.dumps(value, ensure_ascii=False, sort_keys=True),
                "label": label,
            }
        )
        dependencies.append(
            {
                "dependency_key": f"{kind}:{identity}",
                "resource_kind": kind,
                "resource_id": str(identity),
                "revision_token": digest,
                "role": "content",
                "required": True,
                "scope_stamp": scope_hash,
            }
        )

    selected = [
        node
        for node in nodes
        if node.message_kind == "story" and node.completion_state == "complete"
    ][-12:]
    for node in selected:
        remember(
            "interaction_message",
            node.id,
            {"role": node.role, "content": node.content},
            "你已读过的这段发展" if node.role == "assistant" else "你的明确输入",
        )
    if overview.base_revision_id and overview.status == "ready":
        remember(
            "interaction_overview",
            UUID(overview.base_revision_id),
            overview.sections.model_dump(mode="json"),
            "当前选中发展中的有效回顾；最新输入优先",
        )
    fact = ForecastDomainFact(
        capability_id="interaction.source_gap.v1",
        subject=str(journey.id),
        title="按当前发展准备下一步",
        summary="只使用你选中的正式发展与有效回顾。"
        + ("固定作品资料版本仍可用。" if source else "本次旅程没有绑定作品资料。"),
        source={
            **values,
            "source_ready": source is not None,
            "overview_status": overview.status,
        },
        scope_label="最近十二条正式发展；未读原作、兄弟分支和作者摘要不参与",
        target={"page": "interaction", "journey_id": str(journey.id)},
        unknowns=["更早的细节若未进入有效回顾，本次未重新逐条核对。"],
    )
    remember(
        "domain_result",
        uuid5(journey.id, "source-readiness"),
        fact.model_dump(mode="json"),
        fact.title,
    )
    fact_ref = refs[-1]
    dependencies.append(
        {
            "dependency_key": "selected_path",
            "resource_kind": "selected_path",
            "resource_id": str(journey.id),
            "revision_token": content_hash(values),
            "role": "query_scope",
            "required": True,
            "scope_stamp": scope_hash,
        }
    )
    if len(json.dumps(sources, ensure_ascii=False)) > 22000:
        raise ValidationError(
            "当前发展资料超过短期检查范围，请先在原回顾界面整理有效回顾",
            code="CONTEXT_TOO_LARGE",
        )
    context_hash = content_hash(
        {
            "scope": scope_hash,
            "values": values,
            "dependencies": dependencies,
            "instruction": focus.explicit_instruction,
        }
    )
    return ForecastContext(
        ResolvedScope(
            novel_id=journey.novel_id,
            owner_id=journey.owner_id,
            persona="rp",
            audience_key=f"rp:{journey.id}",
            scope_hash=scope_hash,
            context_hash=context_hash,
            journey_id=journey.id,
            selected_path_hash=path_digest,
            selection_epoch=journey.selection_epoch,
            source_context_epoch=journey.source_context_epoch,
            policy_generation=journey.source_context_epoch,
            source_manifest_hash=path_digest,
        ),
        focus,
        sources,
        refs,
        dependencies,
        None,
        [],
        [(fact, fact_ref)],
    )
