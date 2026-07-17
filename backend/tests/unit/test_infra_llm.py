"""
Infrastructure: LLM 模块单元测试

覆盖:
- llm/prompt_loader.py — load_prompt (纯逻辑, 无外部依赖)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.llm.prompt_loader import load_prompt, resolve_prompt_path


class TestLoadPrompt:
    """load_prompt 单元测试"""

    def test_load_success(self, tmp_path: Path) -> None:
        """GREEN: 正常加载 .md 文件并替换变量"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "test_template.md"
        prompt_file.write_text(
            "角色：{character_name}，场景：{scene_name}", encoding="utf-8"
        )

        result = load_prompt(
            "test_template",
            prompt_dir=prompts_dir,
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

        result = load_prompt("multi_var", prompt_dir=prompts_dir, a="1", b="2", c="3")

        assert result == "1 + 2 + 3"

    def test_no_variables_in_template(self, tmp_path: Path) -> None:
        """GREEN: 模板无变量时原样返回"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "plain.md"
        prompt_file.write_text("纯文本模板，没有占位符", encoding="utf-8")

        result = load_prompt("plain", prompt_dir=prompts_dir, unused_var="xxx")

        assert result == "纯文本模板，没有占位符"

    def test_unused_variable_not_replaced(self, tmp_path: Path) -> None:
        """GREEN: 模板中的占位符没有对应实参时保持原样"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "unused.md"
        prompt_file.write_text("你好，{name}", encoding="utf-8")

        result = load_prompt("unused", prompt_dir=prompts_dir)

        assert result == "你好，{name}"

    def test_file_not_found(self) -> None:
        """RED: 文件不存在时抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            load_prompt("nonexistent_template", prompt_dir=Path("/nonexistent/prompts"))

    def test_empty_file(self, tmp_path: Path) -> None:
        """GREEN: 空文件返回空字符串"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "empty.md"
        prompt_file.write_text("", encoding="utf-8")

        result = load_prompt("empty", prompt_dir=prompts_dir)

        assert result == ""

    def test_unicode_content(self, tmp_path: Path) -> None:
        """GREEN: 正确处理中文/Unicode 内容"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "unicode.md"
        prompt_file.write_text("「{title}」——{author}", encoding="utf-8")

        result = load_prompt(
            "unicode",
            prompt_dir=prompts_dir,
            title="百年孤独",
            author="马尔克斯",
        )

        assert result == "「百年孤独」——马尔克斯"

    def test_value_converted_to_string(self, tmp_path: Path) -> None:
        """GREEN: 非字符串值自动转换为字符串"""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "numeric.md"
        prompt_file.write_text("第{chapter}章，共{count}节", encoding="utf-8")

        result = load_prompt("numeric", prompt_dir=prompts_dir, chapter=3, count=5)

        assert result == "第3章，共5节"

    @pytest.mark.parametrize(
        "name",
        [
            "../secret",
            "nested/template",
            r"nested\template",
            "/tmp/template",
            "template..bak",
            "",
        ],
    )
    def test_invalid_name_rejected(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(ValueError, match="Invalid prompt name"):
            resolve_prompt_path(name, prompt_dir=tmp_path)

    def test_explicit_prompt_dir_is_not_cwd_dependent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prompts_dir = tmp_path / "prompts"
        other_dir = tmp_path / "other"
        prompts_dir.mkdir()
        other_dir.mkdir()
        (prompts_dir / "cwd_safe.md").write_text("路径：{value}", encoding="utf-8")

        monkeypatch.chdir(other_dir)

        result = load_prompt("cwd_safe", prompt_dir=prompts_dir, value="显式目录")

        assert result == "路径：显式目录"

    def test_retired_prompt_files_are_absent_and_unreferenced(self) -> None:
        for prompt_name in (
            "shared_rules",
            "structure_world_character",
            "structure_plot",
            "structure_chapter_scene",
        ):
            assert not resolve_prompt_path(prompt_name).exists()
        for prompt_name in (
            "p20_plot_thread",
            "p20_outline_arc",
            "p20_planned_scene",
        ):
            assert "P20" in load_prompt(prompt_name)
        assert "P21" in load_prompt("rag_reranker")
