"""Apply the author's read scope before a domain prepares an editable preview."""

from core.errors import ConflictError
from modules.evidence.contracts import VisibilityContextContract
from modules.evidence.facade import inspect_novel_target, prepare_confirmed_ai_action


async def require_operation_targets(db, novel_id, context, targets, *, aggregate=False):
    if context is None:
        return
    work = context.work
    excluded = {value.rsplit(":", 1)[-1] for value in work.excluded_targets}
    if any(str(target_id) in excluded for _, target_id in targets):
        raise ConflictError("本次操作涉及已排除资料，请在原范围内调整方案")
    if aggregate and (excluded or work.context_confirmation_id):
        raise ConflictError(
            "当前参考范围不能覆盖此项整体预览，请到对应工作台确认具体资料"
        )
    if work.context_confirmation_id:
        prepared = await prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=work.context_confirmation_action,
            confirmation_id=str(work.context_confirmation_id),
        )
        selected = {
            str(value)
            for values in prepared.confirmation.selected_asset_ids.values()
            for value in values
        }
        excluded.update(
            str(value)
            for values in prepared.confirmation.excluded_asset_ids.values()
            for value in values
        )
        if any(
            str(target_id) in excluded
            or (
                str(target_id) not in selected
                and not (kind == "writing_draft" and str(work.draft_id) == str(target_id))
            )
            for kind, target_id in targets
        ):
            raise ConflictError("操作需要的资料不在原确认中，请在原工作台重新确认")
    if work.scope == "current" and (work.chapter_index or work.scene_id):
        for kind, target_id in targets:
            if kind == "author_task":
                continue
            if kind == "writing_draft":
                from modules.writing.facade import get_draft

                draft = await get_draft(db, novel_id, str(target_id))
                if draft is None or (
                    work.chapter_index and draft.chapter_index > work.chapter_index
                ):
                    raise ConflictError("正文不在当前章节范围内")
                if (
                    work.scene_id
                    and str(target_id) != str(work.draft_id)
                    and str((draft.provenance_json or {}).get("scene_id") or "")
                    != str(work.scene_id)
                ):
                    raise ConflictError("正文没有绑定当前场景")
                continue
            inspected = await inspect_novel_target(
                db,
                novel_id=novel_id,
                target_ref={"target_type": kind, "target_id": str(target_id)},
                content_mode="working",
                visibility=VisibilityContextContract(
                    mode="author",
                    cutoff_chapter=work.chapter_index,
                    cutoff_scene_id=str(work.scene_id) if work.scene_id else None,
                ),
            )
            if not inspected.get("visible"):
                raise ConflictError("操作需要的资料不在当前章节或场景可见范围")
