"""Apply OIDC revocation migration to ephemeral CI PostgreSQL, never customer data."""
import os
from pathlib import Path

def main():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('Disposable CI only')
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        actual={row[0] for row in con.execute('SELECT version FROM renewalos.schema_migrations')}
        expected={'001_tenant_core','002_business_write','003_pg_identity','004_oidc_local'}
        if actual!=expected:raise SystemExit('Unexpected schema version, refusing migration')
        con.execute((Path(__file__).resolve().parents[1]/'migrations/postgres/005_oidc_session_revocation.sql').read_text('utf8'))
    print('005_oidc_session_revocation migrated (CI only)')

if __name__=='__main__':main()
