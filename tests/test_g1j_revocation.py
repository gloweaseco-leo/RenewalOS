"""Recovering a user's role must NEVER resurrect a session issued before revocation."""
import os
import pytest
from renewalos.access import AccessDenied

ADMIN=os.getenv('RENEWAL_PG_MIGRATION_DSN')
AUTH=os.getenv('RENEWAL_PG_AUTH_DSN')
pytestmark=pytest.mark.skipif(not ADMIN or not AUTH, reason='disposable PG16 identity DB required')

@pytest.fixture(scope='module')
def seed():
    import psycopg
    with psycopg.connect(ADMIN) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1j_org','CI only')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1j_org','pool','CI only')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES('g1j_staff','CI staff')")
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1j_org','g1j_staff','member')")
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1j_org','pool','g1j_staff','staff')")
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES('https://idp.g1j.example','g1j-oidc-sub','g1j_staff')")
    yield


def _issue_token():
    # Simulate a verified, pre-bound IdP credential: not a forged external JWT.
    from renewalos.oidc import _issue_external_session
    return _issue_external_session(AUTH,'https://idp.g1j.example','g1j-oidc-sub')['access_token']


def _expect_dead(token):
    from renewalos.pg_auth import identity
    with pytest.raises(AccessDenied): identity(AUTH,token)


def _revoked_in_database(token):
    import hashlib, psycopg
    with psycopg.connect(ADMIN) as con:
        row=con.execute('SELECT revoked_at FROM renewalos_auth.sessions WHERE token_hash=%s',
                        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        assert row and row[0] is not None


def test_disable_reenable_user_cannot_resurrect_old_session(seed):
    import psycopg
    token=_issue_token()
    with psycopg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos.identity_users SET enabled=false WHERE user_id='g1j_staff'")
        con.execute("UPDATE renewalos.identity_users SET enabled=true WHERE user_id='g1j_staff'")
    _expect_dead(token);_revoked_in_database(token)
    assert _issue_token()!=token


def test_store_role_change_cannot_reuse_old_manager_session(seed):
    import psycopg
    token=_issue_token()
    with psycopg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos.store_memberships SET role='manager' WHERE org_id='g1j_org' AND user_id='g1j_staff'")
    _expect_dead(token);_revoked_in_database(token)
    with psycopg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos.store_memberships SET role='staff' WHERE org_id='g1j_org' AND user_id='g1j_staff'")


def test_org_disable_reenable_cannot_resurrect_session(seed):
    import psycopg
    token=_issue_token()
    with psycopg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos.org_memberships SET enabled=false WHERE org_id='g1j_org' AND user_id='g1j_staff'")
        con.execute("UPDATE renewalos.org_memberships SET enabled=true WHERE org_id='g1j_org' AND user_id='g1j_staff'")
    _expect_dead(token);_revoked_in_database(token)


def test_external_identity_binding_disable_reenable_retires_sessions(seed):
    import psycopg
    token=_issue_token()
    with psycopg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=false WHERE user_id='g1j_staff'")
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=true WHERE user_id='g1j_staff'")
    _expect_dead(token);_revoked_in_database(token)
