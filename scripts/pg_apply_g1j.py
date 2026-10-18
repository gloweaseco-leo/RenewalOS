"""Apply the G1-J revocation triggers to a disposable, never-customer CI database."""
import os
from pathlib import Path

def main():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('CI-only migration; production deployment is blocked')
    import psycopg
    dsn = os.environ['RENEWAL_PG_MIGRATION_DSN']
    expected={'001_tenant_core','002_business_write','003_pg_identity','004_oidc_local'}
    with psycopg.connect(dsn) as con:
        versions={v for (v,) in con.execute('SELECT version FROM renewalos.schema_migrations')}
        if versions != expected:
            raise SystemExit('Unexpected schema state; refusing to migrate')
        sql=(Path(__file__).resolve().parents[1]/'migrations/postgres/005_session_revocation.sql').read_text('utf8')
        con.execute(sql)
    print('G1-J revocation migration applied to disposable database only')

if __name__ == '__main__':
    main()
