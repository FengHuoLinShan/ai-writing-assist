"""Worldbuilding workspace ORM models."""

from __future__ import annotations

from .common import (
    JSON,
    PG_UUID,
    Base,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    StatusMixin,
    String,
    Text,
    TimestampMixin,
    UniqueConstraint,
    UUIDMixin,
    datetime,
    mapped_column,
    uuid,
)

# ============================================================
# Generation prompt templates
# ============================================================


class GenerationPromptTemplate(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "generation_prompt_templates"
    __table_args__ = (
        Index(
            "ix_generation_prompt_templates_novel_target_status_updated",
            "novel_id",
            "target_kind",
            "status",
            "updated_at",
        ),
        UniqueConstraint(
            "novel_id",
            "target_kind",
            "template_key",
            name="uq_generation_prompt_template_key",
        ),
        {"comment": "生成中心 Prompt 模板"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(
        String(64), nullable=False, default="world_object", index=True
    )
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_template: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom"
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="valid"
    )
    validation_issues_json: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GenerationPromptTemplateRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "generation_prompt_template_revisions"
    __table_args__ = (
        Index(
            "ix_generation_prompt_template_revisions_novel_template",
            "novel_id",
            "template_id",
        ),
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_generation_prompt_template_revision",
        ),
        {"comment": "生成中心 Prompt 模板版本"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("generation_prompt_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_template: Mapped[str] = mapped_column(
        String(32), nullable=False, default="custom"
    )
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    variables_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    validation_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="valid"
    )
    validation_issues_json: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# ============================================================
# World Bible pages and projections
# ============================================================


class WorldBiblePage(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "world_bible_pages"
    __table_args__ = (
        UniqueConstraint("novel_id", "page_key", name="uq_world_bible_page_key"),
        {"comment": "World Bible 手册页面"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_key: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sections_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    linked_asset_refs_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    activation_defaults_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    template_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorldBiblePageRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_bible_page_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "page_id",
            "version_number",
            name="uq_world_bible_page_revision_version",
        ),
        {"comment": "World Bible 页面版本"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision_reason: Mapped[str] = mapped_column(String(64), nullable=False)


class WorldBiblePageProjection(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "world_bible_page_projections"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "page_id",
            "projection_type",
            name="uq_world_bible_projection_type",
        ),
        {"comment": "World Bible 上下文投影缓存"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_pages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    projection_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_page_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_spans_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    omitted_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sensitivity: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stale_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorldBibleCategory(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "world_bible_categories"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "category_key",
            name="uq_world_bible_category_key",
        ),
        {"comment": "项目自定义 World Bible 类别"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#64748B")
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    default_template_key: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorldBiblePageDraft(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_bible_page_drafts"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "page_id",
            name="uq_world_bible_page_active_draft",
        ),
        {"comment": "World Bible 页面服务器工作稿"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_pages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    base_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    sections_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    linked_asset_refs_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    template_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorldBiblePageTemplate(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "world_bible_page_templates"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "template_key",
            name="uq_world_bible_page_template_key",
        ),
        {"comment": "项目自定义 World Bible 页面模板"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_key_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sections_schema_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    default_sections_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    validation_rules_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorldBiblePageTemplateRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_bible_page_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_world_bible_page_template_revision",
        ),
        {"comment": "World Bible 页面模板不可变版本"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_page_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorldBibleSynopsisRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_bible_synopsis_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "version_number",
            name="uq_world_bible_synopsis_revision_version",
        ),
        {"comment": "LLM 派生的不可变作者版世界观简介"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    claims_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_manifest_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    omitted_reasons_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    generation_meta_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class WorldBibleSynopsisHead(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "world_bible_synopsis_heads"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_world_bible_synopsis_head_novel"),
        {"comment": "世界观简介当前指针、失效与自动维护授权"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    desired_source_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_synopsis_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    pinned_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("world_bible_synopsis_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    active_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auto_refresh_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    authorization_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    enabled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# Knowledge tags, reader reveal, suggestions and conflicts
# ============================================================


class KnowledgeTag(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "knowledge_tags"
    __table_args__ = (
        UniqueConstraint("novel_id", "slug", name="uq_knowledge_tag_slug"),
        {"comment": "知识域标签"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class CharacterKnowledgeTag(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "character_knowledge_tags"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "character_id",
            "tag_id",
            "grant_source",
            name="uq_character_knowledge_tag_source",
        ),
        {"comment": "人物知识标签授权"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("characters.entity_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    grant_source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="manual",
    )
    source_ref_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_scene_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    source_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    author_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AssetKnowledgeTag(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "asset_knowledge_tags"
    __table_args__ = (
        Index("ix_asset_knowledge_tags_target_hash", "novel_id", "target_hash"),
        {"comment": "资产知识标签"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_tags.id", ondelete="CASCADE"),
        nullable=False,
    )


class KnowledgeTagExclusion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "knowledge_tag_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "character_id",
            "tag_id",
            name="uq_knowledge_tag_exclusion",
        ),
        {"comment": "人物派生知识标签排除"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("characters.entity_id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_tags.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")


class KnowledgeVisibilityPolicy(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "knowledge_visibility_policies"
    __table_args__ = (
        Index("ix_visibility_policies_target_hash", "novel_id", "target_hash"),
        {"comment": "知识可见性策略"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="public",
    )
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ReaderRevealPolicy(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "reader_reveal_policies"
    __table_args__ = (
        Index("ix_reader_reveal_target_hash", "novel_id", "target_hash"),
        Index("ix_reader_reveal_chapter", "novel_id", "reveal_chapter_index"),
        {"comment": "读者揭示点策略"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reveal_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reveal_scene_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    reveal_plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    public_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CreationSuggestion(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "creation_suggestion_queue"
    __table_args__ = {"comment": "创设建议队列"}

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_module: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    review_group: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action_schema: Mapped[str] = mapped_column(String(128), nullable=False, default="v1")
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    result_ref_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ConflictCheckQueueItem(Base, UUIDMixin, TimestampMixin, StatusMixin):
    __tablename__ = "conflict_check_queue"
    __table_args__ = {"comment": "世界设定冲突/叙事风险队列"}

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    source_module: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="world",
    )
    target: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    target_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resolution_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
