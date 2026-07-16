"""Prompt 模板加载器

从 backend/prompts/ 目录加载 .md prompt 文件，支持 {variable} 替换。
用法：

    from infrastructure.llm.prompt_loader import load_prompt

    prompt = load_prompt("shared_rules")
"""

from pathlib import Path


def _default_prompt_dir() -> Path:
    """Return the backend prompt directory without relying on the current cwd."""
    return Path(__file__).resolve().parents[2] / "prompts"


def resolve_prompt_path(name: str, prompt_dir: Path | str | None = None) -> Path:
    """Resolve a prompt template path and reject traversal-like names."""
    if (
        not name
        or "/" in name
        or "\\" in name
        or ".." in name
        or Path(name).is_absolute()
    ):
        raise ValueError(f"Invalid prompt name: {name!r}")

    base_dir = Path(prompt_dir) if prompt_dir is not None else _default_prompt_dir()
    return base_dir.resolve() / f"{name}.md"


def load_prompt(
    name: str,
    *,
    prompt_dir: Path | str | None = None,
    **kwargs: str,
) -> str:
    """加载 prompt 模板文件并替换 {variable}

    Args:
        name: 文件名（不含 .md 后缀）
        prompt_dir: 可选 prompt 目录；默认使用 backend/prompts
        **kwargs: 模板变量

    Returns:
        替换后的 prompt 文本
    """
    path = resolve_prompt_path(name, prompt_dir=prompt_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    content = path.read_text(encoding="utf-8")

    for key, value in kwargs.items():
        content = content.replace(f"{{{key}}}", str(value))

    return content
