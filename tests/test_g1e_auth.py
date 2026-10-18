"""Dedicated PostgreSQL identity acceptance; never use real user records."""
import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from renewalos.main import app
from renewalos.pg_auth import login, identity, authorize_store, logout
from renewalos.access import AccessDenied

pg=pytest.importorskip('psycopg')
ADMIN=os.getenv('RENEWAL_PG_MIGRATION_DSN')
AUTH=os.getenv('RENEWAL_PG_AUTH_DSN')
APP=os.getenv('RENEWAL_PG_TEST_DSN')
pytestmark=pytest.mark.skipif(not (ADMIN and AUTH and APP),reason='disposable PostgreSQL test service required')


def _seed_user(con,uid,pwd):
    con.execute('INSERT INTO renewalos.identity_users(user_id,display_alias) VALUES(%s,%s)',(uid,uid))
    salt=bytes(range(16))
    hashed=hashlib.pbkdf2_hmac('sha256',pwd.encode(),salt,390000)
    con.execute('''INSERT INTO renewalos_auth.credentials(user_id,password_salt,password_hash,iterations)
                   VALUES(%s,%s,%s,390000)''',(uid,salt,hashed))


@pytest.fixture(scope='module',autouse=True)
def seed():
    if not ADMIN or not AUTH or not APP:yield;return
    with pg.connect(ADMIN) as con:
        for org in ('g1e_alpha','g1e_beta'):
            con.execute('INSERT INTO renewalos.organizations(org_id,label) VALUES(%s,%s)',(org,org))
            con.execute("INSERT INTO renewalos.stores(org_id,store_id,label) VALUES(%s,'pool','pool')",(org,))
        _seed_user(con,'g1e_multi','G1E_Dual_Store_Login_2026')
        _seed_user(con,'g1e_other','G1E_Other_Login_2026')
        for org,uid,role in [('g1e_alpha','g1e_multi','manager'),('g1e_beta','g1e_multi','staff'),('g1e_beta','g1e_other','manager')]:
            con.execute("INSERT INTO renewalos.org_memberships(org_id,user_id,role) VALUES(%s,%s,'member')",(org,uid))
            con.execute('''INSERT INTO renewalos.store_memberships(org_id,store_id,user_id,role)
                           VALUES(%s,'pool',%s,%s)''',(org,uid,role))
    yield


def test_dedicated_database_roles_have_separate_access():
    with pg.connect(APP) as con:
        with pytest.raises(pg.errors.InsufficientPrivilege):
            con.execute('SELECT * FROM renewalos_auth.credentials')
    with pg.connect(AUTH) as con:
        with pytest.raises(pg.errors.InsufficientPrivilege):
            con.execute('SELECT * FROM renewalos.identity_users')


def test_pg_session_compound_org_store_and_revocation():
    with pytest.raises(AccessDenied):login(AUTH,'g1e_multi','wrong-password')
    result=login(AUTH,'g1e_multi','G1E_Dual_Store_Login_2026')
    assert result['identity_backend']=='postgres'
    assert result['memberships']=={'g1e_alpha:pool':'manager','g1e_beta:pool':'staff'}
    token=result['access_token']
    assert identity(AUTH,token)['memberships']==result['memberships']
    assert authorize_store(AUTH,token,'g1e_alpha','pool')['role']=='manager'
    assert authorize_store(AUTH,token,'g1e_beta','pool')['role']=='staff'
    with pytest.raises(AccessDenied):authorize_store(AUTH,token,'g1e_gamma','pool')
    logout(AUTH,token)
    with pytest.raises(AccessDenied):identity(AUTH,token)


def test_membership_disable_invalidates_live_token():
    token=login(AUTH,'g1e_other','G1E_Other_Login_2026')['access_token']
    with pg.connect(ADMIN) as con:
        con.execute("UPDATE renewalos.identity_users SET enabled=false WHERE user_id='g1e_other'")
    try:
        with pytest.raises(AccessDenied):identity(AUTH,token)
    finally:
        with pg.connect(ADMIN) as con:
            con.execute("UPDATE renewalos.identity_users SET enabled=true WHERE user_id='g1e_other'")


def test_pg_http_auth_no_sqlite_and_legacy_routes_disabled(monkeypatch,tmp_path):
    sentinel=tmp_path/'forbidden_sqlite.db'
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_AUTH_BACKEND','postgres')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(sentinel))
    monkeypatch.setenv('RENEWAL_PG_AUTH_DSN',AUTH)
    monkeypatch.setenv('RENEWAL_PG_APP_DSN',APP)
    with TestClient(app) as c:
        r=c.post('/api/auth/login',json={'username':'g1e_multi','password':'G1E_Dual_Store_Login_2026'})
        assert r.status_code==200,r.text
        token=r.json()['access_token'];headers={'Authorization':'Bearer '+token}
        assert c.get('/api/v1/me',headers=headers).json()['memberships']['g1e_beta:pool']=='staff'
        assert c.get('/api/v1/stores/pool/tasks',headers=headers).status_code==404
        assert c.get('/api/v1/orgs/g1e_alpha/stores/pool/tasks',headers=headers).status_code==200
        assert c.get('/api/v1/orgs/g1e_beta/stores/pool/management',headers=headers).status_code==403
        assert c.get('/api/v1/orgs/g1e_alpha/stores/pool/management',headers=headers).status_code==200
        assert c.get('/api/demo/reset',headers=headers).status_code==403
        assert c.post('/api/auth/logout',headers=headers,json={}).status_code==200
        assert c.get('/api/v1/me',headers=headers).status_code==401
    assert not sentinel.exists(), 'Postgres identity mode must not open SQLite at all'


def test_pg_startup_requires_distinct_dedicated_dsns(monkeypatch,tmp_path):
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.setenv('RENEWAL_AUTH_BACKEND','postgres')
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'must-not-exist.db'))
    monkeypatch.setenv('RENEWAL_PG_AUTH_DSN',APP)
    monkeypatch.setenv('RENEWAL_PG_APP_DSN',APP)
    with pytest.raises(RuntimeError,match='distinct configured roles'):
        with TestClient(app):pass
