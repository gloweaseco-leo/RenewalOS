"""Apply G1-E identity migration only to disposable CI database."""
import os
from pathlib import Path

def main():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('Only disposable CI PostgreSQL supported')
    import psycopg
    sql=(Path(__file__).resolve().parents[1]/'migrations/postgres/003_pg_identity.sql').read_text('utf8')
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        v={x[0] for x in con.execute('SELECT version FROM renewalos.schema_migrations')}
        if v!={'001_tenant_core','002_business_write'}:
            raise SystemExit('Unexpected migrations: '+repr(v))
        con.execute(sql)
    print('003_pg_identity migrated')
if __name__=='__main__':main()
