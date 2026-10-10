"""Guard ledger prefix proofs across sessions, writes and historical restores."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261010_evolution_source_epoch"
down_revision = "20261008_evolution_ledger"
branch_labels = None
depends_on = None

SOURCE_TABLES = (
    "writing_drafts",
    "scenes",
    "scene_spans",
    "scene_chapter_links",
    "evolution_runs",
    "evolution_frozen_attempts",
    "evolution_receipts",
)


def upgrade():
    op.create_table(
        "evolution_source_epochs",
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("scope_key", sa.String(300), primary_key=True),
        sa.Column("epoch", UUID(as_uuid=True), nullable=False),
    )
    op.execute("""
        INSERT INTO evolution_source_epochs(novel_id, scope_key, epoch)
        SELECT DISTINCT novel_id, scope_key, gen_random_uuid() FROM (
            SELECT id AS novel_id, 'project' AS scope_key FROM projects
            UNION SELECT novel_id, 'chapter:' || chapter_index FROM writing_drafts
            UNION SELECT novel_id, 'scene:' || id FROM scenes
            UNION SELECT novel_id, 'scene:' || scene_id FROM scene_spans
            UNION SELECT novel_id, 'scene:' || scene_id FROM scene_chapter_links
            UNION SELECT novel_id, 'run:' || run_key FROM evolution_runs
            UNION SELECT novel_id, 'attempt:' || char_length(run_key) || ':' || run_key
                || ':' || attempt_key FROM evolution_frozen_attempts
            UNION SELECT novel_id, 'attempt:' || char_length(run_key) || ':' || run_key
                || ':' || attempt_key FROM evolution_receipts
        ) AS scopes
    """)
    op.execute("""
        CREATE FUNCTION evolution_bump_source_epoch() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE row_data jsonb; keys text[]; key text; nid uuid; scene_id text;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                DELETE FROM evolution_source_epochs;
                RETURN NULL;
            END IF;
            -- Budget/checkpoint progress does not change an old run's prefix.
            IF TG_TABLE_NAME = 'evolution_runs' AND TG_OP = 'UPDATE' THEN
                IF NEW.novel_id = OLD.novel_id AND NEW.run_key = OLD.run_key AND
                    NEW.execution_mode = OLD.execution_mode AND
                    (NEW.reading_plan_json::jsonb -> 'inherited_receipts') IS NOT DISTINCT
                    FROM (OLD.reading_plan_json::jsonb -> 'inherited_receipts') THEN
                    RETURN NULL;
                END IF;
            END IF;
            FOR row_data IN SELECT value FROM jsonb_array_elements(
                jsonb_build_array(CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
                                  CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END))
                WHERE value <> 'null'::jsonb
            LOOP
                nid := (row_data->>'novel_id')::uuid;
                keys := ARRAY['project'];
                IF TG_TABLE_NAME = 'writing_drafts' THEN
                    keys := keys || ('chapter:' || (row_data->>'chapter_index'));
                ELSIF TG_TABLE_NAME = 'scenes' THEN
                    keys := keys || ('scene:' || (row_data->>'id'));
                ELSIF TG_TABLE_NAME IN ('scene_spans', 'scene_chapter_links') THEN
                    keys := keys || ('scene:' || (row_data->>'scene_id'));
                ELSIF TG_TABLE_NAME = 'evolution_runs' THEN
                    keys := keys || ('run:' || (row_data->>'run_key'));
                    -- Live/shadow transitions of another run can change the
                    -- latest successful attempt for a Scene in an old proof.
                    FOR scene_id IN SELECT DISTINCT payload_json->>'scene_id'
                        FROM evolution_frozen_attempts WHERE novel_id = nid AND
                        run_key = row_data->>'run_key'
                    LOOP
                        IF scene_id IS NOT NULL THEN
                            keys := keys || ('scene:' || scene_id);
                        END IF;
                    END LOOP;
                ELSE
                    keys := keys || ('attempt:' || char_length(row_data->>'run_key')
                        || ':' || (row_data->>'run_key') || ':' ||
                        (row_data->>'attempt_key'));
                    IF TG_TABLE_NAME = 'evolution_frozen_attempts' THEN
                        scene_id := row_data->'payload_json'->>'scene_id';
                    ELSE
                        SELECT payload_json->>'scene_id' INTO scene_id FROM
                        evolution_frozen_attempts WHERE novel_id = nid AND
                        run_key = row_data->>'run_key' AND
                        attempt_key = row_data->>'attempt_key';
                    END IF;
                    IF scene_id IS NOT NULL THEN keys := keys || ('scene:' || scene_id);
                    END IF;
                END IF;
                FOREACH key IN ARRAY keys LOOP
                    INSERT INTO evolution_source_epochs(novel_id, scope_key, epoch)
                    SELECT id, key, gen_random_uuid() FROM projects WHERE id = nid
                    ON CONFLICT (novel_id, scope_key)
                    DO UPDATE SET epoch = EXCLUDED.epoch;
                END LOOP;
            END LOOP;
            RETURN NULL;
        END $$
    """)
    for table in SOURCE_TABLES:
        op.execute(
            f"CREATE TRIGGER evolution_source_epoch_write AFTER INSERT OR "
            f"UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION "
            "evolution_bump_source_epoch()"
        )
        op.execute(
            f"CREATE TRIGGER evolution_source_epoch_truncate AFTER TRUNCATE "
            f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION "
            "evolution_bump_source_epoch()"
        )


def downgrade():
    for table in SOURCE_TABLES:
        op.execute(f"DROP TRIGGER evolution_source_epoch_write ON {table}")
        op.execute(f"DROP TRIGGER evolution_source_epoch_truncate ON {table}")
    op.execute("DROP FUNCTION evolution_bump_source_epoch()")
    op.drop_table("evolution_source_epochs")
