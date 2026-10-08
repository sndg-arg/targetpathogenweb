from django.db import migrations, models

# Drop whatever actually enforces uniqueness on session_key -- a plain
# AlterField(unique=False) makes Django guess the constraint's name
# (<table>_<column>_key, the Postgres default for an inline UNIQUE column
# constraint), but on this DB that guess doesn't match what's really there
# (observed error: "constraint tpweb_agentchatsession_session_key_key does
# not exist" when running this migrate on the cluster). session_key also has
# db_index=True, and depending on Django/Postgres version the "unique"
# enforcement can end up as a unique INDEX instead of a table CONSTRAINT with
# a differently-generated name. This looks up and drops either shape by
# introspecting pg_constraint/pg_indexes for session_key specifically,
# instead of assuming a name.
_DROP_SESSION_KEY_UNIQUENESS_SQL = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ANY(con.conkey)
        WHERE rel.relname = 'tpweb_agentchatsession'
          AND con.contype = 'u'
          AND att.attname = 'session_key'
          AND array_length(con.conkey, 1) = 1
    LOOP
        EXECUTE format('ALTER TABLE tpweb_agentchatsession DROP CONSTRAINT %I', r.conname);
    END LOOP;

    FOR r IN
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'tpweb_agentchatsession'
          AND indexdef ILIKE '%UNIQUE%'
          AND indexdef ILIKE '%(session_key)%'
    LOOP
        EXECUTE format('DROP INDEX IF EXISTS %I', r.indexname);
    END LOOP;
END $$;
"""

_RECREATE_SESSION_KEY_UNIQUE_CONSTRAINT_SQL = """
ALTER TABLE tpweb_agentchatsession
    ADD CONSTRAINT tpweb_agentchatsession_session_key_key UNIQUE (session_key);
"""


class Migration(migrations.Migration):

    dependencies = [
        ("tpweb", "0071_agentchatsession"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="agentchatsession",
                    name="session_key",
                    field=models.CharField(max_length=40, db_index=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=_DROP_SESSION_KEY_UNIQUENESS_SQL,
                    reverse_sql=_RECREATE_SESSION_KEY_UNIQUE_CONSTRAINT_SQL,
                ),
            ],
        ),
        migrations.AddField(
            model_name="agentchatsession",
            name="title",
            field=models.CharField(max_length=140, blank=True, default=""),
        ),
        migrations.AddIndex(
            model_name="agentchatsession",
            index=models.Index(fields=["session_key", "-updated_at"], name="tpweb_agent_sesskey_upd_idx"),
        ),
    ]
