"""Add the immutable world Canon foundation.

Revision ID: 20260827_world_canon_foundation
Revises: 20260822_relation_alias_kinds
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260827_world_canon_foundation"
down_revision = "20260822_relation_alias_kinds"
branch_labels = None
depends_on = None

_KERNEL = "world-kernel.v1"
_BASE_SCHEMA = "builtin:world-base-schema.v1"
_AUTH_POLICY = "builtin:world-canon-author-policy.v1"
_POLICY_DIGEST = hashlib.sha256(_AUTH_POLICY.encode()).hexdigest()


def _canonical_digest(value: dict) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def upgrade() -> None:
    op.create_table(
        "world_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("regime_kind", sa.String(16), nullable=False),
        sa.Column(
            "belief_holder_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("core_entities.id", ondelete="RESTRICT"),
        ),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("statement_kind", sa.String(32), nullable=False),
        sa.Column("statement_version", sa.Integer(), nullable=False),
        sa.Column("statement_payload_json", sa.JSON(), nullable=False),
        sa.Column("schema_ref_json", sa.JSON(), nullable=False),
        sa.Column("time_scope_json", sa.JSON(), nullable=False),
        sa.Column("source_revision_ref_json", sa.JSON(), nullable=False),
        sa.Column("hard_ground_refs_json", sa.JSON(), nullable=False),
        sa.Column("cite_refs_json", sa.JSON(), nullable=False),
        sa.Column("provenance_actor_ref", sa.String(128)),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "regime_kind IN ('world', 'belief')", name="ck_world_assertion_regime"
        ),
        sa.CheckConstraint(
            "polarity IN ('positive', 'negative')", name="ck_world_assertion_polarity"
        ),
        sa.CheckConstraint(
            "(regime_kind = 'world' AND belief_holder_entity_id IS NULL) OR "
            "(regime_kind = 'belief' AND belief_holder_entity_id IS NOT NULL)",
            name="ck_world_assertion_belief_holder",
        ),
        sa.UniqueConstraint("id", "novel_id", name="uq_world_assertion_id_novel"),
        sa.UniqueConstraint(
            "novel_id", "content_hash", name="uq_world_assertion_content_hash"
        ),
    )
    op.create_index("ix_world_assertions_novel_id", "world_assertions", ["novel_id"])

    op.create_table(
        "world_canon_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("kernel_spec_version", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("admission_receipt_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "novel_id", name="uq_world_canon_revision_id_novel"),
        sa.ForeignKeyConstraint(
            ["parent_id", "novel_id"],
            ["world_canon_revisions.id", "world_canon_revisions.novel_id"],
            ondelete="CASCADE",
            name="fk_world_canon_parent_same_novel",
        ),
    )
    op.create_index(
        "ix_world_canon_revisions_novel_id", "world_canon_revisions", ["novel_id"]
    )

    op.create_table(
        "world_canon_heads",
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("canon_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("head_version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canon_revision_id", "novel_id"],
            ["world_canon_revisions.id", "world_canon_revisions.novel_id"],
            ondelete="CASCADE",
            name="fk_world_canon_head_same_novel",
        ),
    )

    op.create_table(
        "entity_profile_template_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entity_profile_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("profile_type", sa.String(64), nullable=False),
        sa.Column("template_schema_json", sa.JSON(), nullable=False),
        sa.Column("display_schema_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_entity_profile_template_revision",
        ),
        sa.UniqueConstraint(
            "id", "novel_id", name="uq_entity_profile_template_revision_id_novel"
        ),
    )
    op.create_index(
        "ix_entity_profile_template_revisions_novel_id",
        "entity_profile_template_revisions",
        ["novel_id"],
    )
    op.create_index(
        "ix_entity_profile_template_revisions_template_id",
        "entity_profile_template_revisions",
        ["template_id"],
    )

    _backfill_profile_template_revisions()
    _backfill_c0()
    _install_immutable_triggers()


def _backfill_profile_template_revisions() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, novel_id, profile_type, template_schema_json, "
            "display_schema_json, created_at, updated_at FROM entity_profile_templates"
        )
    ).mappings()
    table = sa.table(
        "entity_profile_template_revisions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.column("template_id", postgresql.UUID(as_uuid=True)),
        sa.column("version_number", sa.Integer()),
        sa.column("profile_type", sa.String()),
        sa.column("template_schema_json", sa.JSON()),
        sa.column("display_schema_json", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    values = []
    for row in rows:
        snapshot = {
            "profile_type": row["profile_type"],
            "template_schema_json": row["template_schema_json"] or {},
            "display_schema_json": row["display_schema_json"] or {},
        }
        values.append(
            {
                "id": uuid.uuid4(),
                "novel_id": row["novel_id"],
                "template_id": row["id"],
                "version_number": 1,
                **snapshot,
                "content_hash": _canonical_digest(snapshot),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    if values:
        bind.execute(table.insert(), values)


def _backfill_c0() -> None:
    bind = op.get_bind()
    projects = bind.execute(
        sa.text(
            "SELECT id, owner_id FROM projects WHERE project_kind = 'author' ORDER BY id"
        )
    ).mappings()
    revisions = sa.table(
        "world_canon_revisions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.column("kernel_spec_version", sa.String()),
        sa.column("manifest_json", sa.JSON()),
        sa.column("manifest_digest", sa.String()),
        sa.column("admission_receipt_json", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    heads = sa.table(
        "world_canon_heads",
        sa.column("novel_id", postgresql.UUID(as_uuid=True)),
        sa.column("canon_revision_id", postgresql.UUID(as_uuid=True)),
        sa.column("head_version", sa.BigInteger()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    revision_rows = []
    head_rows = []
    for project in projects:
        canon_id = uuid.uuid4()
        novel_id = project["id"]
        manifest = {
            "schema_version": "world_canon_manifest.v1",
            "novel_id": str(novel_id),
            "kernel_spec_version": _KERNEL,
            "resources": [],
            "selected_assertion_ids": [],
            "schema_refs": [_BASE_SCHEMA],
            "rule_refs": [],
            "policy_refs": sorted([_BASE_SCHEMA, _AUTH_POLICY]),
            "calendar_refs": [],
            "correspondence_refs": [],
            "inactive_resource_refs": [],
        }
        digest = _canonical_digest(manifest)
        receipt = {
            "schema_version": "world_canon_admission_receipt.v1",
            "novel_id": str(novel_id),
            "canon_revision_id": str(canon_id),
            "manifest_digest": digest,
            "committer_principal": str(project["owner_id"]),
            "action": "initialize",
            "authorization_scope": "world.canon.commit",
            "authorization_policy_ref": _AUTH_POLICY,
            "authorization_policy_digest": _POLICY_DIGEST,
            "decision": "allowed",
            "committed_at": now.isoformat().replace("+00:00", "Z"),
            "expected_previous_head": None,
        }
        revision_rows.append(
            {
                "id": canon_id,
                "novel_id": novel_id,
                "parent_id": None,
                "kernel_spec_version": _KERNEL,
                "manifest_json": manifest,
                "manifest_digest": digest,
                "admission_receipt_json": receipt,
                "created_at": now,
            }
        )
        head_rows.append(
            {
                "novel_id": novel_id,
                "canon_revision_id": canon_id,
                "head_version": 0,
                "updated_at": now,
            }
        )
    if revision_rows:
        bind.execute(revisions.insert(), revision_rows)
        bind.execute(heads.insert(), head_rows)


def _install_immutable_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_world_immutable_write() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION '% is immutable', TG_TABLE_NAME USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in (
        "world_assertions",
        "world_canon_revisions",
        "entity_profile_template_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION reject_world_immutable_write()"
        )


def downgrade() -> None:
    for table in (
        "world_assertions",
        "world_canon_revisions",
        "entity_profile_template_revisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_world_immutable_write")
    op.drop_table("world_canon_heads")
    op.drop_index(
        "ix_entity_profile_template_revisions_template_id",
        table_name="entity_profile_template_revisions",
    )
    op.drop_index(
        "ix_entity_profile_template_revisions_novel_id",
        table_name="entity_profile_template_revisions",
    )
    op.drop_table("entity_profile_template_revisions")
    op.drop_index("ix_world_canon_revisions_novel_id", table_name="world_canon_revisions")
    op.drop_table("world_canon_revisions")
    op.drop_index("ix_world_assertions_novel_id", table_name="world_assertions")
    op.drop_table("world_assertions")
