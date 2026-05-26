"""Prompt 模板加载器

从 backend/prompts/ 目录加载 .md prompt 文件，支持 {variable} 替换。
用法：

    from infrastructure.llm.prompt_loader import load_prompt

    prompt = load_prompt("extract_chapter_scene",
        chapter_index=3,
        entity_names="王都、旧王都",
    )
"""

from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def load_prompt(name: str, **kwargs: str) -> str:
    """加载 prompt 模板文件并替换 {variable}

    Args:
        name: 文件名（不含 .md 后缀）
        **kwargs: 模板变量

    Returns:
        替换后的 prompt 文本
    """
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    content = path.read_text(encoding="utf-8")

    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))

    return content
