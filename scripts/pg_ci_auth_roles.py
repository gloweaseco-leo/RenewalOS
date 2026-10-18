"""Grant identity-only role, disposable CI database only."""
import os
from pathlib import Path

def main():
    if os.getenv('CI')!='true' or os.getenv('RENEWAL_PG_CI_BOOTSTRAP')!='I_ACCEPT_CI_ONLY':
        raise SystemExit('CI guard required')
    import psycopg
    with psycopg.connect(os.environ['RENEWAL_PG_MIGRATION_DSN']) as con:
        con.execute((Path(__file__).parent/'pg_ci_auth_roles.sql').read_text('utf8'))
    print('CI auth role configured')
if __name__=='__main__':main()
