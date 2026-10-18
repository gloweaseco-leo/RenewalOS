"""Apply G1-J synthetic migration to an isolated disposable CI database."""
import os
from pathlib import Path


def main():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI database only')
    import psycopg
    dsn = os.environ['RENEWAL_PG_MIGRATION_DSN']
    with psycopg.connect(dsn) as con:
        versions = {r[0] for r in con.execute('SELECT version FROM renewalos.schema_migrations')}
        required = {'001_tenant_core','002_business_write','003_pg_identity','004_oidc_local'}
        if versions != required:
            raise SystemExit('Unexpected schema state; refusing migration')
        con.execute((Path(__file__).resolve().parents[1] / 'migrations/postgres/005_oidc_session_revocation.sql').read_text('utf8'))
    print('005_oidc_session_revocation migrated (CI only)')

if __name__ == '__main__':
    main()
