"""create revisioned World object dossier entries and preserve legacy profiles

Revision ID: 20261015_object_dossier_v2
Revises: 20261015_map_node_merge
Create Date: 2026-10-15
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_object_dossier_v2"
down_revision: str | None = "20261015_map_node_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "world_object_dossier_entries",
        sa.Column("entry_group_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_revision_id", sa.UUID(), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("facing_kind", sa.String(length=16), nullable=False),
        sa.Column("facing_key", sa.String(length=96), nullable=False),
        sa.Column("vocabulary_term_id", sa.UUID(), nullable=True),
        sa.Column("legacy_field_key", sa.String(length=96), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("legacy_value_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("start_anchor_kind", sa.String(length=16), nullable=True),
        sa.Column("start_anchor_id", sa.UUID(), nullable=True),
        sa.Column("end_anchor_kind", sa.String(length=16), nullable=True),
        sa.Column("end_anchor_id", sa.UUID(), nullable=True),
        sa.Column("revision_reason", sa.String(length=48), nullable=True),
        sa.Column("restored_from_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "facing_kind IN ('core', 'project')",
            name="ck_world_dossier_facing_kind",
        ),
        sa.CheckConstraint(
            "(facing_kind = 'core' AND vocabulary_term_id IS NULL) OR "
            "(facing_kind = 'project' AND vocabulary_term_id IS NOT NULL)",
            name="ck_world_dossier_facing_reference",
        ),
        sa.CheckConstraint(
            "source IN ('author', 'author_assistant', 'evolution_adoption', "
            "'spreadsheet_migration', 'legacy_import', 'object_completion')",
            name="ck_world_dossier_source",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'secret')",
            name="ck_world_dossier_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'needs_review', "
            "'covered_by_plot', 'cleared')",
            name="ck_world_dossier_status",
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_world_dossier_revision_number"
        ),
        sa.CheckConstraint(
            "(start_anchor_kind IS NULL AND start_anchor_id IS NULL) OR "
            "(start_anchor_kind IN ('scene', 'chapter') AND start_anchor_id IS NOT NULL)",
            name="ck_world_dossier_start_anchor",
        ),
        sa.CheckConstraint(
            "(end_anchor_kind IS NULL AND end_anchor_id IS NULL) OR "
            "(end_anchor_kind IN ('scene', 'chapter') AND end_anchor_id IS NOT NULL)",
            name="ck_world_dossier_end_anchor",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["core_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "vocabulary_term_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_world_dossier_vocabulary_same_novel",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "entry_group_id", "previous_revision_id"],
            [
                "world_object_dossier_entries.novel_id",
                "world_object_dossier_entries.entry_group_id",
                "world_object_dossier_entries.id",
            ],
            name="fk_world_dossier_previous_revision_same_group",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "id", name="uq_world_dossier_novel_id"),
        sa.UniqueConstraint(
            "novel_id",
            "entry_group_id",
            "revision_number",
            name="uq_world_dossier_revision_number",
        ),
        sa.UniqueConstraint(
            "novel_id",
            "entry_group_id",
            "id",
            name="uq_world_dossier_group_revision_id",
        ),
        comment="World object dossier entry history",
    )
    op.create_index(
        "ix_world_dossier_entity_status_facing",
        "world_object_dossier_entries",
        ["novel_id", "entity_id", "status", "facing_kind", "facing_key"],
    )
    op.create_index(
        "ix_world_dossier_legacy_field_status",
        "world_object_dossier_entries",
        ["novel_id", "entity_id", "legacy_field_key", "status"],
    )
    op.create_index(
        "ix_world_object_dossier_entries_entity_id",
        "world_object_dossier_entries",
        ["entity_id"],
    )
    op.create_index(
        "ix_world_object_dossier_entries_entry_group_id",
        "world_object_dossier_entries",
        ["entry_group_id"],
    )
    op.create_index(
        "ix_world_object_dossier_entries_novel_id",
        "world_object_dossier_entries",
        ["novel_id"],
    )
    op.create_index(
        "uq_world_dossier_active_group",
        "world_object_dossier_entries",
        ["novel_id", "entry_group_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    _backfill_legacy_profiles()


def _display_value(value: Any) -> tuple[str, Any | None]:
    if isinstance(value, str):
        return value, None
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                label = item.get("label") or item.get("name") or item.get("title")
                details = item.get("description") or item.get("content")
                parts.append(
                    "：".join(str(part) for part in (label, details) if part)
                    or "；".join(f"{key}：{val}" for key, val in item.items())
                )
            else:
                parts.append(str(item))
        return "；".join(part for part in parts if part), value
    if isinstance(value, dict):
        display = "；".join(f"{key}：{item}" for key, item in value.items())
        return display or json.dumps(value, ensure_ascii=False, sort_keys=True), value
    return str(value), None


def _insert_legacy_value(
    connection,
    entries: sa.Table,
    *,
    novel_id,
    entity_id,
    entity_status,
    facing_key: str,
    legacy_field_key: str,
    value: Any,
    visibility: str = "public",
    source_metadata: dict[str, Any] | None = None,
) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    display, structured = _display_value(value)
    if not display.strip():
        return
    connection.execute(
        entries.insert().values(
            id=uuid.uuid4(),
            novel_id=novel_id,
            entity_id=entity_id,
            entry_group_id=uuid.uuid4(),
            revision_number=1,
            previous_revision_id=None,
            facing_kind="core",
            facing_key=facing_key,
            vocabulary_term_id=None,
            legacy_field_key=legacy_field_key,
            content=display,
            tags_json=[],
            legacy_value_json=structured,
            metadata_json=source_metadata or {},
            source="legacy_import",
            source_refs_json=[],
            quote_text=None,
            visibility=visibility,
            status="active" if entity_status == "canonical" else "needs_review",
            start_anchor_kind=None,
            start_anchor_id=None,
            end_anchor_kind=None,
            end_anchor_id=None,
            revision_reason="legacy_backfill",
            restored_from_id=None,
        )
    )


def _backfill_legacy_profiles() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    entries = sa.Table("world_object_dossier_entries", metadata, autoload_with=connection)
    core_entities = sa.Table("core_entities", metadata, autoload_with=connection)
    for entity in connection.execute(
        sa.select(
            core_entities.c.id,
            core_entities.c.novel_id,
            core_entities.c.status,
            core_entities.c.summary,
            core_entities.c.public_info,
            core_entities.c.hidden_truth,
        )
    ).mappings():
        for field, facing, visibility in (
            ("summary", "overview", "public"),
            ("public_info", "public_info", "public"),
            ("hidden_truth", "truth", "secret"),
        ):
            _insert_legacy_value(
                connection,
                entries,
                novel_id=entity["novel_id"],
                entity_id=entity["id"],
                entity_status=entity["status"],
                facing_key=facing,
                legacy_field_key=field,
                value=entity[field],
                visibility=visibility,
            )

    characters = sa.Table("characters", metadata, autoload_with=connection)
    character_fields = {
        "role": ("identity_position", "public"),
        "appearance": ("appearance", "public"),
        "personality": ("personality", "public"),
        "desire": ("desire_fear", "public"),
        "fear": ("desire_fear", "public"),
        "secret": ("secret", "secret"),
        "weakness": ("abilities_limits", "public"),
        "stance": ("values_boundaries", "public"),
        "voice_style": ("speech_style", "public"),
        "behavior_rules": ("habits", "public"),
        "relationship_summary": ("relationship_summary", "public"),
    }
    for character in connection.execute(sa.select(characters)).mappings():
        core_status = connection.execute(
            sa.select(core_entities.c.status).where(
                core_entities.c.id == character["entity_id"],
                core_entities.c.novel_id == character["novel_id"],
            )
        ).scalar_one_or_none()
        if core_status is None:
            continue
        for field, (facing, visibility) in character_fields.items():
            _insert_legacy_value(
                connection,
                entries,
                novel_id=character["novel_id"],
                entity_id=character["entity_id"],
                entity_status=core_status,
                facing_key=facing,
                legacy_field_key=field,
                value=character[field],
                visibility=visibility,
            )

    profile_fields = {
        "species_profiles": {
            "origin_summary": ("history", "public"),
            "physiology_summary": ("physiology_lifespan", "public"),
            "lifespan": ("physiology_lifespan", "public"),
            "abilities_json": ("abilities_weaknesses", "public"),
            "weaknesses_json": ("abilities_weaknesses", "public"),
            "culture_summary": ("culture_customs", "public"),
            "language_summary": ("language", "public"),
        },
        "faction_profiles": {
            "ideology_summary": ("ideology", "public"),
            "leader_entity_ids_json": ("structure_positions", "public"),
            "member_rules": ("rules", "public"),
            "territory_refs_json": ("resources", "public"),
            "resources_json": ("resources", "public"),
        },
        "location_profiles": {
            "map_refs_json": ("geography", "public"),
            "climate": ("sensory_details", "public"),
            "population_summary": ("appearance_people", "public"),
            "resources_json": ("resources", "public"),
            "hazards_json": ("dangers", "public"),
            "controlling_faction_ids_json": ("control", "public"),
        },
        "rule_profiles": {
            "rule_domain": ("known_scope", "public"),
            "principle_summary": ("principle", "public"),
            "constraints_json": ("constraints", "public"),
            "exceptions_json": ("exceptions", "public"),
            "consequences_json": ("consequences", "public"),
        },
        "item_profiles": {
            "item_class": ("form_appearance", "public"),
            "powers_json": ("abilities_limits", "public"),
            "limitations_json": ("abilities_limits", "public"),
            "owner_entity_ids_json": ("meaning", "public"),
            "origin_summary": ("origin", "public"),
        },
        "secret_profiles": {
            "truth_summary": ("truth", "secret"),
            "holder_entity_ids_json": ("knowledge_scope", "secret"),
            "risk_level": ("risk", "secret"),
            "reveal_status": ("reveal_plan", "secret"),
            "linked_target_refs_json": ("reveal_plan", "secret"),
        },
    }
    for table_name, fields in profile_fields.items():
        if table_name not in sa.inspect(connection).get_table_names():
            continue
        profiles = sa.Table(table_name, metadata, autoload_with=connection)
        for profile in connection.execute(sa.select(profiles)).mappings():
            entity_status = connection.execute(
                sa.select(core_entities.c.status).where(
                    core_entities.c.id == profile["entity_id"],
                    core_entities.c.novel_id == profile["novel_id"],
                )
            ).scalar_one_or_none()
            if entity_status is None:
                continue
            provenance = {
                "profile_source": profile.get("source"),
                "confidence": profile.get("confidence"),
                "evidence_refs": profile.get("evidence_refs_json") or [],
                "profile_extra": profile.get("extra_json") or {},
            }
            status = profile.get("status") or entity_status
            for field, (facing, visibility) in fields.items():
                _insert_legacy_value(
                    connection,
                    entries,
                    novel_id=profile["novel_id"],
                    entity_id=profile["entity_id"],
                    entity_status=(
                        "canonical"
                        if entity_status == "canonical" and status == "canonical"
                        else "needs_review"
                    ),
                    facing_key=facing,
                    legacy_field_key=f"{table_name}.{field}",
                    value=profile.get(field),
                    visibility=visibility,
                    source_metadata=provenance,
                )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM world_object_dossier_entries")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "World dossier history is append-only; export and remove its entries "
            "before downgrading this revision"
        )
    op.drop_index(
        "uq_world_dossier_active_group", table_name="world_object_dossier_entries"
    )
    op.drop_index(
        "ix_world_object_dossier_entries_entry_group_id",
        table_name="world_object_dossier_entries",
    )
    op.drop_index(
        "ix_world_object_dossier_entries_entity_id",
        table_name="world_object_dossier_entries",
    )
    op.drop_index(
        "ix_world_object_dossier_entries_novel_id",
        table_name="world_object_dossier_entries",
    )
    op.drop_index(
        "ix_world_dossier_entity_status_facing",
        table_name="world_object_dossier_entries",
    )
    op.drop_index(
        "ix_world_dossier_legacy_field_status",
        table_name="world_object_dossier_entries",
    )
    op.drop_table("world_object_dossier_entries")
