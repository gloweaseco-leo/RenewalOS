"""G1-A: fail-closed legacy API and store-scoped auth regression tests."""
from datetime import date, timedelta
import hashlib
import sqlite3
import pytest
from fastapi.testclient import TestClient
from renewalos.access import create_local_user, AccessDenied
from renewalos.db import connect
from renewalos.main import app


@pytest.fixture
def secure(tmp_path, monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'secure.sqlite'))
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    monkeypatch.delenv('RENEWAL_AI_API_KEY',raising=False)
    with TestClient(app) as c:
        create_local_user('alice','ValidLongPassword!2026',{'STORE-A':'manager','STORE-B':'auditor'})
        create_local_user('bob','AnotherSecurePassword!',{'STORE-B':'staff'})
        with connect() as con:
            for store,tag in [('STORE-A','A'),('STORE-B','B')]:
                learner='L-'+tag
                con.execute('INSERT INTO learners(learner_id,family_id,guardian_alias,store_id,contact_consent) VALUES(?,?,?,?,1)',
                            (learner,'Family-'+tag,'Guardian-'+tag,store))
                con.execute('INSERT INTO packages(package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents) VALUES(?,?,?,?,?,?,?,?)',
                            ('P-'+tag,learner,'swim',date.today().isoformat(),(date.today()+timedelta(days=20)).isoformat(),10,3,200000))
                con.execute('INSERT INTO opportunities(opportunity_id,learner_id,package_id,signals_json,priority,reason,rule_advice,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                            ('O-'+tag,learner,'P-'+tag,'{}',70,'reason-'+tag,'advice-'+tag, '2026-10-18T00:00:00'))
                con.execute('INSERT INTO experiment_assignments(family_key,store_id,family_id,arm,assigned_on) VALUES(?,?,?,?,?)',
                            (store+':Family-'+tag,store,'Family-'+tag,'rules','2026-10-18'))
                con.execute('INSERT INTO work_tasks(task_id,opportunity_id,store_id,owner,due_on,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                            ('T-'+tag,'O-'+tag,store,'alice' if tag=='A' else 'bob',date.today().isoformat(),'open','2026-10-18','2026-10-18'))
        yield c


def get_token(c,user,secret):
    r=c.post('/api/auth/login',json={'username':user,'password':secret})
    assert r.status_code==200,r.text
    return r.json()['access_token']


def headers(token):return {'Authorization':'Bearer '+token}


def test_secure_mode_blocks_every_legacy_surface(secure):
    assert secure.get('/api/health').json()['mode']=='SECURE_LOCAL_ALPHA'
    for method,path in [('GET','/static/app.js'),('GET','/api/opportunities'),
                        ('GET','/api/tasks'),('GET','/api/management/overview'),
                        ('POST','/api/demo/reset'),('POST','/api/recompute'),
                        ('POST','/api/import/learners'),('POST','/api/demo/sales/payments'),
                        ('POST','/api/quality/benchmark')]:
        assert secure.request(method,path).status_code==403,(method,path)


def test_authentication_and_no_plaintext_tokens(secure):
    assert secure.post('/api/auth/login',json={'username':'alice','password':'wrong'}).status_code==401
    assert secure.post('/api/auth/login',json={'username':'ghost','password':'wrong'}).status_code==401
    token=get_token(secure,'alice','ValidLongPassword!2026')
    with connect() as con:
        r=con.execute('SELECT password_salt,password_hash FROM access_users WHERE user_id="alice"').fetchone()
        stored=con.execute('SELECT token_hash FROM access_sessions').fetchone()['token_hash']
        assert r['password_hash']!=b'ValidLongPassword!2026'
        assert stored!=token and stored==hashlib.sha256(token.encode()).hexdigest()
    assert secure.get('/api/v1/me',headers=headers(token)).json()['memberships']=={'STORE-A':'manager','STORE-B':'auditor'}
    assert secure.get('/api/v1/me').status_code==401
    assert secure.get('/api/v1/me',headers={'Authorization':'Bearer malformed'}).status_code==401


def test_all_store_read_routes_enforce_scope_at_database_level(secure):
    token=get_token(secure,'alice','ValidLongPassword!2026')
    aa=secure.get('/api/v1/stores/STORE-A/opportunities',headers=headers(token))
    assert aa.status_code==200
    assert [x['learner_id'] for x in aa.json()['items']]==['L-A']
    assert all(x['store_id']=='STORE-A' for x in aa.json()['items'])
    bb=secure.get('/api/v1/stores/STORE-B/tasks',headers=headers(token))
    assert bb.status_code==403  # auditor cannot browse staff cases
    assert secure.get('/api/v1/stores/STORE-UNKNOWN/tasks',headers=headers(token)).status_code==403
    assert secure.get('/api/v1/stores/STORE-UNKNOWN/management',headers=headers(token)).status_code==403


def test_per_store_roles_and_manager_data(secure):
    token=get_token(secure,'alice','ValidLongPassword!2026')
    manager=secure.get('/api/v1/stores/STORE-A/management',headers=headers(token))
    assert manager.status_code==200 and manager.json()['case_count']==1
    assert manager.json()['cases'][0]['store_id']=='STORE-A'
    # Same person is read-only auditor in B, NOT a manager.
    assert secure.get('/api/v1/stores/STORE-B/management',headers=headers(token)).status_code==403
    bob=get_token(secure,'bob','AnotherSecurePassword!')
    assert [x['learner_id'] for x in secure.get('/api/v1/stores/STORE-B/opportunities',headers=headers(bob)).json()['items']]==['L-B']
    assert secure.get('/api/v1/stores/STORE-A/opportunities',headers=headers(bob)).status_code==403
    assert secure.get('/api/v1/stores/STORE-B/management',headers=headers(bob)).status_code==403


def test_logout_and_expiry_and_user_disable(secure):
    token=get_token(secure,'alice','ValidLongPassword!2026')
    assert secure.post('/api/auth/logout',headers=headers(token)).status_code==200
    assert secure.get('/api/v1/me',headers=headers(token)).status_code==401
    token=get_token(secure,'alice','ValidLongPassword!2026')
    with connect() as con:
        con.execute('UPDATE access_sessions SET expires_on=? WHERE user_id=?',('2000-01-01T00:00:00+00:00','alice'))
    assert secure.get('/api/v1/me',headers=headers(token)).status_code==401
    token=get_token(secure,'alice','ValidLongPassword!2026')
    with connect() as con:
        con.execute('UPDATE access_users SET enabled=0 WHERE user_id=?',('alice',))
    assert secure.get('/api/v1/me',headers=headers(token)).status_code==401


def test_origin_and_public_host_stay_blocked(secure):
    assert secure.post('/api/auth/login',json={'username':'alice','password':'ValidLongPassword!2026'},
                       headers={'Origin':'https://evil.example'}).status_code==403
    assert secure.get('/api/health',headers={'Host':'renewalos.example.com'}).status_code==403
    assert secure.get('/api/v1/stores/STORE-A/opportunities',headers={'Host':'renewalos.example.com'}).status_code==403


def test_provisioning_rejects_weak_credentials_and_invalid_roles(secure):
    with pytest.raises(ValueError):create_local_user('evil','short',{'STORE-A':'manager'})
    with pytest.raises(ValueError):create_local_user('foo','long-enough-secret',{'STORE-A':'superadmin'})
    with pytest.raises(sqlite3.IntegrityError):create_local_user('alice','long-enough-secret',{'STORE-B':'staff'})
    with connect() as con:
        assert con.execute('SELECT count(*) AS n FROM access_memberships WHERE user_id="alice"').fetchone()['n']==2


def test_store_denials_are_audited(secure):
    token=get_token(secure,'bob','AnotherSecurePassword!')
    assert secure.get('/api/v1/stores/STORE-A/tasks',headers=headers(token)).status_code==403
    with connect() as con:
        rows=con.execute('SELECT action,result,store_id FROM access_audit WHERE user_id="bob" ORDER BY audit_id').fetchall()
    assert any(x['action']=='store_access' and x['result']=='denied' and x['store_id']=='STORE-A' for x in rows)


def test_staff_only_sees_their_assigned_work(secure):
    bob=get_token(secure,'bob','AnotherSecurePassword!')
    # A second task and opportunity in B are invisible to bob, even though same store.
    with connect() as con:
        con.execute("INSERT INTO learners(learner_id,family_id,guardian_alias,store_id,contact_consent) VALUES('L-C','Family-C','Guardian-C','STORE-B',1)")
        con.execute("INSERT INTO packages(package_id,learner_id,course_type,purchased_on,expires_on,purchased_sessions,remaining_sessions,price_cents) VALUES('P-C','L-C','swim','2026-10-01','2026-12-01',10,3,200000)")
        con.execute("INSERT INTO opportunities(opportunity_id,learner_id,package_id,signals_json,priority,reason,rule_advice,updated_at) VALUES('O-C','L-C','P-C','{}',80,'reason','advice','2026-10-18')")
        con.execute("INSERT INTO work_tasks(task_id,opportunity_id,store_id,owner,due_on,status,created_at,updated_at) VALUES('T-C','O-C','STORE-B','colleague','2026-10-18','open','2026-10-18','2026-10-18')")
    tasks=secure.get('/api/v1/stores/STORE-B/tasks',headers=headers(bob)).json()['items']
    opps=secure.get('/api/v1/stores/STORE-B/opportunities',headers=headers(bob)).json()['items']
    assert [t['task_id'] for t in tasks]==['T-B']
    assert [o['opportunity_id'] for o in opps]==['O-B']


def test_invalid_runtime_fails_startup(tmp_path,monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'invalid.sqlite'))
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','production')
    with pytest.raises(RuntimeError,match='不支持的运行模式'):
        with TestClient(app): pass


def test_secure_login_page_no_legacy_code(secure):
    html=secure.get('/').text
    assert '员工登录' in html and '/static/secure.js' in html
    assert '载入合成数据' not in html
    js=secure.get('/static/secure.js')
    assert js.status_code==200 and 'localStorage' in js.text
    assert secure.get('/static/app.js').status_code==403


def test_remote_peer_spoofing_local_host_is_rejected(tmp_path,monkeypatch):
    monkeypatch.setenv('RENEWAL_DB_PATH',str(tmp_path/'remote.sqlite'))
    monkeypatch.setenv('RENEWAL_RUNTIME_MODE','secure_local')
    with TestClient(app, client=('203.0.113.8', 40123)) as c:
        r=c.get('/api/health',headers={'Host':'localhost'})
        assert r.status_code==403
