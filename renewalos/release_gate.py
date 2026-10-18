"""G1-G public-release blocker and local PostgreSQL readiness checks.

This module intentionally DOES NOT grant production deployment permission.
It permits disposable/local synthetic evaluation only, until an audited
external identity provider and lawful customer data workflow are delivered.
Never include passwords, DSNs, access tokens or SQL errors in responses.
"""
import os
from urllib.parse import urlparse


class ReleaseBlocked(RuntimeError):
    pass


PUBLIC_PLATFORMS = ("VERCEL", "K_SERVICE", "DYNO", "FLY_APP_NAME", "RENDER_SERVICE_ID")
FORBIDDEN_USERS = {"postgres", "root", "admin", "superuser"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
REQUIRED_MIGRATIONS = {"001_tenant_core", "002_business_write", "003_pg_identity"}


def assert_local_only(environ=None):
    env = os.environ if environ is None else environ
    profile = env.get("RENEWAL_DEPLOYMENT_TARGET", "local")
    if profile != "local" or any(env.get(k) for k in PUBLIC_PLATFORMS):
        raise ReleaseBlocked("Public deployment is blocked: production identity and data gates are incomplete")
    base = env.get("RENEWAL_PUBLIC_BASE_URL", "")
    if base:
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOCAL_HOSTS or parsed.username or parsed.password:
            raise ReleaseBlocked("Only local loopback base URLs are allowed")
    return "LOCAL_SYNTHETIC_ONLY"


def assert_dedicated_pg_roles(environ=None):
    env = os.environ if environ is None else environ
    auth = env.get("RENEWAL_PG_AUTH_DSN", "")
    app = env.get("RENEWAL_PG_APP_DSN", "")
    if not auth or not app or auth == app:
        raise ReleaseBlocked("Distinct identity and business DSNs are required")
    a, b = urlparse(auth), urlparse(app)
    for p in (a, b):
        if (p.scheme not in ("postgresql", "postgres") or p.hostname not in LOCAL_HOSTS
                or not p.username or p.username.lower() in FORBIDDEN_USERS or not p.path.strip("/")):
            raise ReleaseBlocked("PostgreSQL must use least-privilege, loopback-only roles")
    if a.username == b.username or a.hostname != b.hostname or a.path != b.path or a.port != b.port:
        raise ReleaseBlocked("Identity and business must use different roles on the same local test database")
    return True


def local_readiness(environ=None, driver=None):
    """Return only a non-sensitive local readiness status; never a public deployment approval."""
    env = os.environ if environ is None else environ
    try:
        assert_local_only(env)
        if env.get("RENEWAL_RUNTIME_MODE") != "secure_local" or env.get("RENEWAL_AUTH_BACKEND") not in ("postgres", "oidc"):
            return {"ready": False, "profile": "LOCAL_SYNTHETIC_ONLY", "reason": "PG_SECURE_MODE_REQUIRED"}
        assert_dedicated_pg_roles(env)
        if driver is None:
            from .pg_store import _driver
            driver = _driver()
        with driver.connect(env["RENEWAL_PG_APP_DSN"], connect_timeout=3) as con:
            versions = {row[0] for row in con.execute("SELECT version FROM renewalos.schema_migrations")}
        needed = REQUIRED_MIGRATIONS | ({"004_oidc_local"} if env.get("RENEWAL_AUTH_BACKEND")=="oidc" else set())
        if not needed.issubset(versions):
            return {"ready": False, "profile": "LOCAL_SYNTHETIC_ONLY", "reason": "MIGRATIONS_INCOMPLETE"}
        with driver.connect(env["RENEWAL_PG_AUTH_DSN"], connect_timeout=3) as con:
            con.execute("SELECT state_hash FROM renewalos_auth.oidc_flows LIMIT 0"
                        if env.get("RENEWAL_AUTH_BACKEND")=="oidc"
                        else "SELECT user_id FROM renewalos_auth.credentials LIMIT 0")
        return {"ready": True, "profile": "LOCAL_SYNTHETIC_ONLY"}
    except Exception:
        return {"ready": False, "profile": "LOCAL_SYNTHETIC_ONLY", "reason": "UNAVAILABLE_OR_BLOCKED"}
