"""OIDC binding and employment access revocation; ephemeral PostgreSQL test only."""
import os
import pytest

psycopg = pytest.importorskip('psycopg')


def test_oidc_binding_revokes_active_session_immediately():
    dsn = os.getenv('RENEWAL_PG_MIGRATION_DSN')
    auth_dsn = os.getenv('RENEWAL_PG_AUTH_DSN')
    if not dsn or not auth_dsn:
        pytest.skip('Requires disposable PG CI environment')
    from renewalos.oidc import _issue_external_session
    from renewalos.pg_auth import identity, authorize_store
    from renewalos.access import AccessDenied
    issuer = 'https://synthetic-g1j.invalid/realm'
    with psycopg.connect(dsn) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES ('g1j_org','Synthetic')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES ('g1j_org','pool','Pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES ('g1j_actor','Synthetic')")
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES ('g1j_org','g1j_actor','member')")
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES ('g1j_org','pool','g1j_actor','manager')")
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES (%s,'g1j-sub','g1j_actor')",(issuer,))
    token = _issue_external_session(auth_dsn, issuer, 'g1j-sub')['access_token']
    assert identity(auth_dsn, token)['user_id'] == 'g1j_actor'
    assert authorize_store(auth_dsn, token, 'g1j_org','pool')['role'] == 'manager'
    with psycopg.connect(dsn) as con:
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=false WHERE user_id='g1j_actor'")
    with pytest.raises(AccessDenied): identity(auth_dsn, token)
    with pytest.raises(AccessDenied): authorize_store(auth_dsn, token,'g1j_org','pool')
    with pytest.raises(AccessDenied): _issue_external_session(auth_dsn,issuer,'g1j-sub')
    with psycopg.connect(dsn) as con:
        con.execute("UPDATE renewalos_auth.oidc_bindings SET enabled=true WHERE user_id='g1j_actor'")
        con.execute("UPDATE renewalos.store_memberships SET enabled=false WHERE user_id='g1j_actor'")
    with pytest.raises(AccessDenied): identity(auth_dsn, token)
