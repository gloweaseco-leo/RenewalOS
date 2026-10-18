"""Run one G1-B migration against an empty dedicated PostgreSQL database.

Do NOT use on an existing production database. Database owner credentials required.
"""
import argparse
import os
from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / 'migrations/postgres/001_tenant_core.sql'


def main():
    cli=argparse.ArgumentParser(description='Apply PostgreSQL G1-B core migration')
    cli.add_argument('--confirm-new-database',action='store_true')
    args=cli.parse_args()
    if not args.confirm_new_database:
        cli.error('requires --confirm-new-database (dedicated empty DB only)')
    dsn=os.environ.get('RENEWAL_PG_MIGRATION_DSN')
    if not dsn:
        cli.error('RENEWAL_PG_MIGRATION_DSN is required')
    import psycopg
    with psycopg.connect(dsn,autocommit=True) as conn:
        found=conn.execute('''SELECT count(*) FROM pg_catalog.pg_tables
                            WHERE schemaname='renewalos' ''').fetchone()[0]
        if found:
            cli.error('renewalos schema contains tables; cannot reapply first migration')
        conn.execute(MIGRATION.read_text(encoding='utf-8'))
        print('G1-B: applied migration 001 to dedicated PostgreSQL database')


if __name__ == '__main__':
    main()
