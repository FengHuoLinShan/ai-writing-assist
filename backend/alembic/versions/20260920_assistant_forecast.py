"""Add immutable forecast assessments and compatible notice/run fields."""

import sqlalchemy as sa

from alembic import op

revision = "20260920_assistant_forecast"
down_revision = "20260920_creative_engine"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assistant_runs", sa.Column("operation_id", sa.Uuid(), nullable=True))
    op.add_column(
        "assistant_notices",
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_assistant_run_operation",
        "assistant_runs",
        ["novel_id", "operation_id"],
        unique=True,
        postgresql_where=sa.text("operation_id IS NOT NULL"),
    )
    op.execute(
        "CREATE TABLE assistant_forecast_candidates (\n\trun_id UUID "
        "NOT NULL,\n\tordinal INTEGER NOT NULL,\n\tissue_key VARCHAR(16"
        "0) NOT NULL,\n\taudience_key VARCHAR(160) NOT NULL,\n\tscope_h"
        "ash VARCHAR(64) NOT NULL,\n\tcontext_hash VARCHAR(64) NOT NU"
        "LL,\n\tassessment_hash VARCHAR(64) NOT NULL,\n\tcapability_id "
        "VARCHAR(100) NOT NULL,\n\tprotocol_version VARCHAR(32) NOT N"
        "ULL,\n\toutput_kind VARCHAR(32) NOT NULL,\n\ttier VARCHAR(16) "
        "NOT NULL,\n\tpolicy_generation INTEGER NOT NULL,\n\tvalidation"
        "_state VARCHAR(16) NOT NULL,\n\tpayload_json JSON NOT NULL,\n"
        "\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL,\n\tid UUID NO"
        "T NULL,\n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT timez"
        "one('utc', now()) NOT NULL,\n\tupdated_at TIMESTAMP WITH TIM"
        "E ZONE DEFAULT timezone('utc', now()),\n\tnovel_id UUID NOT "
        "NULL,\n\tPRIMARY KEY (id),\n\tUNIQUE (novel_id, id),\n\tUNIQUE ("
        "novel_id, run_id, ordinal),\n\tFOREIGN KEY(novel_id, run_id)"
        " REFERENCES assistant_runs (novel_id, id) ON DELETE CASCAD"
        "E,\n\tCHECK (ordinal >= 0 AND ordinal < 64),\n\tCHECK (validat"
        "ion_state IN ('valid','stale','revoked','expired')),\n\tFORE"
        "IGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCA"
        "DE\n)"
    )
    op.execute(
        "CREATE INDEX ix_assistant_forecast_candidates_novel_id ON "
        "assistant_forecast_candidates (novel_id)"
    )
    op.execute(
        "CREATE INDEX ix_forecast_expiry ON assistant_forecast_cand"
        "idates (novel_id, validation_state, expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_forecast_issue_latest ON assistant_forecas"
        "t_candidates (novel_id, audience_key, scope_hash, issue_ke"
        "y, created_at)"
    )
    op.execute(
        "CREATE TABLE assistant_forecast_dependencies (\n\tcandidate_"
        "id UUID NOT NULL,\n\tdependency_key VARCHAR(200) NOT NULL,\n\t"
        "novel_id UUID NOT NULL,\n\tresource_kind VARCHAR(64) NOT NUL"
        "L,\n\tresource_id UUID NOT NULL,\n\trevision_token VARCHAR(200"
        ") NOT NULL,\n\trole VARCHAR(32) NOT NULL,\n\trequired BOOLEAN "
        "NOT NULL,\n\tscope_stamp VARCHAR(64) NOT NULL,\n\tPRIMARY KEY "
        "(candidate_id, dependency_key),\n\tFOREIGN KEY(novel_id, can"
        "didate_id) REFERENCES assistant_forecast_candidates (novel"
        "_id, id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_forecast_dependency_source ON assistant_fo"
        "recast_dependencies (novel_id, resource_kind, resource_id)"
    )
    op.execute("""CREATE FUNCTION guard_forecast_assessment() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        IF TG_OP = 'DELETE' OR
           (to_jsonb(NEW) - ARRAY['validation_state','updated_at']) <>
           (to_jsonb(OLD) - ARRAY['validation_state','updated_at']) THEN
            RAISE EXCEPTION 'forecast assessments are immutable';
        END IF; RETURN NEW; END $$""")
    op.execute("""CREATE TRIGGER forecast_assessment_immutable
        BEFORE UPDATE OR DELETE ON assistant_forecast_candidates
        FOR EACH ROW EXECUTE FUNCTION guard_forecast_assessment()""")
    op.execute("""ALTER TABLE assistant_forecast_candidates
        ADD CONSTRAINT ck_forecast_payload_size
        CHECK (octet_length(payload_json::text) <= 65536)""")
    op.execute("""CREATE FUNCTION bump_assistant_notice_version() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        NEW.row_version := OLD.row_version + 1; RETURN NEW; END $$""")
    op.execute("""CREATE TRIGGER assistant_notice_version
        BEFORE UPDATE ON assistant_notices
        FOR EACH ROW EXECUTE FUNCTION bump_assistant_notice_version()""")


def downgrade():
    op.execute("DROP TRIGGER assistant_notice_version ON assistant_notices")
    op.execute("DROP FUNCTION bump_assistant_notice_version()")
    op.drop_table("assistant_forecast_dependencies")
    op.drop_table("assistant_forecast_candidates")
    op.execute("DROP FUNCTION guard_forecast_assessment()")
    op.drop_index("uq_assistant_run_operation", table_name="assistant_runs")
    op.drop_column("assistant_runs", "operation_id")
    op.drop_column("assistant_notices", "row_version")
