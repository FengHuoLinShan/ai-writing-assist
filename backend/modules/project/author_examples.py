"""作者好例/反例（写作示例）——AI 写作的 few-shot 资料存储。

作者用「以后照这个写 / 别这样写」把认可的语感段落登记为示例；
开启「用于 AI 写作」后，示例作为编译期 section 进入 writing.generate
的确认预览与上下文指纹（默认关闭）。存储沿用 editorial brief 先例：
Project.settings JSON，Pydantic schema extra="forbid"，首版不建表。
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, ValidationError
from modules.project.models import Project
from modules.project.services import ProjectService

_KEY = "author_examples_v1"
_WRITING_USE_KEY = "author_examples_for_writing_v1"

# 与 SF 对齐的首版数量上限：好例 ≤3、反例 ≤2。
_MAX_GOOD = 3
_MAX_BAD = 2


class AuthorExampleSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=200)
    candidate_id: str | None = Field(default=None, min_length=1, max_length=64)


class AuthorExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=8, max_length=64)
    kind: Literal["good", "bad"]
    content: str = Field(min_length=1, max_length=2000)
    note: str = Field(default="", max_length=500)
    source: AuthorExampleSource = Field(default_factory=AuthorExampleSource)
    capability_id: str = Field(min_length=1, max_length=128)

    @property
    def is_substantive(self) -> bool:
        return bool(self.content.strip())


class AuthorExamplesState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    examples: list[Annotated[AuthorExample, Field()]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_counts_and_uniqueness(self) -> "AuthorExamplesState":
        good = [item for item in self.examples if item.kind == "good"]
        bad = [item for item in self.examples if item.kind == "bad"]
        if len(good) > _MAX_GOOD:
            raise ValueError(f"好例最多 {_MAX_GOOD} 条")
        if len(bad) > _MAX_BAD:
            raise ValueError(f"反例最多 {_MAX_BAD} 条")
        ids = [item.id for item in self.examples]
        if len(ids) != len(set(ids)):
            raise ValueError("示例 id 重复")
        # 反例必须附作者的「差在哪」：负面示例若无说明可能反被模型模仿。
        missing_note = [
            item.id for item in bad if not item.note.strip()
        ]
        if missing_note:
            raise ValueError("反例必须填写差在哪里（备注）")
        return self


class AuthorExamplesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=0)
    state: AuthorExamplesState


def _writing_generate_substantive(state: AuthorExamplesState) -> bool:
    """是否存在会真正注入写作上下文的实质示例（与 loader 同口径）。"""
    return any(
        item.is_substantive and item.capability_id == "writing.generate"
        for item in state.examples
    )


def _validated_registry() -> frozenset[str]:
    from modules.evidence.contracts import CAPABILITY_REGISTRY

    return frozenset(CAPABILITY_REGISTRY)


def _validate_state(state: AuthorExamplesState) -> None:
    registry = _validated_registry()
    unknown = sorted({item.capability_id for item in state.examples} - registry)
    if unknown:
        raise ValidationError(f"未注册的能力编号: {', '.join(unknown)}")


async def read_author_examples(db, novel_id: str) -> dict:
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    saved = (row.settings or {}).get(_KEY) or {}
    state = AuthorExamplesState.model_validate(saved.get("state") or {})
    return {
        "version": int(saved.get("version") or 0),
        "examples": [item.model_dump() for item in state.examples],
    }


async def save_author_examples(db, novel_id: str, value: AuthorExamplesUpdate) -> dict:
    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, novel_id)
    _validate_state(value.state)
    row = await db.scalar(
        select(Project).where(Project.id == UUID(novel_id)).with_for_update()
    )
    saved = (row.settings or {}).get(_KEY) or {}
    current = int(saved.get("version") or 0)
    if value.expected_version != current:
        raise ConflictError("写作示例已有新版本，请刷新后重试")
    next_version = current + 1
    row.settings = {
        **(row.settings or {}),
        _KEY: {"version": next_version, "state": value.state.model_dump()},
    }
    await db.flush()
    return {
        "version": next_version,
        "examples": [item.model_dump() for item in value.state.examples],
    }


async def read_author_examples_for_writing(db, novel_id: str) -> dict | None:
    """作者开启「示例用于 AI 写作」且有实质示例时返回 {version, examples}。

    默认关闭；关闭或为空时返回 None，编译层不注入任何 section。
    """
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    settings = row.settings or {}
    enabled = (settings.get(_WRITING_USE_KEY) or {}).get("enabled") is True
    if not enabled:
        return None
    saved = settings.get(_KEY) or {}
    state = AuthorExamplesState.model_validate(saved.get("state") or {})
    substantive = [
        item
        for item in state.examples
        if item.is_substantive and item.capability_id == "writing.generate"
    ]
    if not substantive:
        return None
    return {
        "version": int(saved.get("version") or 0),
        "examples": [item.model_dump() for item in substantive],
    }


async def read_author_examples_writing_toggle(db, novel_id: str) -> dict:
    await ProjectService().get_project(db, novel_id)
    row = await db.scalar(select(Project).where(Project.id == UUID(novel_id)))
    enabled = ((row.settings or {}).get(_WRITING_USE_KEY) or {}).get("enabled") is True
    saved = (row.settings or {}).get(_KEY) or {}
    state = AuthorExamplesState.model_validate(saved.get("state") or {})
    return {
        "enabled": enabled,
        "effective": enabled and _writing_generate_substantive(state),
    }


async def set_author_examples_for_writing(db, novel_id: str, *, enabled: bool) -> dict:
    """切换「示例用于 AI 写作」；默认关闭，作者显式开启才生效。"""
    service = ProjectService()
    service._reject_demo_write()
    await service.get_project(db, novel_id)
    row = await db.scalar(
        select(Project).where(Project.id == UUID(novel_id)).with_for_update()
    )
    row.settings = {
        **(row.settings or {}),
        _WRITING_USE_KEY: {"enabled": bool(enabled)},
    }
    await db.flush()
    saved = row.settings.get(_KEY) or {}
    state = AuthorExamplesState.model_validate(saved.get("state") or {})
    return {
        "enabled": bool(enabled),
        "effective": bool(enabled) and _writing_generate_substantive(state),
    }
