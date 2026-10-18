"""Disposable CI PostgreSQL test role; never run in customer environments."""
import os
from pathlib import Path


def main():
    if os.getenv('RENEWAL_PG_CI_BOOTSTRAP') != 'I_ACCEPT_CI_ONLY':
        raise SystemExit('CI guard required; refuse to grant test database access')
    if os.getenv('CI') != 'true':
        raise SystemExit('Only GitHub CI may provision the disposable app role')
    dsn=os.environ['RENEWAL_PG_MIGRATION_DSN']
    import psycopg
    with psycopg.connect(dsn) as db:
        db.execute((Path(__file__).parent/'pg_ci_roles.sql').read_text(encoding='utf-8'))
        db.commit()
    print('CI fixture role provisioned')


if __name__ == '__main__':
    main()
