# Stamp Row-Level Security (RLS) policies on bop_integration tables
# (external_entity_map and bop_event_log).
#
# RLS Configuration: See common/rls/__init__.py for centralized policy definitions

from django.db import migrations
from common.rls import get_check_table_exists_sql, get_enable_policy_sql

BOP_INTEGRATION_TABLES = [
    "external_entity_map",
    "bop_event_log",
]


def stamp_bop_integration_rls(apps, schema_editor):
    """Create isolation and insert-check policies on bop_integration tables."""
    if schema_editor.connection.vendor != "postgresql":
        print("RLS is only supported on PostgreSQL. Skipping.")
        return

    stamped = 0
    with schema_editor.connection.cursor() as cursor:
        for table in BOP_INTEGRATION_TABLES:
            cursor.execute(get_check_table_exists_sql(), [table])
            if not cursor.fetchone()[0]:
                print(f"  Skipping {table} (table does not exist)")
                continue

            cursor.execute(get_enable_policy_sql(table))
            stamped += 1

    print(f"  Stamped RLS policies on {stamped} bop_integration table(s)")


def noop_reverse(apps, schema_editor):
    """No-op on rollback to preserve security policies."""
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("bop_integration", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(stamp_bop_integration_rls, noop_reverse),
    ]
