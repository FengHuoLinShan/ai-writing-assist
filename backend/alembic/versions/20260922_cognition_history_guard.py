"""Protect understanding receipts and revisions, allowing only pointer retirement."""

from alembic import op

revision = "20260922_cognition_history_guard"
down_revision = "20260922_cognition"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TRIGGER cognition_commits_immutable
        BEFORE UPDATE OR DELETE ON cognition_commits FOR EACH ROW
        EXECUTE FUNCTION reject_creative_history_mutation()""")
    op.execute("""CREATE FUNCTION reject_cognition_revision_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        IF TG_OP = 'UPDATE' AND OLD.is_current AND NOT NEW.is_current
            AND (to_jsonb(OLD) - 'is_current' - 'updated_at') =
                (to_jsonb(NEW) - 'is_current' - 'updated_at') THEN RETURN NEW; END IF;
        RAISE EXCEPTION 'understanding revisions are immutable';
        END $$""")
    op.execute("""CREATE TRIGGER cognition_records_immutable
        BEFORE UPDATE OR DELETE ON cognition_records FOR EACH ROW
        EXECUTE FUNCTION reject_cognition_revision_mutation()""")


def downgrade():
    op.execute("DROP TRIGGER cognition_records_immutable ON cognition_records")
    op.execute("DROP FUNCTION reject_cognition_revision_mutation()")
    op.execute("DROP TRIGGER cognition_commits_immutable ON cognition_commits")
