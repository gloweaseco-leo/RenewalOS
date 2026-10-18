"""Apply G1-C additive schema once to a dedicated test database.

Never auto-apply in the application runtime; the migration owner must review it.
"""
import argparse
import os
from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / 'migrations/postgres/002_business_write.sql'

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--confirm-test-database', action='store_true')
    args = p.parse_args()
    if not args.confirm_test_database or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY' or os.getenv('CI') != 'true':
        p.error('G1-C migration runner restricted to ephemeral CI database')
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        rows = con.execute("SELECT version FROM renewalos.schema_migrations ORDER BY version").fetchall()
        if rows != [('001_tenant_core',)]:
            p.error('expected exactly 001_tenant_core; migration already applied or DB unexpected')
        con.execute(SQL.read_text('utf8'))
    print('G1-C PostgreSQL migration 002 applied')

if __name__=='__main__':
    main()
