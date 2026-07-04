"""
shared/utils.py 单元测试

测试 parse_uuid（UUID 解析 + 422 错误）和 is_valid_uuid（格式验证）。
"""

import uuid
from pathlib import Path

import pytest

from core.errors import ValidationError as DomainValidationError
from shared.utils import is_valid_uuid, parse_uuid


class TestParseUUID:
    """parse_uuid — 字符串 UUID 解析"""

    def test_shared_utils_has_no_fastapi_exception_dependency(self):
        source = Path("backend/shared/utils.py").read_text()

        assert "from fastapi import HTTPException" not in source
        assert "raise HTTPException" not in source

    def test_valid_uuid_returns_uuid_object(self):
        result = parse_uuid("c8f2a1e456784b3d9f1a2b3c4d5e6f71")
        assert isinstance(result, uuid.UUID)

    def test_valid_uuid_preserves_hex_value(self):
        hex_str = "c8f2a1e456784b3d9f1a2b3c4d5e6f71"
        result = parse_uuid(hex_str)
        assert result == uuid.UUID(hex=hex_str)

    def test_invalid_uuid_raises_422(self):
        with pytest.raises(DomainValidationError) as exc:
            parse_uuid("not-a-valid-uuid")
        assert exc.value.status_code == 422

    def test_invalid_uuid_error_detail_contains_field_name(self):
        with pytest.raises(DomainValidationError) as exc:
            parse_uuid("bad", "entity_id")
        assert "entity_id" in exc.value.detail
        assert "bad" in exc.value.detail

    def test_default_field_name_is_id(self):
        with pytest.raises(DomainValidationError) as exc:
            parse_uuid("invalid")
        assert "id" in exc.value.detail.lower() or "id" in exc.value.detail

    def test_empty_string_raises_422(self):
        with pytest.raises(DomainValidationError) as exc:
            parse_uuid("")
        assert exc.value.status_code == 422

    def test_wrong_length_raises_422(self):
        with pytest.raises(DomainValidationError):
            parse_uuid("abc123")

    def test_non_hex_characters_raise_422(self):
        with pytest.raises(DomainValidationError):
            parse_uuid("gggg1111222233334444555566667777")

    def test_custom_field_name_in_error(self):
        with pytest.raises(DomainValidationError) as exc:
            parse_uuid("x", "novel_id")
        assert "novel_id" in exc.value.detail


class TestIsValidUUID:
    """is_valid_uuid — UUID 格式验证（不抛异常）"""

    def test_valid_uuid_returns_true(self):
        assert is_valid_uuid("c8f2a1e456784b3d9f1a2b3c4d5e6f71") is True

    def test_invalid_uuid_returns_false(self):
        assert is_valid_uuid("not-a-uuid") is False

    def test_empty_string_returns_false(self):
        assert is_valid_uuid("") is False

    def test_none_returns_false(self):
        # None 不是有效的字符串输入，is_valid_uuid 应返回 False
        try:
            result = is_valid_uuid(None)  # type: ignore[arg-type]
        except TypeError:
            result = False
        assert result is False

    def test_wrong_length_returns_false(self):
        assert is_valid_uuid("abc") is False

    def test_non_hex_returns_false(self):
        assert is_valid_uuid("zzzz1111222233334444555566667777") is False
