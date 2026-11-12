# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database refuses UPDATE and DELETE on every record table and on Supersession (M6 R1).

Same shape as ledger/0002. Row triggers: TRUNCATE and DROP (the database owner's tools, used by the
test flush and by `pg_restore --clean`) still work. There is no supported bypass for normal use.
"""
from django.db import migrations

TABLES = ("core_dailysnapshot", "core_probesession", "core_workblock", "core_discomfortcheck", "core_reset",
          "core_weeklycheck", "core_trainingsession", "core_trainingset", "core_supersession")

FUNCTION = """
CREATE OR REPLACE FUNCTION core_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'records are append-only: % on % refused (a correction is a new record)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'integrity_constraint_violation';
END $$;
"""

SQL = [FUNCTION] + [
    f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
    "FOR EACH ROW EXECUTE FUNCTION core_refuse_change();" for t in TABLES
]
REVERSE = [f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in TABLES] + [
    "DROP FUNCTION IF EXISTS core_refuse_change();"
]


class Migration(migrations.Migration):
    dependencies = [("core", "0015_training_log")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
