"""Add V2 creative execution and immutable trial/merge receipts."""

from alembic import op

revision = "20260920_creative_engine"
down_revision = "20260920_interaction_ensemble"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_async_task_novel_identity", "async_tasks", ["novel_id", "id"]
    )
    op.execute("""CREATE TABLE collaboration_cases (
	owner_id UUID NOT NULL,
	operation_id UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	goal TEXT NOT NULL,
	goal_version INTEGER NOT NULL,
	constraints_json JSON NOT NULL,
	goal_history_json JSON NOT NULL,
	grant_json JSON NOT NULL,
	recipe_json JSON NOT NULL,
	requests_used INTEGER NOT NULL,
	status VARCHAR(24) NOT NULL,
	id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()),
	novel_id UUID NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (novel_id, id),
	UNIQUE (novel_id, operation_id),
	FOREIGN KEY(owner_id) REFERENCES accounts (id),
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
)""")
    op.execute(
        "CREATE INDEX ix_collaboration_cases_novel_id ON collaboration_cases (novel_id)"
    )
    op.execute(
        "CREATE TABLE collaboration_runs (\n\tcase_id UUID NOT NULL,\n"
        "\toperation_id UUID NOT NULL,\n\ttask_id UUID,\n\trequest_hash "
        "VARCHAR(64) NOT NULL,\n\trequest_json JSON NOT NULL,\n\tmanife"
        "st_json JSON NOT NULL,\n\tllm_snapshot_json JSON NOT NULL,\n\t"
        "budget_json JSON NOT NULL,\n\tresult_json JSON NOT NULL,\n\tpl"
        "an_revision INTEGER NOT NULL,\n\tgeneration INTEGER NOT NULL"
        ",\n\tstatus VARCHAR(24) NOT NULL,\n\terror_code VARCHAR(100),\n"
        "\tid UUID NOT NULL,\n\tcreated_at TIMESTAMP WITH TIME ZONE DE"
        "FAULT timezone('utc', now()) NOT NULL,\n\tupdated_at TIMESTA"
        "MP WITH TIME ZONE DEFAULT timezone('utc', now()),\n\tnovel_i"
        "d UUID NOT NULL,\n\tPRIMARY KEY (id),\n\tUNIQUE (novel_id, id)"
        ",\n\tUNIQUE (novel_id, operation_id),\n\tFOREIGN KEY(novel_id,"
        " case_id) REFERENCES collaboration_cases (novel_id, id) ON"
        " DELETE CASCADE,\n\tFOREIGN KEY(novel_id, task_id) REFERENCE"
        "S async_tasks (novel_id, id),\n\tCHECK (status IN ('pending'"
        ",'running','completed','partial','failed','cancelled','bud"
        "get_exceeded')),\n\tFOREIGN KEY(novel_id) REFERENCES project"
        "s (id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_collaboration_runs_novel_id ON collaboration_runs (novel_id)"
    )
    op.execute(
        "CREATE TABLE creative_workspaces (\n\tcase_id UUID NOT NULL,"
        "\n\toperation_id UUID NOT NULL,\n\tparent_id UUID,\n\tlabel VARC"
        "HAR(200) NOT NULL,\n\tbaseline_json JSON NOT NULL,\n\tcurrent_"
        "revision_id UUID,\n\tstatus VARCHAR(24) NOT NULL,\n\tid UUID N"
        "OT NULL,\n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT time"
        "zone('utc', now()) NOT NULL,\n\tupdated_at TIMESTAMP WITH TI"
        "ME ZONE DEFAULT timezone('utc', now()),\n\tnovel_id UUID NOT"
        " NULL,\n\tPRIMARY KEY (id),\n\tUNIQUE (novel_id, id),\n\tUNIQUE "
        "(novel_id, operation_id),\n\tFOREIGN KEY(novel_id, case_id) "
        "REFERENCES collaboration_cases (novel_id, id) ON DELETE CA"
        "SCADE,\n\tFOREIGN KEY(novel_id, parent_id) REFERENCES creati"
        "ve_workspaces (novel_id, id),\n\tFOREIGN KEY(novel_id) REFER"
        "ENCES projects (id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_creative_workspaces_novel_id ON creative_workspaces (novel_id)"
    )
    op.execute(
        "CREATE TABLE creative_workspace_revisions (\n\tworkspace_id "
        "UUID NOT NULL,\n\tparent_revision_id UUID,\n\tsequence INTEGER"
        " NOT NULL,\n\tgoal_version INTEGER NOT NULL,\n\tpatches_json J"
        "SON NOT NULL,\n\tmanifest_json JSON NOT NULL,\n\tdigest VARCHA"
        "R(64) NOT NULL,\n\tid UUID NOT NULL,\n\tcreated_at TIMESTAMP W"
        "ITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL,\n\tup"
        "dated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', "
        "now()),\n\tnovel_id UUID NOT NULL,\n\tPRIMARY KEY (id),\n\tUNIQU"
        "E (novel_id, id),\n\tUNIQUE (workspace_id, sequence),\n\tFOREI"
        "GN KEY(novel_id, workspace_id) REFERENCES creative_workspa"
        "ces (novel_id, id) ON DELETE CASCADE,\n\tFOREIGN KEY(novel_i"
        "d, parent_revision_id) REFERENCES creative_workspace_revis"
        "ions (novel_id, id),\n\tFOREIGN KEY(novel_id) REFERENCES pro"
        "jects (id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_creative_workspace_revisions_novel_id ON c"
        "reative_workspace_revisions (novel_id)"
    )
    op.execute(
        "CREATE TABLE collaboration_artifacts (\n\trun_id UUID NOT NU"
        "LL,\n\tworkspace_revision_id UUID,\n\tkind VARCHAR(32) NOT NUL"
        "L,\n\tmanifest_json JSON NOT NULL,\n\tpayload_json JSON NOT NU"
        "LL,\n\toutput_hash VARCHAR(64) NOT NULL,\n\tid UUID NOT NULL,\n"
        "\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc"
        "', now()) NOT NULL,\n\tupdated_at TIMESTAMP WITH TIME ZONE D"
        "EFAULT timezone('utc', now()),\n\tnovel_id UUID NOT NULL,\n\tP"
        "RIMARY KEY (id),\n\tUNIQUE (novel_id, id),\n\tFOREIGN KEY(nove"
        "l_id, run_id) REFERENCES collaboration_runs (novel_id, id)"
        " ON DELETE CASCADE,\n\tFOREIGN KEY(novel_id, workspace_revis"
        "ion_id) REFERENCES creative_workspace_revisions (novel_id,"
        " id),\n\tFOREIGN KEY(novel_id) REFERENCES projects (id) ON D"
        "ELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_collaboration_artifacts_novel_id ON collab"
        "oration_artifacts (novel_id)"
    )
    op.execute(
        "CREATE TABLE collaboration_work_items (\n\trun_id UUID NOT N"
        "ULL,\n\tlogical_key VARCHAR(64) NOT NULL,\n\tgeneration INTEGE"
        "R NOT NULL,\n\tproposal_json JSON NOT NULL,\n\tinput_hash VARC"
        "HAR(64) NOT NULL,\n\tstatus VARCHAR(24) NOT NULL,\n\tattempt I"
        "NTEGER NOT NULL,\n\toutput_id UUID,\n\terror_code VARCHAR(100)"
        ",\n\tid UUID NOT NULL,\n\tcreated_at TIMESTAMP WITH TIME ZONE "
        "DEFAULT timezone('utc', now()) NOT NULL,\n\tupdated_at TIMES"
        "TAMP WITH TIME ZONE DEFAULT timezone('utc', now()),\n\tnovel"
        "_id UUID NOT NULL,\n\tPRIMARY KEY (id),\n\tUNIQUE (novel_id, i"
        "d),\n\tUNIQUE (run_id, logical_key, generation),\n\tFOREIGN KE"
        "Y(novel_id, run_id) REFERENCES collaboration_runs (novel_i"
        "d, id) ON DELETE CASCADE,\n\tFOREIGN KEY(novel_id, output_id"
        ") REFERENCES collaboration_artifacts (novel_id, id),\n\tCHEC"
        "K (status IN ('pending','running','succeeded','failed','bl"
        "ocked','cancelled','superseded')),\n\tFOREIGN KEY(novel_id) "
        "REFERENCES projects (id) ON DELETE CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_collaboration_work_items_novel_id ON colla"
        "boration_work_items (novel_id)"
    )
    op.execute(
        "CREATE TABLE creative_merge_receipts (\n\trevision_id UUID N"
        "OT NULL,\n\toperation_id UUID NOT NULL,\n\trequest_hash VARCHA"
        "R(64) NOT NULL,\n\tdigest VARCHAR(64) NOT NULL,\n\tauthorizer_"
        'id UUID NOT NULL,\n\t"authorization" VARCHAR(32) NOT NULL,\n\t'
        "results_json JSON NOT NULL,\n\tid UUID NOT NULL,\n\tcreated_at"
        " TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) N"
        "OT NULL,\n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT time"
        "zone('utc', now()),\n\tnovel_id UUID NOT NULL,\n\tPRIMARY KEY "
        "(id),\n\tUNIQUE (novel_id, id),\n\tUNIQUE (novel_id, operation"
        "_id),\n\tUNIQUE (revision_id),\n\tFOREIGN KEY(novel_id, revisi"
        "on_id) REFERENCES creative_workspace_revisions (novel_id, "
        "id),\n\tFOREIGN KEY(authorizer_id) REFERENCES accounts (id),"
        "\n\tFOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE"
        " CASCADE\n)"
    )
    op.execute(
        "CREATE INDEX ix_creative_merge_receipts_novel_id ON creati"
        "ve_merge_receipts (novel_id)"
    )
    op.execute(
        "CREATE TABLE domain_outbox (\n\treceipt_id UUID NOT NULL,\n\tp"
        "ayload_json JSON NOT NULL,\n\tstatus VARCHAR(16) NOT NULL,\n\t"
        "id UUID NOT NULL,\n\tcreated_at TIMESTAMP WITH TIME ZONE DEF"
        "AULT timezone('utc', now()) NOT NULL,\n\tupdated_at TIMESTAM"
        "P WITH TIME ZONE DEFAULT timezone('utc', now()),\n\tnovel_id"
        " UUID NOT NULL,\n\tPRIMARY KEY (id),\n\tUNIQUE (receipt_id),\n\t"
        "FOREIGN KEY(novel_id, receipt_id) REFERENCES creative_merg"
        "e_receipts (novel_id, id) ON DELETE CASCADE,\n\tFOREIGN KEY("
        "novel_id) REFERENCES projects (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_domain_outbox_novel_id ON domain_outbox (novel_id)")
    op.execute(
        "ALTER TABLE creative_workspaces ADD CONSTRAINT fk_creative"
        "_workspace_current FOREIGN KEY(novel_id, current_revision_"
        "id) REFERENCES creative_workspace_revisions (novel_id, id)"
        " DEFERRABLE INITIALLY DEFERRED"
    )
    op.execute("""CREATE FUNCTION reject_creative_history_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'creative revisions, artifacts and receipts are immutable';
        END $$""")
    op.execute(
        "CREATE TRIGGER creative_workspace_revisions_immutable BEFO"
        "RE UPDATE OR DELETE ON creative_workspace_revisions FOR EA"
        "CH ROW EXECUTE FUNCTION reject_creative_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER collaboration_artifacts_immutable BEFORE UP"
        "DATE OR DELETE ON collaboration_artifacts FOR EACH ROW EXE"
        "CUTE FUNCTION reject_creative_history_mutation()"
    )
    op.execute(
        "CREATE TRIGGER creative_merge_receipts_immutable BEFORE UP"
        "DATE OR DELETE ON creative_merge_receipts FOR EACH ROW EXE"
        "CUTE FUNCTION reject_creative_history_mutation()"
    )


def downgrade():
    op.drop_constraint(
        "fk_creative_workspace_current", "creative_workspaces", type_="foreignkey"
    )
    op.drop_table("domain_outbox")
    op.drop_table("creative_merge_receipts")
    op.drop_table("collaboration_work_items")
    op.drop_table("collaboration_artifacts")
    op.drop_table("creative_workspace_revisions")
    op.drop_table("creative_workspaces")
    op.drop_table("collaboration_runs")
    op.drop_table("collaboration_cases")
    op.execute("DROP FUNCTION reject_creative_history_mutation()")
    op.drop_constraint("uq_async_task_novel_identity", "async_tasks", type_="unique")
