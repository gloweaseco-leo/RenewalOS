"""G1-J: revocation must remain effective for already-issued OIDC sessions."""
import os
import pytest

from renewalos.access import AccessDenied
from renewalos.oidc import _issue_external_session, OIDCConfig
from renewalos.pg_auth import identity, authorize_store

try:
    import psycopg
except ImportError:
    psycopg = None

ISSUER='https://synthetic.g1j.invalid/realm'
SUB='g1j-test-sub'
USER='g1j_test_user'


def test_https_oidc_redirect_is_allowed_only_for_loopback():
    fields={
      'RENEWAL_OIDC_ISSUER':ISSUER,
      'RENEWAL_OIDC_CLIENT_ID':'renewalos-local',
      'RENEWAL_OIDC_AUTHORIZATION_ENDPOINT':ISSUER+'/auth',
      'RENEWAL_OIDC_TOKEN_ENDPOINT':ISSUER+'/token',
      'RENEWAL_OIDC_JWKS_URI':ISSUER+'/keys',
      'RENEWAL_OIDC_REDIRECT_URI':'https://127.0.0.1:8443/',
    }
    assert OIDCConfig.from_env(fields).redirect_uri.startswith('https://')
    from renewalos.oidc import OIDCRejected
    with pytest.raises(OIDCRejected):
        OIDCConfig.from_env({**fields,'RENEWAL_OIDC_REDIRECT_URI':'http://real-customer.invalid/'})


def test_synthetic_binding_revocation_is_immediate_and_permanent():
    mig=os.getenv('RENEWAL_PG_MIGRATION_DSN')
    auth=os.getenv('RENEWAL_PG_AUTH_DSN')
    if not mig or not auth or psycopg is None:
        pytest.skip('Disposable PostgreSQL test cluster required')
    with psycopg.connect(mig) as con:
        versions={x[0] for x in con.execute('SELECT version FROM renewalos.schema_migrations')}
        assert '005_oidc_session_revocation' in versions
        con.execute("INSERT INTO renewalos.organizations(org_id,label) VALUES('g1j_test','G1J synthetic')")
        con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES('g1j_test','pool','Pool')")
        con.execute("INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,'G1J fake')",(USER,))
        con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES('g1j_test',%s,'member')",(USER,))
        con.execute("INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role) VALUES('g1j_test','pool',%s,'staff')",(USER,))
        con.execute('INSERT INTO renewalos_auth.oidc_bindings(issuer,subject,user_id) VALUES(%s,%s,%s)',(ISSUER,SUB,USER))
    s1=_issue_external_session(auth,ISSUER,SUB)['access_token']
    assert identity(auth,s1)['user_id']==USER
    assert authorize_store(auth,s1,'g1j_test','pool')['role']=='staff'
    with psycopg.connect(mig) as con:
        con.execute('UPDATE renewalos_auth.oidc_bindings SET enabled=false WHERE issuer=%s AND subject=%s',(ISSUER,SUB))
        assert con.execute('''SELECT revoked_at IS NOT NULL FROM renewalos_auth.sessions
                              WHERE token_hash=%s''',(__import__('hashlib').sha256(s1.encode()).hexdigest(),)).fetchone()[0]
    with pytest.raises(AccessDenied):identity(auth,s1)
    with psycopg.connect(mig) as con:
        con.execute('UPDATE renewalos_auth.oidc_bindings SET enabled=true WHERE issuer=%s AND subject=%s',(ISSUER,SUB))
    with pytest.raises(AccessDenied):identity(auth,s1)
    s2=_issue_external_session(auth,ISSUER,SUB)['access_token']
    assert identity(auth,s2)['user_id']==USER
    with psycopg.connect(mig) as con:
        con.execute('UPDATE renewalos.identity_users SET enabled=false WHERE user_id=%s',(USER,))
    with pytest.raises(AccessDenied):identity(auth,s2)
    with psycopg.connect(mig) as con:
        con.execute('UPDATE renewalos.identity_users SET enabled=true WHERE user_id=%s',(USER,))
    with pytest.raises(AccessDenied):identity(auth,s2)
