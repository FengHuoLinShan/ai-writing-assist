"""World 世界书资料集导入 Pydantic Schema — manifest、payload、预览与应用契约。

自 schemas.py 拆出（P8 文件行数门禁：schemas.py 超限只许下降），
依赖方向单向：本模块可引用 schemas.py 的基元与类型，反向禁止。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.schemas import _validate_lower_sha256


class WorldbookImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(..., max_length=2 * 1024 * 1024)


class WorldbookImportLegacyBinding(BaseModel):
    """接续旧来源的待绑定映射（m1-contract 第 2 条，逐条可核对）。

    ``target_kind`` 区分工作稿与已发布页：已发布页的 meta 补写按契约
    走发布链显式确认路径（M3 未落地），本轮 apply 不改写其归属，预览必须
    如实披露，不得让作者以为绑定已生效。
    """

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(..., min_length=64, max_length=64)
    legacy_source_path: str = Field(..., min_length=1, max_length=1024)
    rel_path: str = Field(..., min_length=1, max_length=1024)
    target_kind: Literal["draft", "page"] | None = None


class WorldbookImportLinkDetail(BaseModel):
    """单条引用的解析明细（m1-contract 第 4 条：明细进预览清单）。

    ``alias``（``|显示文本``）与 ``anchor``（``#段落``）原样保留，供导航与
    恢复；``resolved_path``/``resolved_title`` 记录命中对象（resolved 与
    unselected 有值），供作者定位目标页。仅展示用，不参与任何指纹。
    """

    model_config = ConfigDict(extra="forbid")

    raw: str = Field(..., min_length=1, max_length=2048)
    target: str = Field(..., min_length=1, max_length=1024)
    alias: str = Field(default="", max_length=1024)
    anchor: str = Field(default="", max_length=1024)
    origin: Literal["free_text", "frontmatter"]
    state: Literal["resolved", "ambiguous", "unresolved", "unselected"]
    resolved_path: str | None = Field(default=None, max_length=1024)
    resolved_title: str | None = Field(default=None, max_length=255)


class WorldbookImportLinkDetailGroup(BaseModel):
    """单页引用明细组；``truncated`` 标记超出每页 200 条的截断。"""

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(..., min_length=64, max_length=64)
    truncated: bool = False
    details: list[WorldbookImportLinkDetail] = Field(default_factory=list, max_length=200)

    @field_validator("source_key")
    @classmethod
    def validate_source_key(cls, value: str) -> str:
        return _validate_lower_sha256(value, "source_key")


class WorldbookImportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_worldbook_import.v1", "world_worldbook_import.v2"] = (
        "world_worldbook_import.v1"
    )
    # 受 schema 限定的格式选择；"auto" 沿用目录标记检测（m1-contract 第 1 条）。
    source_format: Literal["auto", "obsidian", "llmwiki", "wiki_markdown", "generic"] = (
        "auto"
    )
    # 作者声明的资料集名；dataset_key 由服务端派生，不接收客户端值
    # （m1-contract 第 2 条）。长度上限 1–80 在服务端按归一化后名称校验。
    dataset_name: str | None = Field(default=None, min_length=1, max_length=200)
    # 资料集提交语义：continue 沿用既有资料集四态（v1 兼容默认）；new 显式声明
    # 新资料集（派生 key 已存在即拒绝）；adopt_legacy 显式接续旧来源（legacy
    # source_path 剥根得等效 rel_path 逐条匹配并补写 dataset 字段）。
    dataset_intent: Literal["continue", "new", "adopt_legacy"] = "continue"
    commit_mode: Literal["full_snapshot", "append"] = "full_snapshot"
    files: list[WorldbookImportFile] = Field(..., min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_dataset_intent(self) -> WorldbookImportManifest:
        if self.dataset_intent != "continue" and self.dataset_name is None:
            raise ValueError("dataset_intent requires dataset_name")
        return self


class WorldbookImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(..., min_length=64, max_length=64)
    path: str = Field(..., min_length=1, max_length=1024)
    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(default="source_material", min_length=1, max_length=64)
    source_hash: str = Field(..., min_length=64, max_length=64)
    action: Literal["create", "update", "preserve", "conflict", "missing"]
    target_id: str | None = None
    target_kind: Literal["draft", "page"] | None = None
    current_content_hash: str | None = None
    reason: str = Field(default="", max_length=1000)
    # 四态 Wiki 引用计数（m1-contract 第 4 条，纳入 preview_hash）：
    # resolved/ambiguous/unresolved/unselected 按页内引用出现次数统计（正文
    # 双链 + frontmatter related）；物化 refs 另按去重与每页 100 上限截断，
    # 超限在对应 item.reason 明示。ambiguous/unresolved/unselected 不建引用。
    link_summary: dict[str, int] = Field(
        default_factory=lambda: {
            "resolved": 0,
            "ambiguous": 0,
            "unresolved": 0,
            "unselected": 0,
        }
    )

    @field_validator("source_key", "source_hash", "current_content_hash")
    @classmethod
    def validate_hashes(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_lower_sha256(value, info.field_name)


class WorldbookImportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # v1 存量 pending 预览必须仍可读取；写入端按资料集语义选择版本
    # （m1-contract 第 5 条）。
    schema_version: Literal["world_worldbook_import.v1", "world_worldbook_import.v2"]
    source_format: Literal["obsidian", "llmwiki", "wiki_markdown", "generic"]
    manifest_hash: str = Field(..., min_length=64, max_length=64)
    preview_hash: str = Field(..., min_length=64, max_length=64)
    # 资料集语义字段；dataset_key 为空表示 legacy 提交（v1 归一化默认值）。
    dataset_name: str | None = Field(default=None, min_length=1, max_length=200)
    dataset_key: str | None = Field(default=None, min_length=64, max_length=64)
    dataset_intent: Literal["continue", "new", "adopt_legacy"] = "continue"
    commit_mode: Literal["full_snapshot", "append"] = "full_snapshot"
    # dataset 提交中 files[].path 统一为 rel_path；原始含根名路径仅保存在
    # source_paths（rel_path → 原始路径），用于回放时按原语义写
    # page_meta.worldbook_import.source_path，不参与任何指纹（m1-contract 第 2/8 条）。
    source_paths: dict[str, str] = Field(default_factory=dict, max_length=2000)
    files: list[WorldbookImportFile] = Field(..., min_length=1, max_length=2000)
    items: list[WorldbookImportItem] = Field(default_factory=list, max_length=4000)
    ignored_paths: list[str] = Field(default_factory=list, max_length=2000)
    # 接续旧来源的待绑定映射快照；仅展示与恢复预览用，判定要素已由 items
    # （target/current_hash）纳入 preview_hash（m1-contract 第 2/5 条）。
    legacy_bindings: list[WorldbookImportLegacyBinding] = Field(
        default_factory=list, max_length=2000
    )
    # 每页引用明细快照（m1-contract 第 4 条「明细进预览清单」；r7 定案：随
    # payload 持久化以支撑恢复预览的冻结语义，但不入指纹，先例同
    # legacy_bindings）。四态计数仍在 items.link_summary 并纳入 preview_hash。
    link_details: list[WorldbookImportLinkDetailGroup] = Field(
        default_factory=list, max_length=2000
    )

    @field_validator("manifest_hash", "preview_hash", "dataset_key")
    @classmethod
    def validate_hashes(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _validate_lower_sha256(value, info.field_name)

    @model_validator(mode="after")
    def validate_dataset_intent(self) -> WorldbookImportPayload:
        if self.dataset_key is None and self.dataset_intent != "continue":
            raise ValueError("dataset_intent requires dataset_key")
        return self

    @model_validator(mode="after")
    def validate_total_size(self) -> WorldbookImportPayload:
        if (
            sum(len(item.content.encode("utf-8")) for item in self.files)
            > 25 * 1024 * 1024
        ):
            raise ValueError("worldbook import exceeds 25 MiB")
        return self


class WorldbookImportPreviewResponse(BaseModel):
    suggestion_id: str
    source_format: Literal["obsidian", "llmwiki", "wiki_markdown", "generic"]
    manifest_hash: str
    preview_hash: str
    counts: dict[str, int]
    items: list[WorldbookImportItem]
    ignored_paths: list[str] = Field(default_factory=list)
    dataset_name: str | None = None
    dataset_key: str | None = None
    dataset_intent: str | None = None
    commit_mode: str | None = None
    legacy_bindings: list[WorldbookImportLegacyBinding] = Field(default_factory=list)
    link_details: list[WorldbookImportLinkDetailGroup] = Field(default_factory=list)


class WorldbookImportApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_preview_hash: str = Field(..., min_length=64, max_length=64)

    @field_validator("expected_preview_hash")
    @classmethod
    def validate_preview_hash(cls, value: str) -> str:
        return _validate_lower_sha256(value, "expected_preview_hash")


class WorldbookImportApplyResponse(BaseModel):
    suggestion_id: str
    status: Literal["accepted"]
    manifest_hash: str
    preview_hash: str
    counts: dict[str, int]
    draft_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
