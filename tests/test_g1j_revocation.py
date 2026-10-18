"""Identity binding revocation invalidates an already authenticated session."""
import os
import pytest
from renewalos.access import AccessDenied

psycopg = pytest.importorskip('psycopg')
ISS='https://g1j-identity.synthetic.example'

def test_oidc_binding_disable_revokes_existing_session_immediately():
    admin=os.getenv('RENEWAL_PG_MIGRATION_DSN')
    auth=os.getenv('RENEWAL_PG_AUTH_DSN')
    if not admin or not auth:pytest.skip('Disposable PG CI required')
    from renewalos.oidc import _issue_external_session
    from renewalos.pg_auth import identity
    with psycopg.connect(admin) as con:
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1jorg','Synthetic G1J')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1jorg','pool','Pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES('g1juser','Synthetic employee')")
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1jorg','g1juser','member')")
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1jorg','pool','g1juser','manager')")
        con.execute("INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES(%s,'external-sub','g1juser')",(ISS,))
    result=_issue_external_session(auth,ISS,'external-sub')
    token=result['access_token']
    assert identity(auth,token)['user_id']=='g1juser'
    with psycopg.connect(admin) as con:
        con.execute('UPDATE renewalos_auth.oidc_bindings SET enabled=false WHERE issuer=%s',(ISS,))
    with pytest.raises(AccessDenied): identity(auth,token)
    with pytest.raises(AccessDenied): _issue_external_session(auth,ISS,'external-sub')
    with psycopg.connect(admin) as con:
        con.execute('UPDATE renewalos_auth.oidc_bindings SET enabled=true WHERE issuer=%s',(ISS,))
    with pytest.raises(AccessDenied): identity(auth,token)
    assert _issue_external_session(auth,ISS,'external-sub')['access_token'] != token
