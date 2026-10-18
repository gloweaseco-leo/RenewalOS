"""Apply OIDC local identity migration to disposable GitHub CI database ONLY."""
import os
from pathlib import Path

def main():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI database only')
    import psycopg
    dsn=os.environ['RENEWAL_PG_MIGRATION_DSN']
    with psycopg.connect(dsn) as con:
        versions={x[0] for x in con.execute('SELECT version FROM renewalos.schema_migrations')}
        if versions!={'001_tenant_core','002_business_write','003_pg_identity'}:
            raise SystemExit('Unexpected schema state; refusing migration')
        con.execute((Path(__file__).resolve().parents[1]/'migrations/postgres/004_oidc_local.sql').read_text('utf8'))
    print('004_oidc_local migrated (CI only)')

if __name__=='__main__':main()
