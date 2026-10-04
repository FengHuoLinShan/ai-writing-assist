"""World 模块共享辅助函数"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from shared.utils import parse_uuid  # noqa: F401


async def current_writing_chapter_index(
    db: AsyncSession,
    novel_id: str,
) -> int:
    """当前写作进度：最新有实质正文的章节号；0 表示动笔前。

    按需导入 writing facade（先例 ``world_impact_service.py``）；查询出错直接
    向上抛出，不吞异常。
    """
    from modules.writing.facade import get_latest_effective_chapter_index

    return await get_latest_effective_chapter_index(db, novel_id)


def entity_relation_execution_snapshot(relation) -> dict[str, object]:
    """关系执行快照 — 读取端展示与写入端重验共用同一份字段清单。

    字段增删会改变指纹语义，任何调整必须同步调用方并保持两端一致。
    """
    updated_at = relation.updated_at
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    source_chapter_id = relation.source_chapter_id
    caused_by_event_id = relation.caused_by_event_id
    return {
        "id": str(relation.id),
        "source_id": str(relation.source_id),
        "target_id": str(relation.target_id),
        "relation_type": relation.relation_type,
        "relation_kind": relation.relation_kind,
        "description": relation.description,
        "strength": relation.strength,
        "status": relation.status,
        "quote": relation.quote,
        "source_chapter_id": str(source_chapter_id) if source_chapter_id else None,
        "caused_by_event_id": str(caused_by_event_id) if caused_by_event_id else None,
        "review_meta": relation.review_meta or {},
        "updated_at": updated_at.astimezone(UTC).isoformat() if updated_at else None,
    }


def entity_relation_execution_fingerprint(relation) -> str:
    """单条关系的执行指纹，与批量分组指纹共用 stable_fingerprint 算法。"""
    from modules.world.services.core.review_queue import stable_fingerprint

    return stable_fingerprint(entity_relation_execution_snapshot(relation))


def normalize_name(value: str) -> str:
    """标准化名称用于匹配：去除特殊字符后 casefold"""
    normalized = value.casefold()
    for token in ("·", "•", "-", "_", " ", "（", "）", "(", ")", "　"):
        normalized = normalized.replace(token, "")
    return normalized


def merge_text_field(current: str | None, incoming: str | None) -> str:
    """合并两个文本字段：不覆盖非空已有内容，只追加"""
    current_text = (current or "").strip()
    incoming_text = (incoming or "").strip()
    if not incoming_text:
        return current_text
    if not current_text:
        return incoming_text
    if incoming_text == current_text or incoming_text in current_text:
        return current_text
    return f"{current_text}\n\n{incoming_text}"


def world_entity_types_compatible(left: str | None, right: str | None) -> bool:
    """判断两个 entity_type 是否可合并"""
    left = (left or "other").strip().casefold()
    right = (right or "other").strip().casefold()
    return "other" in {left, right} or left == right


def find_alias_in_entity(entity, alias_text: str) -> bool:
    """检查 CoreEntity 的 aliases JSONB 中是否包含指定别名文本"""
    if not alias_text:
        return False
    for entry in entity.aliases or []:
        if isinstance(entry, dict) and entry.get("alias") == alias_text:
            return True
    return False


def find_alias_in_list(aliases: list | None, alias_text: str) -> bool:
    """检查 JSONB 别名列表（原始 list[dict]）是否包含指定别名文本"""
    if not alias_text:
        return False
    for entry in aliases or []:
        if isinstance(entry, dict) and entry.get("alias") == alias_text:
            return True
    return False


def _baseline_as_utc(value):
    from datetime import UTC

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def assert_edit_baseline(
    expected_updated_at,
    current_updated_at,
    *,
    label: str,
) -> None:
    """作者编辑基线检查：缺失或过期都返回可识别的 409 冲突，不接受无条件覆盖。

    比较前统一到 UTC，避免 SQLite/PG 时区表达差异造成误判；调用方必须先在
    行锁内加载目标行，再执行本检查。
    """
    from core.errors import ConflictError

    if expected_updated_at is None:
        raise ConflictError(
            f"{label}编辑需要携带基线 expected_updated_at",
            code="edit_baseline_required",
        )
    if current_updated_at is None or _baseline_as_utc(
        expected_updated_at
    ) != _baseline_as_utc(current_updated_at):
        raise ConflictError(
            f"{label}已在别处更新，请刷新后重试",
            code="edit_baseline_stale",
        )


async def require_fresh_understanding_source(db, novel_id, metadata):
    """Explicit adoption of an Evolution candidate still revalidates its source."""
    if not isinstance(metadata, dict):
        return
    if "evolution_ref" in metadata:
        reference = metadata["evolution_ref"]
    elif (
        isinstance(metadata.get("review_meta"), dict)
        and "evolution_ref" in metadata["review_meta"]
    ):
        reference = metadata["review_meta"]["evolution_ref"]
    else:
        return
    from core.errors import ConflictError
    from modules.evolution.facade import require_current_world_candidate

    if (
        not isinstance(reference, dict)
        or not reference.get("run_key")
        or not reference.get("attempt_id")
    ):
        raise ConflictError("理解来源记录不完整，请重新核对候选")
    from sqlalchemy.exc import DBAPIError

    from modules.project.facade import require_active_project_exclusive

    # Some review paths already hold domain rows. Never wait to upgrade the
    # shared project lock: a concurrent writer gets a retryable conflict.
    try:
        await require_active_project_exclusive(db, novel_id, nowait=True)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != "55P03":
            raise
        raise ConflictError("正文或资料正在更新，请刷新后再采用") from error
    await require_current_world_candidate(db, novel_id, reference)
