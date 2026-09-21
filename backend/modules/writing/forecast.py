"""Writing owns the meaning of local continuation suggestions."""

INSTRUCTIONS = {
    "writing.next_beat.v1": (
        "从当前已保存段落找下一节拍：人物行动、对白结果、情绪收束或直接切场。"
        "最多三个不同方向，说明条件、下一至两步影响与新增负担；允许不放大。"
        "没有大纲或 Scene 仍可就当前正文帮助；只润色时不提出剧情变化。"
    ),
}


async def inspect(db, novel_id, focus, excluded):
    from difflib import SequenceMatcher
    from uuid import UUID

    from sqlalchemy import select

    from infrastructure.llm.collaboration import content_hash
    from modules.assistant.contracts import ForecastDomainFact
    from modules.writing.models import WritingDraft

    if not focus.draft_id or str(focus.draft_id) in excluded:
        return []
    draft = await db.scalar(
        select(WritingDraft).where(
            WritingDraft.novel_id == UUID(novel_id),
            WritingDraft.id == focus.draft_id,
        )
    )
    if draft is None:
        return []
    rows = (
        await db.scalars(
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == draft.novel_id,
                WritingDraft.chapter_index == draft.chapter_index,
                WritingDraft.status != "deprecated",
            )
            .order_by(WritingDraft.version_number.desc())
        )
    ).all()
    rows = [row for row in rows if str(row.id) not in excluded]
    saved = [row for row in rows if row.status != "candidate"]
    previous = next(
        (row for row in saved if row.version_number < draft.version_number), None
    )
    facts = []
    if previous:
        before, after = previous.content or "", draft.content or ""
        # ponytail: bounded chapter diff; use indexed diffs if chapter size grows.
        bounded = max(len(before), len(after)) <= 32000
        changes = [
            {"old_range": [a, b], "new_range": [c, d], "operation": tag}
            for tag, a, b, c, d in SequenceMatcher(
                None, before if bounded else "", after if bounded else ""
            ).get_opcodes()
            if tag != "equal"
        ]
        facts.append(
            ForecastDomainFact(
                capability_id="writing.revision_impact.v1",
                subject=f"chapter:{draft.chapter_index}",
                title="核对这次改稿影响",
                summary=f"与前一个保存版本相比，正文有 {len(changes)} 处变化。"
                if bounded
                else "本章超过完整差异枚举范围，请在原版本页缩小比较。",
                source={
                    "previous_id": str(previous.id),
                    "previous_hash": previous.content_hash,
                    "current_id": str(draft.id),
                    "current_hash": draft.content_hash,
                    "changes": changes,
                },
                scope_label="当前章节两个保存版本的文字差异"
                if bounded
                else "仅核对两个版本的来源哈希，未枚举文字差异",
                actionable=bool(changes) or not bounded,
                unknowns=["文字差异不等于剧情因果影响；尚未检查其他章节和人物所知。"],
                target={"page": "writing", "chapter_index": draft.chapter_index},
            )
        )
    candidates = [row for row in rows if row.status == "candidate"]
    if candidates:
        candidate = candidates[0]
        facts.append(
            ForecastDomainFact(
                capability_id="writing.candidate_next.v1",
                subject=str(candidate.id),
                title="有一份候选可供审阅",
                summary="先在原候选页核对依据与复核状态，再决定采用或返修。",
                source={
                    "id": str(candidate.id),
                    "hash": candidate.content_hash,
                    "working_hash": draft.content_hash,
                    "provenance_hash": content_hash(candidate.provenance_json or {}),
                    "review": candidate.conflict_check_snapshot_json,
                },
                scope_label="当前章节最近候选及原保存回执",
                unknowns=["前瞻未替代原候选来源重验，不据此宣称可直接采用。"],
                target={
                    "page": "writing",
                    "chapter_index": draft.chapter_index,
                    "reference": {
                        "type": "writing_candidate",
                        "id": str(candidate.id),
                        "chapter_index": draft.chapter_index,
                    },
                },
            )
        )
    facts.append(
        ForecastDomainFact(
            capability_id="writing.recall_pack.v1",
            subject=f"chapter:{draft.chapter_index}",
            title="接着写前，回看当前保存段落",
            summary="当前保存稿可直接定位；如需人物知识或世界约束，请在原资料界面选择并确认。",
            source={
                "draft_id": str(draft.id),
                "hash": draft.content_hash,
                "scene_id": str(focus.scene_id) if focus.scene_id else None,
                "confirmation_id": str(focus.context_confirmation_id)
                if focus.context_confirmation_id
                else None,
            },
            scope_label="当前保存正文；已选择的场景及确认资料另列",
            unknowns=[]
            if focus.context_confirmation_id
            else ["未确认人物知识、世界约束和继承资料。"],
            target={"page": "writing", "chapter_index": draft.chapter_index},
        )
    )
    return facts
