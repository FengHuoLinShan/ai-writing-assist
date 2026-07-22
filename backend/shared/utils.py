"""
共享工具函数

包含 UUID 解析、验证等跨模块通用工具。
所有模块应使用此文件的函数，而非各自重复实现。
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from core.errors import ValidationError as DomainValidationError

logger = logging.getLogger(__name__)

def parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """将字符串 ID 解析为 UUID，格式错误时抛出 422

    Args:
        value: UUID 字符串（hex 格式）
        field_name: 字段名（用于错误提示）

    Returns:
        uuid.UUID

    Raises:
        DomainValidationError 422: UUID 格式无效
    """
    try:
        return uuid.UUID(hex=value)
    except ValueError:
        raise DomainValidationError(
            f"Invalid {field_name}: {value}",
            status_code=422,
        )


def is_valid_uuid(value: str) -> bool:
    """检查字符串是否为有效的 UUID 格式

    Args:
        value: 待检查的字符串

    Returns:
        True 如果字符串是有效 UUID，否则 False
    """
    try:
        uuid.UUID(hex=value)
        return True
    except (ValueError, AttributeError):
        return False


def parse_llm_json(content: str, label: str = "LLM response") -> dict:
    """从 LLM 响应中可靠地提取 JSON。

    处理常见问题：
    - Markdown 代码块包裹 (```json ... ```)
    - 前导/尾随空白
    - BOM 字符
    - DeepSeek 推理模型的思考块
    - 空响应

    Args:
        content: LLM 返回的原始文本
        label: 日志描述标签

    Returns:
        解析出的 dict

    Raises:
        ValueError: 无法提取有效 JSON
    """
    text = content.strip()
    if not text:
        logger.warning("%s is empty or whitespace-only", label)
        raise ValueError(f"{label} is empty")

    # 1. 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        # 如果结果是列表，包装为 dict
        if isinstance(result, list):
            return {"items": result}
    except json.JSONDecodeError:
        pass

    # 2. 提取 markdown JSON 代码块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            result = json.loads(m.group(1).strip())
            if isinstance(result, dict):
                return result
            if isinstance(result, list):
                return {"items": result}
        except json.JSONDecodeError:
            pass

    # 3. 尝试找到第一个 { 到最后一个 }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        try:
            return json.loads(text[first_brace : last_brace + 1])
        except json.JSONDecodeError:
            pass

    # 4. 尝试找到第一个 [ 到最后一个 ]
    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket >= 0 and last_bracket > first_bracket:
        try:
            result = json.loads(text[first_bracket : last_bracket + 1])
            if isinstance(result, list):
                return {"items": result}
            return result
        except json.JSONDecodeError:
            pass

    # 5. 从 { 到最后一个 }，尝试逐步截断以恢复被 max_tokens 截断的 JSON
    if first_brace >= 0:
        truncated = text[first_brace:]
        # 找到最后一个完整的对象或数组结束
        for end_char in ("}]", "]}", '"]', '"]', "}}", '""}'):
            last_good = truncated.rfind(end_char)
            if last_good >= 0:
                try:
                    candidate = truncated[: last_good + len(end_char)]
                    # 补齐可能缺失的外层括号
                    if candidate.count("{") > candidate.count("}"):
                        candidate += "}" * (candidate.count("{") - candidate.count("}"))
                    if candidate.count("[") > candidate.count("]"):
                        candidate += "]" * (candidate.count("[") - candidate.count("]"))
                    result = json.loads(candidate)
                    if isinstance(result, dict):
                        logger.info(
                            "%s: recovered truncated JSON (len=%d)", label, len(candidate)
                        )
                        return result
                except json.JSONDecodeError:
                    continue

    logger.warning("%s JSON parse failed (length=%d)", label, len(text))
    raise ValueError(f"{label} is not valid JSON")
