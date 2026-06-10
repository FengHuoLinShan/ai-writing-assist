"""
Infrastructure: LLM 模块单元测试

覆盖:
- llm/prompt_loader.py — load_prompt (纯逻辑, 无外部依赖)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.llm.prompt_loader import load_prompt


class TestLoadPrompt:
    """load_prompt 单元测试"""

    def test_load_success(self, tmp_path: Path) -> None:
        """GREEN: 正常加载 .md 文件并替换变量"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test_template.md"
        prompt_file.write_text("角色：{character_name}，场景：{scene_name}", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt(
                "test_template",
                character_name="张三",
                scene_name="王都",
            )

        assert result == "角色：张三，场景：王都"

    def test_load_multiple_variables(self, tmp_path: Path) -> None:
        """GREEN: 多个变量替换"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "multi_var.md"
        prompt_file.write_text("{a} + {b} + {c}", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("multi_var", a="1", b="2", c="3")

        assert result == "1 + 2 + 3"

    def test_no_variables_in_template(self, tmp_path: Path) -> None:
        """GREEN: 模板无变量时原样返回"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "plain.md"
        prompt_file.write_text("纯文本模板，没有占位符", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("plain", unused_var="xxx")

        assert result == "纯文本模板，没有占位符"

    def test_unused_variable_not_replaced(self, tmp_path: Path) -> None:
        """GREEN: 模板中的占位符没有对应实参时保持原样"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "unused.md"
        prompt_file.write_text("你好，{name}", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("unused")

        assert result == "你好，{name}"

    def test_file_not_found(self) -> None:
        """RED: 文件不存在时抛出 FileNotFoundError"""
        with patch(
            "infrastructure.llm.prompt_loader._PROMPT_DIR",
            Path("/nonexistent/prompts"),
        ):
            with pytest.raises(FileNotFoundError, match="nonexistent"):
                load_prompt("nonexistent_template")

    def test_empty_file(self, tmp_path: Path) -> None:
        """GREEN: 空文件返回空字符串"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "empty.md"
        prompt_file.write_text("", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("empty")

        assert result == ""

    def test_unicode_content(self, tmp_path: Path) -> None:
        """GREEN: 正确处理中文/Unicode 内容"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "unicode.md"
        prompt_file.write_text("「{title}」——{author}", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("unicode", title="百年孤独", author="马尔克斯")

        assert result == "「百年孤独」——马尔克斯"

    def test_value_converted_to_string(self, tmp_path: Path) -> None:
        """GREEN: 非字符串值自动转换为字符串"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "numeric.md"
        prompt_file.write_text("第{chapter}章，共{count}节", encoding="utf-8")

        with patch("infrastructure.llm.prompt_loader._PROMPT_DIR", prompts_dir):
            result = load_prompt("numeric", chapter=3, count=5)

        assert result == "第3章，共5节"
