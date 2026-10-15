"""Pure operation manifest for unified-notice author dispositions."""

from __future__ import annotations

from modules.assistant.notice_contracts import (
    NoticeOperationCategoryMute,
    NoticeOperationDisposition,
)
from modules.assistant.notice_service import (
    _operation_disposition_apply,
    _operation_disposition_preview,
    _operation_mute_apply,
    _operation_mute_preview,
    _operation_unmute_apply,
    _operation_unmute_preview,
)


def _trace(schema):
    return {
        "parameter_fields": tuple(schema.model_fields),
        "mode": "per_call",
        "parameter_policy": "schema_safe",
    }


def _metadata(
    *, description: str, preconditions: tuple[str, ...], produces: tuple[str, ...]
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": "R2",
        "fee_category": "free",
        "reversibility": "reversible",
        "preconditions": preconditions,
        "produces": produces,
        "target_type": "author_notice",
        "ai_available": True,
        "transaction_mode": "single_transaction",
    }


OPERATIONS_SPEC = {
    "assistant.notice.set_disposition": {
        "label": "处理提醒",
        "schema": NoticeOperationDisposition,
        "prepare": _operation_disposition_preview,
        "apply": _operation_disposition_apply,
        **_metadata(
            description="按当前依据指纹，将项目提醒标为已读、稍后或忽略；转发已有领域处置。",
            preconditions=("作者已确认本项目操作", "提醒依据指纹和版本仍为最新"),
            produces=("提醒展示处置",),
        ),
        "trace_rule": _trace(NoticeOperationDisposition),
    },
    "assistant.notice.mute_category": {
        "label": "静默这一类提醒",
        "schema": NoticeOperationCategoryMute,
        "prepare": _operation_mute_preview,
        "apply": _operation_mute_apply,
        **_metadata(
            description="静默指定项目、来源和类别的统一提醒。",
            preconditions=("作者已确认本项目操作", "提醒来源已注册", "设置版本仍为最新"),
            produces=("来源类别静默设置",),
        ),
        "trace_rule": _trace(NoticeOperationCategoryMute),
    },
    "assistant.notice.unmute_category": {
        "label": "恢复这一类提醒",
        "schema": NoticeOperationCategoryMute,
        "prepare": _operation_unmute_preview,
        "apply": _operation_unmute_apply,
        **_metadata(
            description="恢复指定项目、来源和类别的统一提醒。",
            preconditions=("作者已确认本项目操作", "静默设置存在且版本仍为最新"),
            produces=("来源类别静默设置",),
        ),
        "trace_rule": _trace(NoticeOperationCategoryMute),
    },
}
