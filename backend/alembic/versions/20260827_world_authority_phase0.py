"""Add the accepted Phase 0 world authority kernel.

Revision ID: 20260827_world_authority_phase0
Revises: 20260822_relation_alias_kinds
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260827_world_authority_phase0"
down_revision = "20260822_relation_alias_kinds"
branch_labels = None
depends_on = None

_BOOTSTRAP_NAMESPACE = uuid.UUID("7d771d15-3f43-4d19-99c9-0d525747794f")
_KERNEL_REF = {
    "artifact_id": "world.canon-kernel",
    "version": 1,
    "digest": "f8d47106cd0c8803739815de39439bbb6d6d95e4b0657d63763060f82671ff6c",
}
_SCHEMA_REF = {
    "artifact_id": "world.statement-schema",
    "version": 1,
    "digest": "3eda28fd8a246e2c44cfd36683b754b221de5a340ce0c04be58a85f186c6c81e",
}
_RULE_REF = {
    "artifact_id": "world.canon-rules.empty",
    "version": 1,
    "digest": "c110c7c624f2715b92eb5b0283b316470fbb8b2a6ab49379c157ec014920bad1",
}
_BOOTSTRAP_POLICY_REF = {
    "artifact_id": "world.canon.bootstrap-empty",
    "version": 1,
    "digest": "a1104c58dcb18c278a1fab2b5b944b4f76d05a49d9a22a2412df1e9e7b56cc29",
}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("floats are forbidden in world authority canonical values")
    if isinstance(value, str):
        return unicodedata.normalize(
            "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
        )
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _canonical_value(str(key))
            if normalized_key in normalized:
                raise ValueError("canonical object keys must remain unique")
            normalized[normalized_key] = _canonical_value(item)
        return normalized
    return value


def _json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _empty_manifest() -> dict[str, Any]:
    return {
        "kind": "canon_manifest",
        "version": 1,
        "active_resources": [],
        "selected_assertions": [],
        "kernel_ref": _KERNEL_REF,
        "schema_refs": [_SCHEMA_REF],
        "rule_ref": _RULE_REF,
        "validation_policy_ref": None,
        "calendar_ref": None,
        "pinned_dependencies": [],
        "family_authority": {
            "name": "formal-disabled",
            "typed_scalar": "formal-disabled",
            "binary_relation": "formal-disabled",
            "event_time": "formal-disabled",
            "belief": "formal-disabled",
        },
    }


def _create_tables() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB(astext_type=sa.Text())
    timestamp = sa.DateTime(timezone=True)

    op.create_table(
        "world_assertions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("regime", sa.String(64), nullable=False),
        sa.Column("polarity", sa.String(16), nullable=False),
        sa.Column("statement_json", json_type, nullable=False),
        sa.Column("schema_ref_json", json_type, nullable=False),
        sa.Column("time_scope_json", json_type, nullable=False),
        sa.Column("source_refs_json", json_type, nullable=False),
        sa.Column("hard_ground_refs_json", json_type, nullable=False),
        sa.Column("provenance_actor_ref_json", json_type, nullable=True),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "regime = 'objective_world.v1'", name="ck_world_assertions_regime"
        ),
        sa.CheckConstraint(
            "polarity IN ('positive', 'negative')",
            name="ck_world_assertions_polarity",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id", "content_digest", name="uq_world_assertion_digest"
        ),
    )
    op.create_index("ix_world_assertions_novel_id", "world_assertions", ["novel_id"])

    op.create_table(
        "world_canon_revisions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", uuid_type, nullable=True),
        sa.Column("manifest_json", json_type, nullable=False),
        sa.Column("manifest_digest", sa.String(64), nullable=False),
        sa.Column("receipt_json", json_type, nullable=False),
        sa.Column("decision_id", uuid_type, nullable=False),
        sa.Column("decision_digest", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "id", name="uq_world_canon_revision_novel_id"),
        sa.UniqueConstraint(
            "novel_id", "version_number", name="uq_world_canon_revision_version"
        ),
        sa.UniqueConstraint(
            "novel_id", "decision_id", name="uq_world_canon_revision_decision"
        ),
    )
    op.create_index(
        "ix_world_canon_revisions_novel_id", "world_canon_revisions", ["novel_id"]
    )
    op.create_foreign_key(
        "fk_world_canon_revision_parent_same_novel",
        "world_canon_revisions",
        "world_canon_revisions",
        ["novel_id", "parent_revision_id"],
        ["novel_id", "id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "world_canon_heads",
        sa.Column("novel_id", uuid_type, primary_key=True),
        sa.Column("current_revision_id", uuid_type, nullable=False),
        sa.Column(
            "updated_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "current_revision_id"],
            ["world_canon_revisions.novel_id", "world_canon_revisions.id"],
            ondelete="CASCADE",
            name="fk_world_canon_head_revision_same_novel",
        ),
    )

    op.create_unique_constraint(
        "uq_profile_template_novel_id", "entity_profile_templates", ["novel_id", "id"]
    )
    op.create_table(
        "entity_profile_template_revisions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("template_id", uuid_type, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", json_type, nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("revision_reason", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            timestamp,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "template_id"],
            ["entity_profile_templates.novel_id", "entity_profile_templates.id"],
            ondelete="CASCADE",
            name="fk_profile_template_revision_same_novel",
        ),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_entity_profile_template_revision",
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
    op.create_unique_constraint(
        "uq_world_bible_page_novel_id",
        "world_bible_pages",
        ["novel_id", "id"],
    )
    op.create_foreign_key(
        "fk_world_bible_page_revision_same_novel",
        "world_bible_page_revisions",
        "world_bible_pages",
        ["novel_id", "page_id"],
        ["novel_id", "id"],
        ondelete="CASCADE",
    )


def _backfill_revision_digests() -> None:
    bind = op.get_bind()
    json_type = sa.JSON()
    page_revisions = sa.table(
        "world_bible_page_revisions",
        sa.column("id"),
        sa.column("novel_id"),
        sa.column("page_id"),
        sa.column("snapshot_json", json_type),
        sa.column("revision_digest"),
    )
    for row in bind.execute(sa.select(page_revisions)).mappings():
        resource = {
            "kind": "world_bible_page",
            "version": 1,
            "novel_id": str(row["novel_id"]),
            "resource_id": str(row["page_id"]),
        }
        digest_input = {
            "kind": "resource_revision_digest_input",
            "version": 1,
            "resource": resource,
            "revision_id": str(row["id"]),
            "snapshot": row["snapshot_json"],
        }
        bind.execute(
            page_revisions.update()
            .where(page_revisions.c.id == row["id"])
            .values(revision_digest=_digest(digest_input))
        )

    templates = sa.table(
        "entity_profile_templates",
        sa.column("id"),
        sa.column("novel_id"),
        sa.column("profile_type"),
        sa.column("template_schema_json", json_type),
        sa.column("display_schema_json", json_type),
        sa.column("status"),
        sa.column("version_number"),
    )
    revisions = sa.table(
        "entity_profile_template_revisions",
        sa.column("id"),
        sa.column("novel_id"),
        sa.column("template_id"),
        sa.column("version_number"),
        sa.column("snapshot_json", json_type),
        sa.column("revision_digest"),
        sa.column("revision_reason"),
        sa.column("created_by"),
    )
    for row in bind.execute(sa.select(templates)).mappings():
        revision_id = uuid.uuid4()
        snapshot = {
            "profile_type": row["profile_type"],
            "template_schema_json": row["template_schema_json"],
            "display_schema_json": row["display_schema_json"],
            "version_number": row["version_number"],
            "status": row["status"],
        }
        resource = {
            "kind": "entity_profile_template",
            "version": 1,
            "novel_id": str(row["novel_id"]),
            "resource_id": str(row["id"]),
        }
        digest_input = {
            "kind": "resource_revision_digest_input",
            "version": 1,
            "resource": resource,
            "revision_id": str(revision_id),
            "snapshot": snapshot,
        }
        bind.execute(
            revisions.insert().values(
                id=revision_id,
                novel_id=row["novel_id"],
                template_id=row["id"],
                version_number=row["version_number"],
                snapshot_json=snapshot,
                revision_digest=_digest(digest_input),
                revision_reason="phase0_backfill",
                created_by=None,
            )
        )


def _backfill_c0() -> None:
    bind = op.get_bind()
    json_type = sa.JSON()
    projects = sa.table("projects", sa.column("id"), sa.column("project_kind"))
    revisions = sa.table(
        "world_canon_revisions",
        sa.column("id"),
        sa.column("novel_id"),
        sa.column("version_number"),
        sa.column("parent_revision_id"),
        sa.column("manifest_json", json_type),
        sa.column("manifest_digest"),
        sa.column("receipt_json", json_type),
        sa.column("decision_id"),
        sa.column("decision_digest"),
        sa.column("created_at"),
    )
    heads = sa.table(
        "world_canon_heads",
        sa.column("novel_id"),
        sa.column("current_revision_id"),
        sa.column("updated_at"),
    )
    now = datetime.now(UTC)
    for project in bind.execute(
        sa.select(projects.c.id).where(projects.c.project_kind == "author")
    ).mappings():
        novel_id = project["id"]
        revision_id = uuid.uuid4()
        decision_id = uuid.uuid5(_BOOTSTRAP_NAMESPACE, str(novel_id))
        admission_input = {
            "kind": "bootstrap_empty",
            "version": 1,
            "novel_id": str(novel_id),
            "expected_previous_head": None,
        }
        decision_digest = _digest(admission_input)
        manifest = _empty_manifest()
        manifest_digest = _digest(manifest)
        receipt = {
            "kind": "canon_admission_receipt",
            "version": 1,
            "novel_id": str(novel_id),
            "canon_revision_id": str(revision_id),
            "manifest_digest": manifest_digest,
            "decision": {"id": str(decision_id), "digest": decision_digest},
            "authorizer": {
                "kind": "bootstrap",
                "version": 1,
                "subject": "world.canon.bootstrap",
            },
            "executor": {
                "kind": "bootstrap",
                "version": 1,
                "subject": "world.canon.bootstrap",
            },
            "authorization_policy": _BOOTSTRAP_POLICY_REF,
            "authorization_decision": "allow",
            "action": "bootstrap_empty_canon",
            "affected_families": [],
            "affected_resources": [],
            "admission_input": admission_input,
            "admission_input_digest": decision_digest,
            "expected_previous_head": None,
            "committed_at": now.isoformat().replace("+00:00", "Z"),
        }
        bind.execute(
            revisions.insert().values(
                id=revision_id,
                novel_id=novel_id,
                version_number=0,
                parent_revision_id=None,
                manifest_json=manifest,
                manifest_digest=manifest_digest,
                receipt_json=receipt,
                decision_id=decision_id,
                decision_digest=decision_digest,
                created_at=now,
            )
        )
        bind.execute(
            heads.insert().values(
                novel_id=novel_id,
                current_revision_id=revision_id,
                updated_at=now,
            )
        )


def _install_immutable_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_world_authority_immutable_write() RETURNS trigger AS $$
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
        "world_bible_page_revisions",
    ):
        op.execute(
            f"CREATE TRIGGER trg_{table}_authority_immutable "
            f"BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION reject_world_authority_immutable_write()"
        )


def upgrade() -> None:
    op.add_column(
        "world_bible_page_revisions",
        sa.Column("revision_digest", sa.String(64), nullable=True),
    )
    op.add_column(
        "entity_profile_templates",
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
    )
    _create_tables()
    _backfill_revision_digests()
    _backfill_c0()
    _install_immutable_triggers()
    op.alter_column("world_bible_page_revisions", "revision_digest", nullable=False)


def downgrade() -> None:
    for table in (
        "world_assertions",
        "world_canon_revisions",
        "entity_profile_template_revisions",
        "world_bible_page_revisions",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_authority_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_world_authority_immutable_write")
    op.drop_constraint(
        "fk_world_bible_page_revision_same_novel",
        "world_bible_page_revisions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_world_bible_page_novel_id",
        "world_bible_pages",
        type_="unique",
    )
    op.drop_table("entity_profile_template_revisions")
    op.drop_constraint(
        "uq_profile_template_novel_id",
        "entity_profile_templates",
        type_="unique",
    )
    op.drop_table("world_canon_heads")
    op.drop_constraint(
        "fk_world_canon_revision_parent_same_novel",
        "world_canon_revisions",
        type_="foreignkey",
    )
    op.drop_table("world_canon_revisions")
    op.drop_table("world_assertions")
    op.drop_column("entity_profile_templates", "version_number")
    op.drop_column("world_bible_page_revisions", "revision_digest")
