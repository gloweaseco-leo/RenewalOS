"""Apply G1-J synthetic OIDC session revocation migration in disposable CI only."""
import os
from pathlib import Path

def main():
    if os.getenv('CI') != 'true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI database only')
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        versions = {r[0] for r in con.execute('SELECT version FROM renewalos.schema_migrations')}
        expected = {'001_tenant_core','002_business_write','003_pg_identity','004_oidc_local'}
        if versions != expected:
            raise SystemExit('Unexpected migration state: fail closed')
        sql = Path(__file__).resolve().parents[1] / 'migrations/postgres/005_oidc_session_revocation.sql'
        con.execute(sql.read_text('utf8'))
    print('005_oidc_session_revocation migrated in disposable CI')

if __name__ == '__main__': main()
