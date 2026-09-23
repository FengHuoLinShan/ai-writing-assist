"""Durable author understanding, independent of short-lived collaboration runs."""

from alembic import op

revision = "20260922_cognition"
down_revision = "20260922_evolution_invalidation"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE TABLE cognition_commits (\n\toperation_id UUID NOT NULL, \n\tpa"
        "rent_id UUID, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tscope VARCHAR"
        "(32) NOT NULL, \n\toutcome VARCHAR(24) NOT NULL, \n\tmethod_version VA"
        "RCHAR(64) NOT NULL, \n\tread_set_json JSON NOT NULL, \n\tchanges_json "
        "JSON NOT NULL, \n\tprovenance_json JSON NOT NULL, \n\tid UUID NOT NULL"
        ", \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', no"
        "w()) NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT timez"
        "one('utc', now()), \n\tnovel_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n"
        "\tUNIQUE (novel_id, id), \n\tUNIQUE (novel_id, operation_id), \n\tFOREI"
        "GN KEY(novel_id, parent_id) REFERENCES cognition_commits (novel_id"
        ", id), \n\tFOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE "
        "CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_cognition_commits_novel_id ON cognition_commits (novel_id)"
    )
    op.execute(
        "CREATE TABLE cognition_heads (\n\tscope VARCHAR(32) NOT NULL, \n\tcomm"
        "it_id UUID, \n\tgeneration INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tc"
        "reated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) "
        "NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('"
        "utc', now()), \n\tnovel_id UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQ"
        "UE (novel_id, scope), \n\tFOREIGN KEY(novel_id, commit_id) REFERENCE"
        "S cognition_commits (novel_id, id), \n\tFOREIGN KEY(novel_id) REFERE"
        "NCES projects (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_cognition_heads_novel_id ON cognition_heads (novel_id)")
    op.execute(
        "CREATE TABLE cognition_records (\n\trecord_id UUID NOT NULL, \n\tcommi"
        "t_id UUID NOT NULL, \n\tscope VARCHAR(32) NOT NULL, \n\tis_current BOO"
        "LEAN NOT NULL, \n\tcontent_json JSON NOT NULL, \n\tdependencies_json J"
        "SON NOT NULL, \n\tcognition_refs_json JSON NOT NULL, \n\tquery_depende"
        "ncies_json JSON NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\ta"
        "uthor_status VARCHAR(24) NOT NULL, \n\tlearned_at_chapter INTEGER, \n"
        "\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT t"
        "imezone('utc', now()) NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME Z"
        "ONE DEFAULT timezone('utc', now()), \n\tnovel_id UUID NOT NULL, \n\tPR"
        "IMARY KEY (id), \n\tUNIQUE (novel_id, id), \n\tFOREIGN KEY(novel_id, c"
        "ommit_id) REFERENCES cognition_commits (novel_id, id) ON DELETE CA"
        "SCADE, \n\tFOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE "
        "CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_cognition_records_novel_id ON cognition_records (novel_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_cognition_current_record ON cognition_recor"
        "ds (novel_id, record_id) WHERE is_current"
    )


def downgrade():
    op.drop_table("cognition_records")
    op.drop_table("cognition_heads")
    op.drop_table("cognition_commits")
