"""G1-B PostgreSQL tenant-scoped read adapter (not wired to legacy API).

Trusted backend must validate the bearer principal before passing its user_id.
No anonymous access, no direct client database credentials, no production claims.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import re

ID = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


class TenantAccessError(PermissionError):
    pass


@dataclass(frozen=True)
class TenantScope:
    org_id: str
    store_id: str
    user_id: str

    def __post_init__(self):
        if not all(isinstance(s, str) and ID.fullmatch(s)
                   for s in (self.org_id, self.store_id, self.user_id)):
            raise ValueError("valid organization, store and verified user IDs required")


def _driver():
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError("install renewalos-mvp[postgres] to use PostgreSQL") from e
    return psycopg


@contextmanager
def tenant_transaction(dsn: str, scope: TenantScope, *, roles=("manager", "staff")):
    """Isolated transaction; GUC state never survives connection close.

    The user_id MUST come from validated authentication, never a request body.
    This DB adapter provides defense in depth, not full token verification.
    """
    if not dsn or not isinstance(scope, TenantScope):
        raise ValueError("database DSN and trusted tenant scope are required")
    with _driver().connect(dsn) as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('renewalos.org_id', %s, true)", (scope.org_id,))
            conn.execute("SELECT set_config('renewalos.store_id', %s, true)", (scope.store_id,))
            conn.execute("SELECT set_config('renewalos.actor_id', %s, true)", (scope.user_id,))
            membership = conn.execute('''
                SELECT role FROM renewalos.store_memberships
                WHERE org_id=%s AND store_id=%s AND user_id=%s AND enabled
            ''', (scope.org_id,scope.store_id,scope.user_id)).fetchone()
            if membership is None or membership[0] not in roles:
                raise TenantAccessError("not authorized for this store")
            yield conn


def list_store_opportunities(dsn, scope: TenantScope):
    with tenant_transaction(dsn, scope) as conn:
        role = conn.execute('''SELECT role FROM renewalos.store_memberships
                  WHERE org_id=%s AND store_id=%s AND user_id=%s AND enabled''',
                  (scope.org_id,scope.store_id,scope.user_id)).fetchone()[0]
        # A staff member may only read opportunities actually assigned to them.
        result = conn.execute('''SELECT opportunity_id,source_package_id,stage,priority
                 FROM renewalos.renewal_opportunities
                 WHERE org_id=%s AND store_id=%s
                   AND (%s='manager' OR assigned_user_id=%s)
                 ORDER BY priority DESC,opportunity_id''',
                 (scope.org_id,scope.store_id,role,scope.user_id))
        return [dict(zip(('opportunity_id','source_package_id','stage','priority'),row))
                for row in result.fetchall()]


def list_assigned_tasks(dsn, scope: TenantScope):
    with tenant_transaction(dsn, scope) as conn:
        role=conn.execute('''SELECT role FROM renewalos.store_memberships
                WHERE org_id=%s AND store_id=%s AND user_id=%s''',
                (scope.org_id,scope.store_id,scope.user_id)).fetchone()[0]
        result=conn.execute('''SELECT task_id,opportunity_id,assigned_user_id,status,due_on
                    FROM renewalos.work_tasks WHERE org_id=%s AND store_id=%s
                    AND (%s='manager' OR assigned_user_id=%s)
                    ORDER BY due_on,task_id''',
                    (scope.org_id,scope.store_id,role,scope.user_id))
        return [dict(zip(('task_id','opportunity_id','assigned_user_id','status','due_on'),row))
                for row in result.fetchall()]


def contract_net_cash(dsn, scope: TenantScope, contract_id: str):
    # Financial summary is a manager-only surface until distinct finance roles exist.
    with tenant_transaction(dsn, scope, roles=('manager',)) as conn:
        row=conn.execute('''SELECT coalesce(sum(CASE WHEN kind='payment' THEN amount_cents
                          ELSE -amount_cents END),0) FROM renewalos.cash_events
                    WHERE org_id=%s AND store_id=%s AND contract_id=%s''',
                    (scope.org_id,scope.store_id,contract_id)).fetchone()
        return row[0]
