"""Actual pg_dump/pg_restore rehearsal in disposable CI PostgreSQL only.

Source must be the exact local CI database `renewalos_ci`. Destination is created
and dropped for the drill, never a production or user-supplied database name.
Uses synthetic fixtures seeded by G1-E TCP E2E and G1-F browser E2E.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

SOURCE = "renewalos_ci"
DESTINATION = "renewalos_ci_g1g_restored"
TABLES = (
    "renewalos.organizations", "renewalos.stores", "renewalos.identity_users",
    "renewalos.org_memberships", "renewalos.store_memberships", "renewalos.households",
    "renewalos.learners", "renewalos.course_packages", "renewalos.renewal_opportunities",
    "renewalos.work_tasks", "renewalos.followup_events", "renewalos.renewal_contracts",
    "renewalos.cash_events", "renewalos.business_action_events", "renewalos_auth.credentials",
    "renewalos_auth.sessions", "renewalos_auth.audit", "renewalos.schema_migrations",
)


def ci_guard(env=None):
    env = os.environ if env is None else env
    if env.get("CI") != "true" or env.get("RENEWAL_PG_CI_BOOTSTRAP") != "I_ACCEPT_CI_ONLY":
        raise RuntimeError("Backup rehearsal may run only in disposable CI")
    dsn = env.get("RENEWAL_PG_MIGRATION_DSN", "")
    parsed = urlparse(dsn)
    if (parsed.scheme not in ("postgresql", "postgres") or parsed.hostname != "127.0.0.1"
            or parsed.path != "/" + SOURCE or parsed.username != "postgres"):
        raise RuntimeError("Refuse non-CI/non-local database backup")
    return dsn


def fingerprint(conn):
    # Static table identifiers only; no SQL input from environment or user.
    result = {}
    for table in TABLES:
        result[table] = conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
    result["contract_total"] = conn.execute(
        "SELECT COALESCE(SUM(contracted_amount_cents),0) FROM renewalos.renewal_contracts"
    ).fetchone()[0]
    result["cash_total"] = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN kind='payment' THEN amount_cents ELSE -amount_cents END),0) FROM renewalos.cash_events"
    ).fetchone()[0]
    result["versions"] = tuple(sorted(row[0] for row in conn.execute("SELECT version FROM renewalos.schema_migrations")))
    return result


def main():
    dsn = ci_guard()
    for executable in ("pg_dump", "pg_restore"):
        if not shutil.which(executable):
            raise RuntimeError("PostgreSQL client utility unavailable: " + executable)
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    with psycopg.connect(dsn) as conn:
        before = fingerprint(conn)
    if before["renewalos.renewal_contracts"] < 1 or before["renewalos.cash_events"] < 2:
        raise RuntimeError("Cannot rehearse restore without synthetic transaction fixtures")
    with tempfile.TemporaryDirectory(prefix="renewalos-g1g-") as tmp:
        archive = str(Path(tmp) / "synthetic-ci.pgdump")
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--dbname=" + dsn,
                        "--file=" + archive], check=True, capture_output=True, timeout=80)
        created = False
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                if conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DESTINATION,)).fetchone():
                    raise RuntimeError("Disaster recovery destination already exists; refusing overwrite")
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DESTINATION)))
                created = True
            restored_dsn = make_conninfo(dsn, dbname=DESTINATION)
            subprocess.run(["pg_restore", "--no-owner", "--no-acl", "--exit-on-error",
                            "--dbname=" + restored_dsn, archive], check=True, capture_output=True, timeout=80)
            with psycopg.connect(restored_dsn) as con:
                after = fingerprint(con)
            if before != after:
                raise RuntimeError("PostgreSQL backup and restore reconciliation failed")
            print("G1-G disposable PostgreSQL pg_dump/pg_restore verified; finance counts and migration versions match")
        finally:
            if created:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DESTINATION)))


if __name__ == "__main__":
    main()
