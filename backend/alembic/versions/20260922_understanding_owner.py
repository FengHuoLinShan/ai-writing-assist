"""Fence legacy and evolution writers at the shared project and task boundaries."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_understanding_owner"
down_revision = "20260922_cognition_history_guard"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "projects",
        sa.Column(
            "understanding_engine", sa.String(16), nullable=False, server_default="legacy"
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "understanding_epoch", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "understanding_schema_floor", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "evolution_runs",
        sa.Column(
            "project_owner_epoch", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    # Existing live evolution history cannot be silently assigned to legacy.
    # Preserve all runs, checkpoints and fees; explicit forward activation is required.
    op.execute("""UPDATE projects p SET understanding_engine='read_only',
        understanding_epoch=2, understanding_schema_floor=2
        WHERE EXISTS (SELECT 1 FROM evolution_runs r WHERE r.novel_id=p.id AND
        r.execution_mode='live')""")
    # Fence queued work before adding guards, so an incompatible earliest task
    # cannot repeatedly fail claim and starve unrelated projects.
    op.execute("""UPDATE async_tasks SET status='cancelled', lease_id=NULL,
        finished_at=now(), transition_reason='understanding_protocol_upgrade'
        WHERE status IN ('pending','running') AND
        (task_type='evolution_scene_step' OR
        (novel_id IN (SELECT id FROM projects WHERE understanding_engine='read_only') AND
        task_type IN ('deep_import','scene_auto_extraction',
        'world_object_auto_extraction',
            'plot_structure_auto_extraction','targeted_completion',
            'import_review_resolution')))""")
    op.execute("""UPDATE import_workflow_runs SET status='cancelled',
    recovery_required=false,
        generation=generation+1, owner_task_id=NULL, owner_attempt=NULL,
        owner_lease_id=NULL
        WHERE novel_id IN (SELECT id FROM projects WHERE understanding_engine='read_only')
        AND (status IN ('pending','running') OR recovery_required)""")
    op.execute("""UPDATE evolution_runs SET status='stopped', owner_epoch=owner_epoch+1
        WHERE execution_mode='live' AND status='active'""")
    op.execute("""CREATE FUNCTION guard_understanding_project() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.understanding_engine NOT IN ('legacy','evolution','read_only')
           OR NEW.understanding_epoch < OLD.understanding_epoch
           OR NEW.understanding_schema_floor < OLD.understanding_schema_floor
           OR (NEW.understanding_engine <> OLD.understanding_engine AND
           NEW.understanding_epoch <= OLD.understanding_epoch)
           OR (NEW.understanding_engine='legacy' AND NEW.understanding_schema_floor>1)
           OR (NEW.understanding_engine='evolution' AND
           NEW.understanding_schema_floor<2) THEN
            RAISE EXCEPTION 'incompatible understanding engine transition';
        END IF;
        RETURN NEW; END $$""")
    op.execute("""CREATE TRIGGER understanding_project_guard BEFORE UPDATE ON projects
        FOR EACH ROW EXECUTE FUNCTION guard_understanding_project()""")
    # Old heartbeat/claim SQL locks the child first. NOWAIT fails closed instead
    # of deadlocking with a switch holding project -> child locks. The queue's
    # heartbeat/poll loop retries; current domain commits lock project first.
    op.execute("""CREATE FUNCTION guard_understanding_writer() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE nid uuid; writer text; token jsonb; current_engine text;
        current_epoch integer;
                floor integer; token_epoch integer; token_schema integer;
        BEGIN
        nid := NEW.novel_id;
        IF TG_TABLE_NAME='async_tasks' THEN
            IF TG_OP='UPDATE' AND OLD.task_type IS DISTINCT FROM NEW.task_type AND
                (OLD.task_type IN ('deep_import','scene_auto_extraction',
                'world_object_auto_extraction',
                    'plot_structure_auto_extraction','targeted_completion',
                    'import_review_resolution',
                    'evolution_scene_step','evolution_scene_step_v2')
                OR NEW.task_type IN ('deep_import','scene_auto_extraction',
                'world_object_auto_extraction',
                    'plot_structure_auto_extraction','targeted_completion',
                    'import_review_resolution',
                    'evolution_scene_step','evolution_scene_step_v2')) THEN
                RAISE EXCEPTION 'understanding task protocol is immutable';
            END IF;
            IF NEW.task_type IN ('deep_import','scene_auto_extraction',
            'world_object_auto_extraction',
                'plot_structure_auto_extraction','targeted_completion',
                'import_review_resolution') THEN writer := 'legacy';
            ELSIF NEW.task_type IN ('evolution_scene_step','evolution_scene_step_v2')
            THEN writer := 'evolution';
            ELSE RETURN NEW; END IF;
            IF NEW.status NOT IN ('pending','running','done') THEN RETURN NEW; END IF;
            IF TG_OP='UPDATE' THEN
                IF (OLD.meta::jsonb -> '_understanding_owner') IS DISTINCT FROM
                (NEW.meta::jsonb -> '_understanding_owner')
                    OR (OLD.meta::jsonb -> 'execution_mode') IS DISTINCT FROM
                    (NEW.meta::jsonb -> 'execution_mode') THEN
                    RAISE EXCEPTION 'understanding task owner is immutable';
                END IF;
            END IF;
            IF NEW.task_type='evolution_scene_step' THEN
                RAISE EXCEPTION 'understanding task requires v2 protocol';
            END IF;
            IF writer='evolution' AND NEW.meta->>'execution_mode'='shadow' THEN
            RETURN NEW; END IF;
            token := NEW.meta::jsonb -> '_understanding_owner';
        ELSIF TG_TABLE_NAME='import_workflow_runs' THEN
            IF NEW.status NOT IN ('pending','running') AND NOT NEW.recovery_required
            THEN RETURN NEW; END IF;
            writer := 'legacy'; token := NEW.prepare_checkpoint::jsonb ->
            '_understanding_owner';
            IF TG_OP='UPDATE' AND (OLD.prepare_checkpoint::jsonb ->
            '_understanding_owner') IS DISTINCT FROM token THEN
                RAISE EXCEPTION 'understanding run owner is immutable';
            END IF;
        ELSE
            IF NEW.execution_mode='shadow' OR NEW.status <> 'active' THEN RETURN NEW;
            END IF;
            writer := 'evolution';
            token := jsonb_build_object('engine', writer, 'epoch',
            NEW.project_owner_epoch, 'schema', 2);
            IF TG_OP='UPDATE' AND OLD.project_owner_epoch <> NEW.project_owner_epoch THEN
                RAISE EXCEPTION 'understanding run owner is immutable';
            END IF;
        END IF;
        SELECT understanding_engine, understanding_epoch, understanding_schema_floor
            INTO current_engine, current_epoch, floor FROM projects WHERE id=nid FOR
            SHARE NOWAIT;
        IF NOT FOUND THEN RAISE EXCEPTION 'understanding project missing'; END IF;
        IF token IS NULL OR token='null'::jsonb THEN
            IF writer='legacy' AND current_engine='legacy' AND current_epoch=1 AND
            floor=1 THEN RETURN NEW; END IF;
            RAISE EXCEPTION 'understanding writer missing frozen owner';
        END IF;
        token_epoch := (token->>'epoch')::integer;
        token_schema := (token->>'schema')::integer;
        IF current_engine IS DISTINCT FROM writer OR token->>'engine' IS DISTINCT
        FROM writer
            OR token_epoch IS DISTINCT FROM current_epoch OR token_schema IS NULL OR
            token_schema<floor
            OR (writer='legacy' AND token_schema<>1) OR (writer='evolution' AND
            token_schema<>2) THEN
            RAISE EXCEPTION 'understanding writer fenced';
        END IF;
        RETURN NEW; END $$""")
    for table in ("async_tasks", "import_workflow_runs", "evolution_runs"):
        op.execute(
            "CREATE TRIGGER understanding_writer_guard BEFORE INSERT OR UPDATE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION guard_understanding_writer()"
        )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM projects WHERE
    understanding_schema_floor>1) THEN
        RAISE EXCEPTION
        'new understanding history requires forward repair; downgrade refused'; END
        IF; END $$""")
    for table in ("async_tasks", "import_workflow_runs", "evolution_runs"):
        op.execute(f"DROP TRIGGER understanding_writer_guard ON {table}")
    op.execute("DROP FUNCTION guard_understanding_writer()")
    op.execute("DROP TRIGGER understanding_project_guard ON projects")
    op.execute("DROP FUNCTION guard_understanding_project()")
    op.drop_column("evolution_runs", "project_owner_epoch")
    for name in (
        "understanding_schema_floor",
        "understanding_epoch",
        "understanding_engine",
    ):
        op.drop_column("projects", name)
