"""World 模块共享辅助函数"""

from __future__ import annotations

from shared.utils import parse_uuid  # noqa: F401


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
