# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database itself refuses UPDATE and DELETE on ledger rows (M5 R4).

Row triggers, so TRUNCATE and DROP (the database owner's tools: test flush, pg_restore --clean)
still work; backups and exports cover those.
"""
from django.db import migrations

TABLES = ("ledger_grant", "ledger_revocation", "ledger_accessevent")

FUNCTION = """
CREATE OR REPLACE FUNCTION ledger_refuse_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ledger rows are append-only: % on % refused', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'integrity_constraint_violation';
END $$;
"""

SQL = [FUNCTION] + [
    f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
    "FOR EACH ROW EXECUTE FUNCTION ledger_refuse_change();" for t in TABLES
]
REVERSE = [f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};" for t in TABLES] + [
    "DROP FUNCTION IF EXISTS ledger_refuse_change();"
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
